# ADR-001: OpenAI-compatible API and canonical schema

- **Status:** accepted
- **Date:** 2026-11-04
- **Milestone:** M0 (decision), implemented in M1 (T05 canonical schema, T07 OpenAI adapter, T08 API surface)
- **Deciders:** Switchyard maintainers
- **Requirements:** FR-01, FR-02, FR-04, FR-08, FR-09, FR-10, FR-11, FR-12, FR-13, NFR-18
- **Related:** [ADR-002](0002-runtime-ecs-fargate.md) · ADR-005 (streaming semantics) · ADR-007 (capability registry)

## Context

Switchyard sits between application code and three LLM providers (OpenAI, then Anthropic, then
Gemini). Each provider has its own wire format:

| Concern | OpenAI | Anthropic | Gemini |
|---|---|---|---|
| System prompt | `system` message in `messages` | top-level `system` field | `systemInstruction` |
| Tool calls | `tool_calls[]` with `id` | `tool_use` content blocks | `functionCall` parts (no stable ID) |
| Usage | `prompt_tokens` / `completion_tokens` | `input_tokens` / `output_tokens`, cache tokens | `usageMetadata` |
| Stream shape | `data:` chunks, `[DONE]` | typed SSE events (`message_start`, `content_block_delta`, ...) | chunked JSON |

The problems this gateway exists to solve (plan §1) include vendor lock-in: provider SDK code
spread across every service. Clients must be able to adopt the gateway by changing **only
`base_url` and the API key** (FR-01). At the same time, the gateway's own features (routing,
cross-provider fallback, exact caching, cost accounting, the lifecycle state machine) need one
internal shape to reason about. Two questions follow: what does the outside world see, and what
does the inside of the gateway work on?

## Decision drivers

1. **Zero-change adoption** — existing OpenAI SDKs (Python, TypeScript, LangChain, etc.) must work unmodified.
2. **Cross-provider fallback** — a request that starts on OpenAI must be replayable on Anthropic or Gemini (plan §6).
3. **No silent data loss** — an unsupported field must never be dropped without the client knowing (FR-10).
4. **Pure, testable domain** — the internal model lives in `domain/` with no I/O and is property-testable (FR-13, ADR-000).
5. **Deterministic cache keys and cost** — one normalized shape to hash and price (NFR-18).
6. **Bounded maintenance** — adding a provider should mean writing one adapter, not touching routing or billing.

## Considered options

### Option A — OpenAI wire format outside, canonical schema inside (chosen)

Expose `/v1/chat/completions` and `/v1/models` in OpenAI format. Translate every request into
`CanonicalRequest`, and every provider result into `CanonicalResponse` or a `StreamEvent` sequence
(`domain/schema.py`). Each adapter owns the two-way translation.

- Good: clients switch with a `base_url` change; the whole OpenAI SDK ecosystem works on day one.
- Good: routing, fallback, caching and billing see exactly one shape, so they are written once.
- Good: pydantic v2 models with `extra="forbid"` turn unknown fields into a 400 automatically.
- Good: stream events carry sequence numbers and exactly one terminal event, so stream correctness is testable in the domain.
- Bad: two translations per request (client → canonical → provider), with a small CPU cost inside the p95 < 15 ms overhead budget (NFR-01).
- Bad: the canonical schema is a contract; a new field touches all three adapters and their fixtures.

### Option B — Custom native Switchyard API

Design a clean, provider-neutral API and ship Switchyard SDKs.

- Good: full control over naming, error model and extension points.
- Bad: every client needs a new SDK and code changes, which reintroduces the lock-in the gateway is meant to remove.
- Bad: three or more SDKs to build and maintain; no existing tooling works.

### Option C — Transparent pass-through proxy

Forward provider-native payloads and add only auth, rate limits and logging.

- Good: least code; new provider features work immediately.
- Bad: cross-provider fallback is impossible, since an OpenAI payload cannot be sent to Anthropic.
- Bad: the cache key, cost estimator and capability matcher would each need per-provider branches.
- Bad: provider types leak into the application layer, breaking ADR-000 layering.

### Option D — OpenAI format end-to-end (no canonical layer)

Use the OpenAI request/response objects as the internal model too.

- Good: one fewer mapping; less code in M1.
- Bad: OpenAI's model has no slots for Anthropic cache tokens, reasoning tokens or `usage_source`; the domain would inherit a schema it does not own.
- Bad: any OpenAI API change becomes a domain change; fields it adds would pass through unvalidated.

## Decision

Option A. The public surface is the OpenAI Chat Completions format: `POST /v1/chat/completions`
(including `stream=true` SSE ending with `data: [DONE]`) and `GET /v1/models`. Errors use the
OpenAI error-object shape with Switchyard `type`/`code` values from the normalized taxonomy (FR-08).

Internally the gateway works only on `CanonicalRequest`, `CanonicalResponse` and the
`StreamEvent` union (`StreamStart`, `ContentDelta`, `ToolCallDelta`, `UsageEvent`, `StreamEnd`,
`StreamError`), all frozen pydantic models with `extra="forbid"`. Rules:

- Every supported field is mapped explicitly; every unknown top-level field returns **400 `InvalidRequestError`**.
- Provider-specific options go in one namespaced `provider_extensions` field, validated per provider.
- `CanonicalResponse` always carries finish reason, tool calls with IDs, usage (input, output, cached, reasoning), provider request ID, resolved provider/model and `usage_source: reported | estimated`.

## Consequences

**Positive**
- Adoption is a one-line change for any OpenAI SDK user, which is the strongest argument in a portfolio demo.
- Fallback, caching, budgets and tracing are provider-agnostic and live in pure, unit-testable code.
- FR-10 is provable: a round-trip test covers every supported field and a rejection test covers unknown ones.
- Adding a provider is bounded to one adapter plus recorded contract fixtures (T11, T12, T13).

**Negative**
- OpenAI-only features not yet modelled (for example audio or new request fields) return 400 until added to the schema; this is deliberate but visible to users.
- Schema changes are cross-cutting: every adapter and contract fixture must be updated in the same PR.
- Lossy corners remain where providers differ (for example Gemini tool calls lack native IDs, so the adapter must synthesize stable ones).
- Translation adds a small, measured cost to every request; it is tracked against NFR-01 in the M10 load test.

# Requirements

> Source of truth: `.claude/project_memory/project_plan.md` (Plan v2 + user-confirmed defaults, 2026-11-04).
> Each requirement is tagged with its milestone `[Mx]`. "§n" refers to the plan section.

## Problem Statement
Teams calling LLM providers directly suffer from provider outages taking features down, unbounded cost (runaway agent loops), vendor lock-in through provider-specific SDK code, no visibility into why a request cost or took what it did, double billing when clients retry, and paying repeatedly for identical deterministic prompts. Switchyard is an execution and governance platform for LLM calls: an OpenAI-compatible gateway that normalizes three providers (OpenAI, Anthropic, Gemini), routes capability-aware with resilience, enforces per-tenant security, limits and budgets, guarantees exactly-once settlement, and makes every request's cost and latency explainable from a single trace.

## Functional Requirements

### API
- FR-01 [M1]: Expose `POST /v1/chat/completions` compatible with the OpenAI Chat Completions wire format; an unmodified OpenAI SDK client works by changing only `base_url` and API key.
- FR-02 [M1]: Expose `GET /v1/models` listing only models routable for the calling tenant (status `active`), in OpenAI list format.
- FR-03 [M0]: Expose `GET /healthz` returning 200 when the process is up; usable as the compose/ECS health check.
- FR-04 [M1]: Support `stream=true` via SSE in OpenAI chunk format, terminated by `data: [DONE]` on success.
- FR-05 [M1]: Middleware assigns a `request_id` to every request (returned in a response header) before any other processing.
- FR-06 [M1]: Middleware enforces request body size limits and rejects oversized bodies with 413 before parsing.
- FR-07 [M1]: Admission, caching, routing, execution and settlement are implemented in explicit application services (`GatewayService`, `ExecutionService`, `BudgetService`, `IdempotencyService`, `CacheService`), not in middleware. Middleware is limited to request ID, auth/tenant context and size limits.
- FR-08 [M1]: Errors are returned in OpenAI error-object shape with a Switchyard error `type`/`code` from the normalized taxonomy (FR-62).

### Canonical schema
- FR-09 [M1]: Canonical request model supports `model`, `messages`, `tools`, `tool_choice`, `temperature`, `top_p`, `max_tokens`, `stop`, `response_format` (incl. JSON schema), parallel tool calls, tool-call IDs, and provider extensions in a single namespaced field.
- FR-10 [M1]: Any request field that is not supported is rejected with 400 or explicitly mapped; a test proves no field is silently dropped (round-trip of every supported field, rejection of every unknown field).
- FR-11 [M1]: Canonical response includes finish reason, tool calls with IDs, usage (input, output, cached, reasoning tokens), provider request ID, resolved provider and model, and `usage_source: reported | estimated`.
- FR-12 [M1]: Canonical stream events carry monotonically increasing sequence numbers and exactly one terminal event (success or typed error) per stream.
- FR-13 [M1]: Domain modules (`schema.py`, `errors.py`, `capabilities.py`, `lifecycle.py`, `routing.py`, `pricing.py`) are pure: no I/O imports (enforced by a test or import-lint rule).

### Provider adapters
- FR-14 [M1]: A common adapter interface (`adapters/base.py`) converts canonical request → provider request and provider output → canonical response / stream events, for both streaming and non-streaming, including tools and usage.
- FR-15 [M1]: OpenAI adapter implements streaming, tool calling (incl. parallel tool calls) and usage reporting.
- FR-16 [M2]: Anthropic adapter implements the same contract, validated by recorded fixtures.
- FR-17 [M2]: Gemini adapter implements the same contract, validated by recorded fixtures.
- FR-18 [M2]: A single shared contract test suite runs unchanged against all three adapters and passes on each.
- FR-19 [M1]: Adapters validate every provider chunk; a malformed chunk produces a normalized error event, never an unhandled exception or corrupt output.
- FR-20 [M1]: Adapters map provider errors to the normalized error taxonomy (FR-62) and surface `Retry-After` when present.
- FR-21 [M4]: Adapters support cancellation: cancelling the adapter call aborts the underlying HTTP request to the provider.
- FR-22 [M5]: Provider base URLs are fixed in code/registry; tenants cannot supply custom provider base URLs.

### Capability registry
- FR-23 [M2]: `config/models.yaml` declares each model with provider, capabilities (`streaming`, `tools`, `parallel_tools`, `structured_output`), `context_window`, `max_output_tokens`, pricing (`input_per_mtok`, `output_per_mtok`, `cached_input_per_mtok`), `pricing_version`, and `status` (`active | deprecated | disabled`).
- FR-24 [M2]: Registry is loaded into typed models and validated at startup; invalid registry fails startup.
- FR-25 [M2]: CI test fails if any routable model lacks a pricing or capability entry.
- FR-26 [M2]: `disabled` models are never routable; `deprecated` models remain routable but are flagged in logs/metrics.
- FR-27 [M2]: `pricing.py` computes cost from usage (input, output, cached input) and pricing for a given `pricing_version`, deterministically.

### Routing
- FR-28 [M3]: Routing pipeline is: filter by capability → filter by health (breaker state) → rank by strategy, producing an ordered candidate chain.
- FR-29 [M3]: Capability matcher excludes models that do not support the request's tools, parallel tools, streaming, structured output, or whose context window / max output cannot fit the request.
- FR-30 [M3]: Strategy `fallback`: fixed ordered chain; advance only on eligible failures.
- FR-31 [M3]: Strategy `cheapest_capable`: lowest estimated cost among models meeting all request capabilities.
- FR-32 [M3]: Strategy `lowest_latency`: lowest EWMA latency among healthy eligible models.
- FR-33 [M3]: Strategy `weighted`: weighted split across eligible models; observed distribution converges to configured weights (statistical test).
- FR-34 [M3]: Every fallback candidate satisfies the original request's capabilities (property test: 100% of generated chains are capability-compatible).
- FR-35 [M3]: When no candidate is eligible, return a typed 400 (capability mismatch) or 503 (no healthy candidate), never an untyped error.

### Request lifecycle
- FR-36 [M1]: Lifecycle states: `RECEIVED, ADMITTED, CACHE_HIT, ROUTED, ATTEMPTING, RETRY_WAIT, FALLBACK, STREAMING, COMPLETED, FAILED, CANCELLED, REJECTED, SETTLED`, with only the transitions in §4 permitted; illegal transitions raise.
- FR-37 [M1] (Invariant 1): Every logical request has a unique `request_id`, and every provider attempt has a unique `attempt_id` linked to it.
- FR-38 [M1] (Invariant 2): Every request reaches exactly one terminal state (`COMPLETED | FAILED | CANCELLED | REJECTED`) and exactly one idempotent settlement (`SETTLED`); hypothesis state-machine tests prove this for arbitrary event sequences.
- FR-39 [M1] (Invariant 3): Retry or fallback is only allowed from `ATTEMPTING` and only before the first token is emitted to the client; transitions to `RETRY_WAIT`/`FALLBACK` after `STREAMING` are rejected.
- FR-40 [M4] (Invariant 4): Cancellation propagates client → gateway → adapter → provider; a test proves the provider connection is closed after client disconnect.
- FR-41 [M6] (Invariant 5): Usage from every billable attempt, including failed attempts that consumed tokens, is recorded and included in settlement.

### Streaming semantics
- FR-42 [M4]: Failure before the first token: retry or fall back if the error is eligible.
- FR-43 [M4]: Failure after the first token: end the stream with a typed error event; never switch provider mid-response.
- FR-44 [M4]: Once any partial tool call has been streamed, never switch provider.
- FR-45 [M4]: Client disconnect cancels the provider call promptly and settles the tokens used.
- FR-46 [M4]: Provider hang is bounded by TTFT, idle-stream and overall deadlines; each expiry yields a typed timeout error.
- FR-47 [M1]: Malformed provider chunk → adapter validation failure → normalized error event (see FR-19).

### Resilience
- FR-48 [M4]: Layered timeouts `connect_ms`, `first_token_ms`, `idle_stream_ms`, `deadline_ms` (overall, across all attempts), configurable per route with the §6 defaults (2000 / 15000 / 10000 / 60000).
- FR-49 [M4]: `max_attempts` (default 3) and `max_fallbacks` (default 2) are enforced per request.
- FR-50 [M4]: Backoff uses exponential backoff with full jitter between `initial_backoff_ms` (200) and `max_backoff_ms` (2000); no retry is scheduled if it would exceed `deadline_ms`.
- FR-51 [M4]: 429 responses are retried honouring `Retry-After`; if `Retry-After` exceeds the remaining deadline, fail over or fail fast instead of waiting.
- FR-52 [M4]: 500/502/503/504/529 are retried with backoff only if deadline and retry budget allow.
- FR-53 [M4]: 400 invalid request is never retried.
- FR-54 [M4]: 401/403 from a provider are never retried and raise an alert signal.
- FR-55 [M4]: Context overflow is never retried; no automatic truncation in v1.
- FR-56 [M4]: Client cancellation is never retried.
- FR-57 [M4]: Retry budget: when retries exceed `max_retry_ratio` (0.2) of traffic over the rolling window, stop retrying and fail fast; exhaustion emits a metric/alert.
- FR-58 [M4]: Circuit breaker per provider/model, shared across replicas via Redis, with `failure_threshold` (5), `rolling_window_s` (30), `open_duration_s` (15), `half_open_probes` (2); states closed → open → half-open → closed/open.
- FR-59 [M4]: Open breakers remove the model from candidate chains (FR-28).
- FR-60 [M4]: Correlated outage of all candidates returns a typed 503 within `deadline_ms`.
- FR-61 [M4]: Retries and `max_attempts` are included in the budget reservation estimate (§8).
- FR-62 [M1]: Normalized error taxonomy covers at least: rate_limited, provider_unavailable (5xx/529), invalid_request, auth_failed, context_overflow, timeout (connect/ttft/idle/deadline), cancelled, malformed_response, capability_mismatch, budget_exceeded, idempotency_conflict, no_healthy_candidate; each class has a fixed retryable flag and HTTP status.

### Tenancy and security
- FR-63 [M5]: API keys stored only as HMAC-SHA-256 hashes; only a non-secret prefix is displayable.
- FR-64 [M5]: API keys support rotation, expiry and revocation; expired/revoked keys get 401.
- FR-65 [M5]: Auth middleware resolves the key to a tenant context attached to the request; unauthenticated requests get 401 before any service runs.
- FR-66 [M5]: Key lifecycle events (create, rotate, revoke, expire, failed auth) emit audit events persisted in Postgres.
- FR-67 [M5]: `tenant_id` is part of every DB query and every cache key; composite DB constraints include `tenant_id`.
- FR-68 [M5]: Per-tenant RPM, TPM and concurrency limits enforced via Redis token bucket implemented as atomic Lua; exceeding a limit returns 429 with `Retry-After`.
- FR-69 [M5]: Configurable limits on body size, message count, `max_tokens`, and tool payload size; violations return 400/413.
- FR-70 [M5]: Provider secrets loaded from AWS Secrets Manager; never stored in YAML or `.env` (local dev uses fake_provider or env injection outside the repo).
- FR-71 [M5]: Prompts and tool arguments are redacted from logs by default; per-tenant opt-in enables unredacted logging.
- FR-72 [M5]: `docs/security.md` documents retention/deletion policy and a STRIDE threat model.
- FR-73 [M5]: Negative tests prove tenant A cannot read tenant B's cache entries, keys, ledger, idempotency records or policy.

### Cost governance
- FR-74 [M6]: Postgres is the single source of truth for money; no Redis/Postgres dual write for budgets.
- FR-75 [M6]: Budget reservation uses a single atomic conditional `UPDATE ... WHERE spent + reserved + amt <= limit RETURNING`; 0 rows → budget exceeded.
- FR-76 [M6]: Reservation amount = `input_tokens_est × in_price + max_tokens × out_price`, accounting for `max_attempts` (FR-61).
- FR-77 [M6]: Reservation lifecycle `reserved → committed | released | expired`; no other transitions.
- FR-78 [M6]: Settlement is idempotent keyed by `request_id`: actual cost added to `spent`, remainder released, one ledger row appended; repeated settlement is a no-op.
- FR-79 [M6]: When provider usage is not reported, settle with estimated usage and `usage_source=estimated`.
- FR-80 [M6]: Hard budget rejects before execution (402); soft budget allows and raises an alert.
- FR-81 [M6]: Ledger rows record tenant, request_id, attempt_ids, provider/model, usage, cost, `pricing_version`, `policy_version`, `usage_source`.
- FR-82 [M6]: Reservation-expiry worker expires orphaned reservations past TTL, releases them and flags them (metric + ledger marker).

### Idempotency
- FR-83 [M6]: Optional `Idempotency-Key` header; records stored as `idempotency_keys(tenant_id, key, request_hash, status, response_ref, expires_at)`, scoped by tenant.
- FR-84 [M6]: Same key + same body → replay the stored result without a new provider call or new charge.
- FR-85 [M6]: Same key + different body → 422.
- FR-86 [M6]: Same key while the original is in progress → 409.
- FR-87 [M6]: Idempotency-cleanup worker deletes records past `expires_at`.

### Exact cache
- FR-88 [M7]: Cache key = hash of `tenant_id, route_id, policy_version, model, normalized_messages, tools, tool_choice, temperature, top_p, max_tokens, response_format, stop`.
- FR-89 [M7]: A response is cached/served only if route `cache.exact: true`, `temperature == 0`, the response has no tool calls, and the request is non-streaming (or the full stream was buffered).
- FR-90 [M7]: Every response carries `x-switchyard-cache: hit | miss | bypass`.
- FR-91 [M7]: Cache hits transition `ADMITTED → CACHE_HIT → COMPLETED → SETTLED` and make no provider call.
- FR-92 [M7]: Exact cache is stored in Redis; Redis loss degrades to cache miss, never to error.

### Policy and config
- FR-93 [M3]: Policies (routes, strategies, execution settings) are versioned in Postgres and loaded from YAML via `switchyard policy apply`.
- FR-94 [M3]: Validation before activation: schema valid, all referenced models exist in the registry, chains are capability-compatible; invalid policy is rejected without changing the active version.
- FR-95 [M3]: On config load failure the gateway keeps serving with the last-known-good policy version.
- FR-96 [M3]: Every request records its `policy_version` in traces and ledger.

### Observability
- FR-97 [M8]: OpenTelemetry trace per request with a child span per provider attempt carrying `request_id`, `attempt_id`, tenant, route, provider/model, policy_version, usage, cost, cache status, error class, retry/fallback reason.
- FR-98 [M8]: Metrics for request rate, latency (overhead, TTFT), error rate by class, retries, retry budget, breaker state, cache hit rate, spend, expired reservations.
- FR-99 [M8]: Grafana dashboards provisioned from `dashboards/`.
- FR-100 [M8]: Alerts: breaker open > 5 min, retry budget exhausted, spend velocity spike, expired reservations > 0, error rate by class, provider 401/403.
- FR-101 [M8]: "Why did request X cost $Y and take Z s?" is answerable from a single trace (acceptance demo).

### Deployment and operations
- FR-102 [M0]: Repo bootstrapped with uv, pyproject, ruff, mypy strict, CI, `src/switchyard/{api,domain,application,adapters,infrastructure,security,workers}` skeleton.
- FR-103 [M0]: `docker-compose.yml` runs Postgres, Redis, OTel collector and the gateway locally.
- FR-104 [M0]: `fake_provider` simulates configurable latency, error rate, 529/503, hangs and stream drops, and speaks the OpenAI-compatible wire format used by tests.
- FR-105 [M9]: Terraform provisions ECS Fargate, RDS Postgres, ElastiCache Redis and Secrets Manager from zero.
- FR-106 [M9]: CD pipeline with staging deploy, rollback to previous ECS task definition + last-known-good policy, and nightly live smoke test.
- FR-107 [M9]: On SIGTERM the gateway stops accepting new requests and drains in-flight SSE streams before exit.
- FR-108 [M10]: Runbooks for provider outage, Redis loss, budget drift, key compromise, bad policy rollout; `docs/failure-modes.md`; README with demo.
- FR-109 [M0–M7]: ADRs 001–010 written in `docs/adr/` at the milestone that introduces each decision (001/002 M0, 003 M1, 007 M2, 010 M3, 004/005 M4, 008 M5, 006 M6, 009 M7).
- FR-110 [M3]: Alembic migrations manage all Postgres schema.

## Non-Functional Requirements
- NFR-01 [M10]: Performance — non-streaming gateway overhead p95 < 15 ms (k6, 200 VUs, fake provider at 300 ms).
- NFR-02 [M10]: Performance — streaming gateway-added TTFT p95 < 10 ms.
- NFR-03 [M4/M10]: Resilience — ≥ 99.5% success with 50% retryable errors injected on the primary.
- NFR-04 [M4/M10]: Resilience — correlated outage of all providers returns typed 503 within `deadline_ms`.
- NFR-05 [M6/M10]: Cost — 0 overspend with 200 concurrent requests against a $1 limit.
- NFR-06 [M6/M10]: Crash safety — after a process crash mid-request, 100% of reservations end settled or expired.
- NFR-07 [M6/M10]: Idempotency — 0 double bills over 1,000 duplicate-key retries.
- NFR-08 [M5/M10]: Security — 0 cross-tenant leaks in the isolation suite.
- NFR-09 [M5/M10]: Rate limiting — enforced limit within ±5% of configured value across 3 replicas.
- NFR-10 [M3/M10]: Fallback correctness — 100% of fallbacks capability-compatible.
- NFR-11 [M7/M10]: Cache correctness — 0 wrong hits; hit-rate benchmark published.
- NFR-12 [M9/M10]: Graceful shutdown — 0 truncated streams during deploy.
- NFR-13 [M10]: Availability — SLO 99.9% for gateway-caused errors.
- NFR-14 [M5]: Security — no secrets, raw API keys or (by default) prompt content in logs, repo, YAML or `.env`; bandit + pip-audit clean.
- NFR-15 [M3/M5]: Data durability — Redis loss resets only limits, breakers and cache; no money or tenant data lost (documented in `failure-modes.md`, verified by a chaos test).
- NFR-16 [M8]: Observability — 100% of requests and attempts traced; trace IDs correlate with ledger rows.
- NFR-17 [all]: Quality — ruff 0 violations, mypy strict 0 errors, 100% annotation coverage, avg cyclomatic complexity ≤ 5, line coverage ≥ 80%, branch coverage ≥ 75%.
- NFR-18 [M1]: Determinism — routing ranks, cache keys and cost computation are deterministic for equal inputs (ties broken by stable sort on model ID); time and randomness are injectable for tests.

## Constraints
- Stack: Python 3.12, uv, FastAPI, pydantic v2, httpx, SQLAlchemy 2 async + asyncpg, Alembic, redis-py (asyncio), hypothesis, OpenTelemetry; Terraform on AWS (ECS Fargate, RDS, ElastiCache, Secrets Manager); k6; toxiproxy.
- Provider order: OpenAI (M1) → Anthropic → Gemini (M2).
- Architecture: four layers (data access → service → orchestration → API); domain is pure; repository layout per §12.
- Test layout: `tests/{unit,contract,integration,chaos,security}/`; CLAUDE.md and CI updated to match. Tests use `unittest.TestCase` run by pytest; hypothesis for property/state-machine tests.
- Existing unrelated code `src/ai/`, `src/app/` and their tests under `test/` are deleted in `chore/repo-bootstrap`.
- Git: local branches per the confirmed 33-branch breakdown, squash-merged into `main` at each milestone gate; no push/PR unless the user asks.
- Pipeline stops at each milestone exit gate for user confirmation.
- `terraform apply` and live provider calls are manual (user's AWS account / API keys); automated tests use `fake_provider` and recorded fixtures only.
- Registry and policy changes go through version control (PRs/commits); no runtime edits outside `switchyard policy apply`.

## Out of Scope
- Supporting 100+ providers; custom provider base URLs.
- Embeddings, image and audio endpoints.
- UI-heavy admin console (CLI + Grafana only).
- Self-hosted model serving.
- Automatic prompt truncation on context overflow.
- v2 backlog: semantic caching, hedged requests, `quality_first` routing, admin API/dashboard, prompt registry, guardrails, embeddings.

## Success Criteria
- Every milestone exit gate in §14 met and confirmed by the user.
- Every §15 acceptance target (NFR-01 – NFR-12) met in the M10 load/chaos/security runs.
- Every §4 invariant has a passing dedicated test.
- An unmodified OpenAI SDK streams a tool-call conversation through Switchyard against all 3 providers (fixtures) and OpenAI live (manual smoke).
- Project quality targets (NFR-17) met.

## Open Questions
- OQ-01: Concrete provider model IDs for `models.yaml`. Proposed default: `openai/gpt-4o` → `gpt-4o`, `openai/gpt-4o-mini` → `gpt-4o-mini`; `anthropic/claude-sonnet` → latest Claude Sonnet ID, `anthropic/claude-haiku` → latest Claude Haiku ID; `google/gemini-pro` → `gemini-2.5-pro`, `google/gemini-flash` → `gemini-2.5-flash`. Pricing values copied from provider price pages on the pin date and stamped with `pricing_version`. User to confirm exact IDs at M2.
- OQ-02: Budget period granularity. Proposed default: calendar month (UTC) per tenant, with optional daily period.
- OQ-03: Reservation TTL and idempotency-key retention. Proposed default: reservation TTL = `deadline_ms` + 5 min; idempotency `expires_at` = 24 h.
- OQ-04: Budget "downgrade" path (§7 "reject (402) or downgrade"). Proposed default: v1 implements reject (402) only; downgrade deferred unless a route explicitly lists a cheaper fallback chain.
- OQ-05: Default request limits (FR-69). Proposed default: body 1 MiB, 256 messages, `max_tokens` capped at model `max_output_tokens`, tool payload 64 KiB.
- OQ-06: Exact cache TTL and `lowest_latency` EWMA smoothing. Proposed default: cache TTL 1 h per route (configurable); EWMA alpha 0.2.
- OQ-07: Soft-budget alert threshold and spend-velocity spike definition. Proposed default: alert at 80% of soft limit; spike = 1 h spend > 3× trailing 24 h hourly average.
- OQ-08: AWS region for Terraform. Proposed default: `us-east-1`, parameterized.

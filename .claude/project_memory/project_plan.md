# Switchyard — LLM Gateway / Router · Project Plan v2 (user-supplied source of truth)

> Saved verbatim from the user's plan on 2026-11-04, followed by the user-confirmed defaults and the
> confirmed feature-branch breakdown. Architect / System Designer / Planner derive their outputs from this file.

> **Principle:** Switchyard is an **execution and governance platform for LLM calls**, not just a proxy that forwards requests.
> **Goal:** a production-grade, opinionated gateway that shows senior/architect skills: correctness, reliability, cost control, security and observability.
> **v2 changes:** merges the architecture review. Correctness and depth come before features; the order is single provider first; semantic caching and hedging move to v2; budgets live in Postgres only.

---

## 1. Problem statement

| Problem | Example |
|---|---|
| Provider outages | Claude returns `529 overloaded`, and the feature goes down |
| Cost surprises | One tenant's agent loop spends $300 overnight |
| Vendor lock-in | Provider-specific SDK code in every service |
| No visibility | "Why did this request cost $3 and take 40 s?" has no answer |
| Double billing | A client retries after a network blip and both calls are billed |
| Repeated work | The same deterministic prompt is paid for thousands of times a day |

---

## 2. Scope

### v1 goals
- OpenAI-compatible API (`/v1/chat/completions`, `/v1/models`), so clients change only `base_url`
- 3 providers: **OpenAI → Anthropic → Gemini** (added in that order)
- Streaming (SSE) and tool calling, normalized across providers
- **Capability registry** plus capability-aware routing and fallback
- Resilience: layered timeouts, classified retries, a retry budget, circuit breakers and fallback
- **Request lifecycle state machine** with idempotent settlement
- Multi-tenancy and security: hashed API keys, isolation, RPM/TPM/concurrency limits and audit events
- Cost governance: atomic budget reservation in Postgres and a durable ledger
- **Client idempotency keys** (no double billing on client retries)
- Exact caching, with strict eligibility rules
- Observability: OpenTelemetry traces, metrics, a cost ledger and alerts
- Terraform, CI/CD, load, chaos and security tests

### Non-goals (v1)
- Supporting 100+ providers (that is LiteLLM's job)
- Embeddings, image or audio endpoints
- A UI-heavy admin console (a CLI and Grafana are enough)
- Self-hosted model serving
- **Semantic caching and hedged requests** (deferred to v2, see §20)

---

## 3. Architecture

```
Client (OpenAI SDK)
   │ POST /v1/chat/completions   (Idempotency-Key optional)
   ▼
┌────────────────────────────── API layer (FastAPI) ──────────────────────────────┐
│ Middleware: request ID · auth → tenant context · body/size limits              │
└────────────────────────────────────┬────────────────────────────────────────────┘
                                     ▼
┌──────────────────────────── GatewayService (application) ───────────────────────┐
│ 1. Policy resolver      tenant + route + active config version                 │
│ 2. Idempotency check    replay stored result for a seen key                    │
│ 3. Admission control    RPM/TPM/concurrency (Redis) + budget reserve (PG)      │
│ 4. Cache lookup         exact, eligible requests only                          │
│ 5. Capability matcher   filter models: tools, streaming, context, JSON schema  │
│ 6. Candidate ranker     strategy → ordered chain                               │
│ 7. Execution orchestr.  lifecycle state machine: timeouts, retry, breaker,     │
│                         fallback, cancellation                                 │
│ 8. Response normalizer  provider output → canonical response / stream events   │
│ 9. Settlement           idempotent commit to ledger; release reservation       │
└──────────┬───────────────────────────┬──────────────────────────┬───────────────┘
           ▼                           ▼                          ▼
   Provider adapters             Redis (coordination)       Postgres (truth)
   OpenAI · Anthropic · Gemini   rate limits, breaker,      tenants, keys, policies,
                                 exact cache                budgets, ledger, idempotency
                                                                   │
                                     OTel Collector → Tempo / Prometheus → Grafana
```

**Business logic placement:** request ID, auth and size limits are middleware. Admission, caching, routing, execution and settlement live in **explicit application services**, not a long generic middleware chain.

---

## 4. Request lifecycle (state machine)

```
RECEIVED → ADMITTED → [CACHE_HIT → COMPLETED]
                    → ROUTED → ATTEMPTING ⇄ (RETRY_WAIT | FALLBACK)
                                  → STREAMING → COMPLETED
                                  → FAILED | CANCELLED | REJECTED
                    → SETTLED (always exactly once, for every terminal state)
```

**Invariants (each has a test):**
1. Every logical request has a `request_id`, and every provider attempt has a unique `attempt_id`.
2. Every request reaches **exactly one** terminal state and **exactly one** idempotent settlement.
3. Retry or fallback is allowed only from `ATTEMPTING`, before the first token.
4. Cancellation propagates client → gateway → adapter → provider.
5. Usage from **every billable attempt** is accounted for, including failed attempts that consumed tokens.

### Streaming semantics

| Situation | Behaviour |
|---|---|
| Fails before the first token | Retry or fall back, if the error is eligible |
| Fails after the first token | End the stream with a typed error event; never switch mid-response |
| Partial tool call streamed | Never switch providers |
| Client disconnects | Cancel the provider call promptly; settle the tokens used |
| Provider hangs | TTFT, idle-stream and overall deadlines apply |
| Malformed chunk | Adapter validation fails, and a normalized error is emitted |

### Timeouts (layered)
`connect_ms` · `first_token_ms` (TTFT) · `idle_stream_ms` · `deadline_ms` (overall, across all attempts)

---

## 5. Canonical schema and capability registry

### Canonical request
`model`, `messages`, `tools`, `tool_choice`, `temperature`, `top_p`, `max_tokens`, `stop`, `response_format` / JSON schema, parallel tool calls, tool-call IDs, and provider extensions in a namespaced field.
**Rule:** unsupported fields are **rejected with a 400** or explicitly mapped. Never silently dropped.

### Canonical response
Finish reason, a normalized error taxonomy, tool calls with IDs, usage (input, output, cached and reasoning tokens), provider request ID, the resolved provider/model, `usage_source: reported | estimated`, and stream events with sequence numbers and a terminal event.

### Capability registry
```yaml
models:
  anthropic/claude-sonnet:
    provider: anthropic
    capabilities: { streaming: true, tools: true, parallel_tools: true, structured_output: true }
    context_window: 200000
    max_output_tokens: 64000
    pricing: { input_per_mtok: 3.00, output_per_mtok: 15.00, cached_input_per_mtok: 0.30 }
    pricing_version: 2026-11-01
    status: active        # active | deprecated | disabled
```
- Registry is versioned; changes go through PRs.
- **CI test:** fail if any routable model has no pricing or capability entry.

---

## 6. Routing

Pipeline: **filter by capability → filter by health (breaker) → rank by strategy.**

| Strategy | Definition |
|---|---|
| `fallback` | Fixed ordered chain; advance only on eligible failures |
| `cheapest_capable` | Lowest estimated cost among models that meet all request capabilities |
| `lowest_latency` | Lowest EWMA latency among healthy eligible models |
| `weighted` | Weighted split for experiments or canaries |

**Rule:** fallbacks must satisfy the original request's capabilities.

```yaml
routes:
  support-bot:
    strategy: fallback
    chain: [openai/gpt-4o, anthropic/claude-sonnet, google/gemini-pro]
    cache: { exact: true }

execution:
  deadline_ms: 60000
  max_attempts: 3
  max_fallbacks: 2
  retry:   { initial_backoff_ms: 200, max_backoff_ms: 2000, jitter: full }
  timeouts: { connect_ms: 2000, first_token_ms: 15000, idle_stream_ms: 10000 }
  circuit_breaker: { failure_threshold: 5, rolling_window_s: 30, open_duration_s: 15, half_open_probes: 2 }
  retry_budget: { max_retry_ratio: 0.2 }
```

### Error taxonomy and retry classification

| Error | Policy |
|---|---|
| 429 rate limit | Retry, honouring `Retry-After` |
| 500 / 502 / 503 / 504 / 529 | Retry with backoff if the deadline and retry budget allow |
| 400 invalid request | Never retry |
| 401 / 403 | Never retry; alert |
| Context overflow | Never retry (no automatic truncation in v1) |
| Client cancellation | Never retry |

**Retry budget:** when retries exceed 20% of traffic over a window, stop retrying and fail fast.

---

## 7. Cost governance

**Postgres is the single source of truth.** No Redis/Postgres dual write for money.

```sql
UPDATE budgets
SET reserved_usd = reserved_usd + :amt
WHERE tenant_id = :t AND period = :p
  AND spent_usd + reserved_usd + :amt <= limit_usd
RETURNING id;
-- 0 rows → budget exceeded → reject (402) or downgrade
```

Reservation lifecycle `reserved → committed | released | expired`.
- Reservation = `input_tokens_est × in_price + max_tokens × out_price`
- Settlement idempotent, keyed by `request_id`: actual cost → `spent`, release remainder, append ledger row.
- No reported usage → settle with estimate, `usage_source=estimated`.
- Reservation TTL: cleanup worker expires orphaned reservations and flags them.
- Hard budget = reject before execution. Soft budget = allow, then alert.

Client idempotency: `Idempotency-Key` → `idempotency_keys(tenant_id, key, request_hash, status, response_ref, expires_at)`.
Same key+body → replay; same key, different body → 422; in progress → 409.

---

## 8. Security and multi-tenancy
- API keys stored as HMAC-SHA-256 hashes, prefix display, rotation, expiry, revocation, audit events
- Tenant ID in every query and every cache key; composite DB constraints
- Per-tenant RPM, TPM, concurrency limits (Redis token bucket, atomic Lua)
- Limits on body size, message count, `max_tokens`, tool payload size
- Retry budget and `max_attempts` count toward the reservation
- Provider secrets in AWS Secrets Manager, never YAML or `.env`
- No custom provider base URLs in v1 (no SSRF surface)
- Prompts/tool args redacted from logs by default; per-tenant opt-in
- Retention/deletion policy + STRIDE threat model in `docs/security.md`
- **Acceptance gate:** negative tests prove tenant A cannot read tenant B's cache, keys, ledger, idempotency records or policy.

## 9. Exact caching (v1)
Key = hash(`tenant_id, route_id, policy_version, model, normalized_messages, tools, tool_choice, temperature, top_p, max_tokens, response_format, stop`).
Eligible only if: route `cache.exact: true` · `temperature == 0` · no tool calls in response · not streaming (or full stream buffered).
Header `x-switchyard-cache: hit | miss | bypass`.

## 10. Policy and config safety
- Versioned policies in Postgres, loaded from YAML via `switchyard policy apply`
- Validation before activation: schema, models exist in registry, chains capability-compatible
- Last-known-good config on load failure
- Every request records its `policy_version` (traces + ledger)

## 11. Data boundaries
| Data | Store |
|---|---|
| Rate-limit counters, breaker state, exact cache | Redis |
| Tenants, key hashes, policies, budgets, reservations, ledger, idempotency | Postgres |
Redis loss resets limits/breakers/cache; no money or tenant data lost (`failure-modes.md`).

## 12. Repository structure
```
src/switchyard/{api,domain,application,adapters,infrastructure,security,workers}
domain/: schema.py errors.py capabilities.py lifecycle.py routing.py pricing.py  (pure, no I/O)
application/: gateway_service.py execution_service.py budget_service.py idempotency_service.py cache_service.py
adapters/: base.py openai.py anthropic.py gemini.py
workers/: reservation_expiry.py idempotency_cleanup.py
config/ (models.yaml, policies/*.yaml) · tests/{unit,contract,integration,chaos,security}/
fake_provider/ · loadtest/ · infra/ · dashboards/ · docs/{adr/,architecture.md,failure-modes.md,security.md,runbooks/}
examples/ · docker-compose.yml
```

## 13. ADRs
001 OpenAI-compatible API + canonical schema · 002 ECS Fargate · 003 Lifecycle state machine + idempotent settlement ·
004 Error taxonomy, retry classification + retry budget · 005 Streaming semantics, timeouts + cancellation ·
006 Postgres-only budget reservation · 007 Capability registry + capability-aware fallback · 008 Tenant isolation + API keys ·
009 Exact cache eligibility; semantic deferred · 010 Policy versioning + last-known-good

## 14. Milestones
| Phase | Deliverable | Exit gate |
|---|---|---|
| ⭐ M0 Foundations | Repo, uv, ruff, mypy strict, CI, compose, fake_provider, ADR-001/002 | CI green; `/healthz` up |
| ⭐ M1 Single-provider | OpenAI-compatible API + OpenAI adapter, streaming, tools, lifecycle | OpenAI SDK streams a tool-call conversation; lifecycle invariant tests pass |
| ⭐ M2 Provider abstraction | Anthropic + Gemini adapters, registry, contract fixtures | Same suite passes on all 3 providers |
| ⭐ M3 Routing | Matcher, strategies, policy validation + versioning | 100% of fallbacks capability-compatible |
| ⭐ M4 Resilience | Timeouts, retry classification, retry budget, breaker, fallback, cancellation | Chaos suite passes |
| M5 Security + tenancy | Hashed keys, isolation, limits, audit, redaction, threat model | Cross-tenant negative tests pass |
| ⭐ M6 Cost governance | Reservation, settlement, ledger, idempotency keys, expiry worker | Zero overspend under 200 concurrent; crash test settles |
| M7 Exact caching | Key, eligibility, headers | Zero wrong hits; hit-rate benchmark |
| M8 Observability | OTel spans per attempt, metrics, dashboards, alerts | "Why did X cost $Y?" from one trace |
| M9 Deployment | Terraform, CD, staging, rollback, graceful SSE drain | apply from zero; no stream truncation on deploy |
| M10 Hardening + demo | Load/chaos/security runs, SLOs, runbooks, README | Every §15 target met |

## 15. Acceptance criteria
| Metric | Target |
|---|---|
| Gateway overhead non-streaming | p95 < 15 ms (k6, 200 VUs, fake provider 300 ms) |
| Streaming overhead | gateway-added TTFT p95 < 10 ms |
| Resilience | ≥ 99.5% success with 50% retryable errors on primary |
| Correlated outage | typed 503 within `deadline_ms` |
| Budget | 0 overspend, 200 concurrent vs $1 limit |
| Crash safety | 100% reservations settled/expired |
| Idempotency | 0 double bills over 1,000 duplicate-key retries |
| Tenant isolation | 0 leaks |
| Rate limiting | within ±5%, 3 replicas |
| Fallback correctness | 100% capability-compatible |
| Cache correctness | 0 wrong hits |
| Graceful shutdown | 0 truncated streams |

## 16. Testing strategy
Unit (pytest, hypothesis) · Contract (recorded fixtures) · Integration (compose/testcontainers) · Chaos (fake_provider, toxiproxy) · Security · Load (k6) · Live smoke (nightly cron).

## 17. Operations
SLO 99.9% (gateway-caused), overhead p95 < 15 ms. Alerts: breaker open > 5 min, retry budget exhausted, spend velocity spike, expired reservations > 0, error rate by class. Runbooks: provider outage, Redis loss, budget drift, key compromise, bad policy rollout. Rollback: previous ECS task def + last-known-good policy.

## 19. Risks
Provider API changes → contract tests, pinned SDKs, nightly smoke · Scope creep → non-goals, exit gates · Real API costs → fake_provider · Retry storms → retry budget, deadline, breaker · Budget drift → PG single source of truth · Tenant leakage → tenant-scoped keys/queries, security tests.

## 20. v2 backlog (out of scope)
Semantic caching, hedged requests, `quality_first` routing, admin API/dashboard, prompt registry, guardrails, embeddings.

---

## User-confirmed defaults (2026-11-04)
1. Existing unrelated code `src/ai/`, `src/app/` and their tests under `test/` are deleted in `chore/repo-bootstrap`.
2. Test layout follows the plan: `tests/{unit,contract,integration,chaos,security}/`. CLAUDE.md and CI updated to match.
3. Stack: Python 3.12, uv, FastAPI, pydantic v2, httpx, SQLAlchemy 2 async + asyncpg, Alembic, redis-py (asyncio), hypothesis, OpenTelemetry.
4. Work happens on local branches merged (squash) into `main` at each milestone gate; no push/PR unless the user asks. `terraform apply` and live provider calls stay manual (user's AWS account / API keys).
5. Pipeline stops at each milestone exit gate for user confirmation.

## Confirmed feature-branch breakdown
| # | Milestone | Branch | Scope | Group / deps |
|---|---|---|---|---|
| 1 | M0 | chore/repo-bootstrap | uv, pyproject, ruff, mypy strict, src/switchyard skeleton, CI | A (first) |
| 2 | M0 | chore/compose-stack | docker-compose PG+Redis+OTel collector, `/healthz` | B (needs 1) |
| 3 | M0 | feat/fake-provider | mock LLM: latency, error rate, 529/503, hangs, stream drops | B (needs 1) |
| 4 | M0 | docs/adr-001-002 | ADR-001, ADR-002 | B (needs 1) |
| 5 | M1 | feat/canonical-schema | domain/schema.py, domain/errors.py | C |
| 6 | M1 | feat/lifecycle-state-machine | domain/lifecycle.py + hypothesis invariant tests, ADR-003 | C |
| 7 | M1 | feat/adapter-openai | adapters/base.py + openai.py (stream, tools, usage) | D (needs 5) |
| 8 | M1 | feat/api-surface | FastAPI, middleware, /v1/models, /v1/chat/completions, SSE | D (needs 5) |
| 9 | M1 | feat/gateway-service-v1 | gateway_service + single-attempt execution_service; OpenAI SDK e2e | E (needs 6–8) |
| 10 | M2 | feat/capability-registry | capabilities.py, pricing.py, config/models.yaml, CI pricing check, ADR-007 | F |
| 11 | M2 | feat/adapter-anthropic | adapter + recorded fixtures | F |
| 12 | M2 | feat/adapter-gemini | adapter + recorded fixtures | F |
| 13 | M2 | test/provider-contract-suite | shared contract suite on all 3 adapters | G |
| 14 | M3 | feat/persistence-foundation | SQLAlchemy async, Alembic, Redis client, tenant-scoped repo base | H |
| 15 | M3 | feat/routing-strategies | domain/routing.py filters + 4 strategies | H |
| 16 | M3 | feat/policy-versioning | PG policies, `switchyard policy apply`, validation, LKG, ADR-010 | I (needs 14,15) |
| 17 | M4 | feat/retry-and-timeouts | layered timeouts, retry classification, backoff, Retry-After, retry budget, ADR-004 | J |
| 18 | M4 | feat/circuit-breaker | Redis-shared breaker, half-open probes | J |
| 19 | M4 | feat/execution-orchestrator | fallback, cancellation, pre/post-first-token rules, ADR-005 | K (needs 17,18) |
| 20 | M4 | test/chaos-suite | fake_provider + toxiproxy scenarios | L |
| 21 | M5 | feat/tenant-auth | HMAC keys, rotation/expiry/revocation, tenant context, audit, ADR-008 | M |
| 22 | M5 | feat/rate-limits | Redis Lua token bucket RPM/TPM/concurrency | M |
| 23 | M5 | feat/log-redaction | redaction, opt-in, docs/security.md STRIDE | M |
| 24 | M5 | test/tenant-isolation | negative suite | N |
| 25 | M6 | feat/budget-ledger | atomic reservation, idempotent settlement, ledger, hard/soft, ADR-006 | O |
| 26 | M6 | feat/idempotency-keys | replay / 422 / 409 | O |
| 27 | M6 | feat/maintenance-workers | reservation expiry + idempotency cleanup, crash test | P |
| 28 | M7 | feat/exact-cache | key, eligibility, header, safety tests, ADR-009 | — |
| 29 | M8 | feat/observability | OTel spans per attempt, metrics, dashboards, alerts | — |
| 30 | M9 | feat/graceful-shutdown | SSE drain on SIGTERM | — |
| 31 | M9 | chore/terraform-infra | ECS Fargate, RDS, ElastiCache, Secrets Manager | — |
| 32 | M9 | chore/cd-pipeline | CD, staging, rollback, nightly live smoke | — |
| 33 | M10 | chore/loadtest-and-docs | k6, benchmarks, runbooks, failure-modes.md, README | — |

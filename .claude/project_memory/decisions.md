# Architecture Decisions Log

Append decisions here. Do not edit existing entries — only add new ones.

Format:
```
## [DATE] — [Decision Title]
**Decision**: What was decided
**Context**: Why this decision was needed
**Rationale**: Why this choice over alternatives
**Consequences**: What this enables and what it constrains
```

---

<!-- Decisions appended below -->

## 2026-11-04 — ADR-000 Layering: pure domain core plus four CLAUDE.md layers
**Decision**: `switchyard.domain` is a pure core (no I/O) importable by every layer. On top sit the four CLAUDE.md layers: data access (`infrastructure`, `adapters`), service logic (`application.*_service`, `security`), orchestration (`GatewayService`, `ExecutionService`, `workers`), API surface (`api`, `cli`). Imports flow downward only.
**Context**: The gateway mixes money, retries, streaming and tenancy. Without strict boundaries, I/O leaks into business rules and the rules become hard to test.
**Rationale**:
- Pure domain types (`CanonicalRequest`, `RequestLifecycle`, `CostEstimator`) can be property-tested with hypothesis and no fixtures.
- Rejected a flat package: no enforced boundaries, and routes would end up calling repositories directly.
- Rejected hexagonal ports for every dependency: an interface per repository and client adds ceremony with no second implementation to justify it. Only `ProviderAdapter` is a Protocol, because three real implementations exist.
**Consequences**: An import-direction check (e.g. import-linter) runs in CI. The domain cannot log, read config or call time directly; clocks and IDs are injected. Some extra mapping code is needed between ORM rows and domain models.

## 2026-11-04 — ADR-001 OpenAI-compatible API and canonical schema
**Decision**: Expose `/v1/chat/completions` and `/v1/models` in the OpenAI wire format. Internally, every request and response is translated to `CanonicalRequest` / `CanonicalResponse` / `StreamEvent` in `domain/schema.py`. Unsupported fields return 400 (`InvalidRequestError`) or are mapped explicitly, never silently dropped.
**Context**: Clients should switch to the gateway by changing only `base_url`. Three providers have different message, tool and usage shapes.
**Rationale**:
- The OpenAI format is the de facto standard; existing SDKs and tools work unchanged.
- Rejected a native custom API: every client would need a new SDK, which defeats the lock-in goal.
- Rejected passing provider payloads through: routing, fallback, caching and cost accounting need one shape; pass-through makes cross-provider fallback impossible and leaks provider types upward.
- Provider-specific options go in a namespaced extensions field, so they are explicit and validated.
**Consequences**: Each adapter owns two-way translation and is covered by contract fixtures. The canonical schema becomes a versioned contract; adding a field touches all three adapters. OpenAI-only features not in the schema are rejected until modelled.

## 2026-11-04 — ADR-002 Deploy on ECS Fargate
**Decision**: Run the gateway as a long-lived container service on AWS ECS Fargate behind an ALB, with RDS Postgres, ElastiCache Redis and Secrets Manager, all provisioned by Terraform.
**Context**: The gateway serves long SSE streams (up to `deadline_ms`, 60 s by default) and must drain them cleanly on deploy.
**Rationale**:
- Fargate supports long-lived HTTP connections, graceful SIGTERM drain and steady connection pools to Postgres/Redis, with no node management.
- Rejected Lambda: response-streaming limits, the 15-minute duration cap, cold starts that break the p95 < 15 ms overhead target, and per-invocation DB connections.
- Rejected EKS: control-plane cost and Kubernetes operations work are not justified for a single service.
**Consequences**: Rollback is "previous task definition". Autoscaling is by CPU/connection count. Graceful shutdown (`feat/graceful-shutdown`) must keep the ALB deregistration delay longer than the max stream deadline. The setup is AWS-specific; portability is not a v1 goal.

## 2026-11-04 — ADR-003 Request lifecycle state machine and idempotent settlement
**Decision**: Every logical request is driven by `RequestLifecycle` (`domain/lifecycle.py`) over `RequestState`. Transitions not in the allowed table raise `IllegalTransitionError`. Each provider attempt is an `AttemptRecord` with a unique `attempt_id`. `settle()` is idempotent and runs exactly once for every terminal state (COMPLETED, FAILED, CANCELLED, REJECTED).
**Context**: Retries, fallback, streaming and client disconnects create many exit paths. Each path can leak a budget reservation or bill twice.
**Rationale**:
- An explicit state machine makes the five invariants testable with hypothesis (random event sequences must end in exactly one terminal state and one settlement).
- Rejected ad-hoc flags and try/finally blocks in the orchestrator: these are easy to bypass on new code paths and cannot be checked by property tests.
- Settlement is keyed by `request_id` at the DB level, so a double call after a crash or retry is a no-op.
**Consequences**: `ExecutionService` must go through `transition()` for every step. Usage from every billable attempt, including failed ones, is summed at settlement. The lifecycle object is per-request, in memory; crash recovery depends on `ReservationExpiryWorker` (ADR-006).

## 2026-11-04 — ADR-004 Error taxonomy, retry classification and retry budget
**Decision**: All provider and gateway failures map to `GatewayError` subclasses with an `ErrorClass`. A pure `classify(error) -> RetryDecision` (RETRY, RETRY_AFTER, FAIL) decides retry. A shared `RetryBudget` stops retries when they exceed `max_retry_ratio` (0.2) of traffic in a rolling window.
**Context**: Blind retries turn a provider brown-out into a retry storm and burn the deadline and the budget.
**Rationale**:
- 429 → RETRY_AFTER (honour `Retry-After`); 500/502/503/504/529 → RETRY with full-jitter backoff; 400, 401/403, context overflow and client cancel → FAIL.
- Classification lives in the domain, so it is one table with unit tests, not scattered status-code checks in adapters.
- Rejected per-adapter retry logic: inconsistent behaviour across providers. Rejected unbounded retries limited only by `max_attempts`: no protection against correlated outages.
**Consequences**: Adapters must raise typed errors and never retry themselves. 401/403 trigger an alert. When the budget is exhausted, requests fail fast with a typed error inside `deadline_ms`. Retry budget state lives in Redis and resets on Redis loss (acceptable).

## 2026-11-04 — ADR-005 Streaming semantics, layered timeouts and cancellation
**Decision**: Retry or fallback is allowed only before the first token (`first_token_seen` is false). After the first token, any failure ends the stream with a typed `StreamError` followed by the terminal event; the gateway never switches providers mid-response. Timeouts are layered: `connect_ms`, `first_token_ms`, `idle_stream_ms`, and `deadline_ms` across all attempts. Client disconnect sets `AttemptContext.cancel_event`, which cancels the provider call.
**Context**: Switching providers mid-stream would splice two different answers (or two partial tool calls) into one response that the client cannot detect.
**Rationale**:
- The first-token boundary is simple, observable and testable.
- Rejected mid-stream resume on another provider: outputs are not deterministic, and partial tool-call arguments cannot be merged safely.
- Rejected a single overall timeout: a hung provider would hold the slot until the full deadline; TTFT and idle timers fail fast so fallback still has time.
**Consequences**: The client sees typed partial-failure events and must handle them. Tokens used before cancellation or failure are still settled. Hedged requests stay deferred to v2. Malformed chunks raise `MalformedProviderResponseError` in the adapter.

## 2026-11-04 — ADR-006 Postgres-only budget reservation
**Decision**: `BudgetService` reserves money with one conditional `UPDATE budgets ... WHERE spent_usd + reserved_usd + :amt <= limit_usd RETURNING id` via `BudgetRepository`. Zero rows → `BudgetExceededError` (402) for hard budgets; soft budgets allow and alert. Reservation = `CostEstimator.estimate_reservation` (input estimate × input price + `max_tokens` × output price, times attempts allowed). Settlement commits actual cost to `spent_usd`, releases the remainder and appends a `LedgerRepository` row, keyed by `request_id`. Money is `Decimal`.
**Context**: Target is zero overspend with 200 concurrent requests against a $1 limit, and every reservation settled or expired after a crash.
**Rationale**:
- A single atomic row update gives correctness under concurrency without distributed locks.
- Rejected Redis counters plus periodic reconciliation to Postgres: dual writes for money drift, Redis loss loses money state, and reconciliation means overspend is found only after it happened.
- Postgres row contention is acceptable at the target load; one budget row per tenant-period.
**Consequences**: Each request costs two short PG writes (reserve, settle). `ReservationExpiryWorker` expires orphaned reservations past TTL and flags them for alerting. No reported usage → settle with estimate, `usage_source=ESTIMATED`. Hot tenants may need sharded budget rows later (v2).

## 2026-11-04 — ADR-007 Capability registry in versioned YAML plus capability-aware fallback
**Decision**: Model capabilities, limits, pricing and status live in `config/models.yaml`, loaded into `CapabilityRegistry` (`ModelSpec`, `ModelCapabilities`, `ModelPricing`, `ModelStatus`). Routing derives `RequiredCapabilities.from_request(req)` and `CapabilityMatcher` filters candidates before health and ranking. Every fallback must satisfy the original request's capabilities.
**Context**: Falling back from a tool-calling model to one without tools, or with a smaller context window, produces wrong answers rather than errors.
**Rationale**:
- YAML in git gives review via PR, diffs and a `pricing_version`; a CI test fails if any routable model lacks pricing or capabilities.
- Rejected a database table: changes would skip code review, and pricing needs to ship with the code that uses it.
- Rejected querying provider APIs at runtime: they do not expose capabilities consistently and add a startup dependency.
**Consequences**: Price changes need a PR and deploy. `NoEligibleModelError` is returned when no candidate qualifies. `PolicyValidator` reuses the matcher to reject incompatible chains at apply time (ADR-010).

## 2026-11-04 — ADR-008 Tenant isolation and HMAC-SHA-256 API keys
**Decision**: API keys are stored only as HMAC-SHA-256 hashes (`ApiKeyHasher`, server-side pepper in Secrets Manager) plus a display prefix, with rotation, expiry, revocation and audit events (`AuditRepository`). Auth resolves a `TenantContext` via `get_tenant_context`; every repository query, cache key and idempotency key includes `tenant_id`, backed by composite DB constraints.
**Context**: Keys are checked on every request with a p95 overhead target under 15 ms; a leak across tenants is a critical failure.
**Rationale**:
- Keys are high-entropy random tokens, so a fast keyed hash is sufficient; the pepper stops offline guessing from a DB dump. Lookup is O(1) by hash.
- Rejected bcrypt/argon2: tens of ms per request breaks the latency target, and slow hashing adds nothing for random keys.
- Rejected plaintext storage: a DB read would expose every key.
**Consequences**: Pepper rotation requires rehash or dual-pepper verification. Tenant-scoped repository base class enforces the `tenant_id` filter. A negative test suite proves tenant A cannot read B's cache, keys, ledger, idempotency records or policy.

## 2026-11-04 — ADR-009 Exact cache with strict eligibility; semantic cache deferred
**Decision**: `CacheService` stores exact responses in Redis keyed by a hash of `tenant_id, route_id, policy_version, model`, normalized messages, tools, `tool_choice`, `temperature`, `top_p`, `max_tokens`, `response_format`, `stop`. Eligible only when the route has `cache.exact: true`, `temperature == 0`, the response has no tool calls, and the request is non-streaming (or the full stream was buffered). Header `x-switchyard-cache: hit | miss | bypass`.
**Context**: Repeated deterministic prompts cost money, but a wrong cache hit is a correctness bug visible to users.
**Rationale**:
- Exact keys including tenant and policy version make wrong hits structurally impossible (target: 0 wrong hits).
- Rejected semantic caching for v1: similarity thresholds give false hits that are hard to detect, and it needs an embedding store; moved to the v2 backlog.
- Rejected caching tool-call responses: the result depends on external tool state.
**Consequences**: Hit rate is lower than a semantic cache. A policy change invalidates entries naturally through `policy_version`. Redis loss only empties the cache. Cache hits still settle (zero cost) through the lifecycle (CACHE_HIT → COMPLETED → SETTLED).

## 2026-11-04 — ADR-010 Policy versioning in Postgres plus last-known-good config
**Decision**: Route and execution policies (`PolicyDocument(version)`, `RoutePolicy`, `ExecutionPolicy`, etc.) are authored in YAML and applied with `switchyard policy apply`, which runs `PolicyValidator` (schema, models exist in registry, chains capability-compatible) and stores an immutable version in `PolicyRepository`. Activation is a pointer change. `PolicyService` keeps the last-known-good version in memory and uses it if a load fails. Every request records its `policy_version` in traces and the ledger.
**Context**: A bad policy rollout can route all traffic to a disabled model or break budgets across tenants at once.
**Rationale**:
- Validation before activation catches bad chains before traffic sees them; versions give audit and one-step rollback.
- Rejected YAML read directly at startup: no runtime activation or rollback without a deploy, and no history.
- Rejected mutable in-place policy rows: no audit trail and no way to tie a ledger row to the policy that produced it.
**Consequences**: Replicas poll or are notified of the active version; there is a short window where replicas differ (each request still records the version it used). Rollback runbook = re-activate previous version. Policy tables are tenant-scoped (ADR-008).

## 2026-11-05 — ADR-000a Layer tiers refined after M0 review
**Decision**: The import-linter `layers` contract has these tiers, top to bottom: api | cli → orchestration (gateway_service : execution_service : container : workers) → services (`*_service`, mutually independent `|`) → service-support (circuit_breaker | retry_budget | retry | security) → data access (infrastructure | adapters, independent) → application.models → domain. `application.retry` (backoff/jitter helpers) is added to the design under T17. A unit test fails if any `switchyard.application.*` module is missing from the contract.
**Context**: M0 review found services could import each other cyclically and new modules could go unlayered; services need CircuitBreaker and TenantContext.
**Rationale**: Independence between services keeps them unit-testable in isolation; a support tier gives shared policy objects a home without letting services depend on each other. Rejected: one flat `:`-joined service layer (allows cycles); moving CircuitBreaker into infrastructure (it is policy logic, not I/O).
**Consequences**: Layer skipping (e.g. api → domain) remains allowed, as in the original design. Redaction in logs uses dependency inversion: `Telemetry` (infrastructure) accepts a `LogRecordFilter` Protocol defined in `domain`; `container` injects `Redactor` (security). Infrastructure never imports security. Fixes the upward import in design Part 02 §1.10.

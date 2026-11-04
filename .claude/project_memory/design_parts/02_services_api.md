# Design Part 02 — Services, Orchestration, Workers, API, CLI

> Names follow `00_contract.md`. New names introduced here are marked *(new)*. All money is `Decimal`; all time comes from an
> injected `Clock` *(new, `switchyard.domain.clock`: `now() -> datetime`, `monotonic() -> float`, `async sleep(s)`)*; randomness
> comes from an injected `random.Random` (NFR-18). Every repository call takes `tenant_id` (FR-67).

## 1. Service layer (layer 2)

### 1.1 Shared typed models *(new, `switchyard.application.models` unless stated)*
| Model | Fields | Used by |
|---|---|---|
| `AdmissionTicket` | tenant_id, request_id, est_tokens: int, concurrency_slot: bool, degraded: bool | Admission |
| `Reservation` | reservation_id: UUID, tenant_id, request_id, period: str, amount_usd: Decimal, soft_exceeded: bool, expires_at | Budget |
| `AttemptCost` | attempt_id, model_id, usage: Usage, cost_usd: Decimal, pricing_version | Budget |
| `SettlementInput` | reservation: Reservation \| None, request_id, terminal: RequestState, attempts: list[AttemptCost], policy_version: int, cache_status: CacheStatus | Budget |
| `SettlementResult` | request_id, spent_usd: Decimal, released_usd: Decimal, usage_source: UsageSource, already_settled: bool, late: bool | Budget |
| `IdempotencyClaimed` / `IdempotencyReplay` | key, request_hash / key, response: CanonicalResponse, original_request_id | Idempotency (union `IdempotencyOutcome`) |
| `CacheStatus` (StrEnum) | HIT, MISS, BYPASS | Cache, API headers |
| `CacheDecision` | status: CacheStatus, key: str \| None, ttl_s: int, reason: str | Cache |
| `ResolvedPolicy` | route_id, route: RoutePolicy, execution: ExecutionPolicy, cache: CachePolicy, version: int | Policy |
| `PolicyVersionInfo` | tenant_id, version: int, sha256, created_at, active: bool, actor | Policy, CLI |
| `BreakerState` (StrEnum) | CLOSED, OPEN, HALF_OPEN | Breaker, routing |
| `IssuedApiKey` | key_id, prefix, raw_key: SecretStr, expires_at \| None | ApiKeyService, CLI |
| `ApiKeyInfo` | key_id, tenant_id, name, prefix, created_at, expires_at, revoked_at, status | ApiKeyService, CLI |
| `RedactedPayload` (`switchyard.security`) | fields: tuple[tuple[str, str], ...], redacted: bool | Redactor, Telemetry |

### 1.2 AdmissionService — `application/admission_service.py` (FR-68, FR-69, NFR-09, NFR-15)
| Item | Spec |
|---|---|
| Ctor | `(redis: RedisClient, limits: RequestLimits, clock: Clock)`; `RequestLimits` *(new, from `Settings`)*: body_bytes=1 MiB, max_messages=256, max_tool_payload_bytes=64 KiB |
| `validate_shape(req: CanonicalRequest, model_max_output: int) -> None` | sync, pure; message count, `max_tokens <= model_max_output`, tool payload size → `InvalidRequestError` |
| `async admit(ctx: TenantContext, request_id: str, est_tokens: int) -> AdmissionTicket` | one Lua call (`RedisClient.run_script("token_bucket", ...)`) checks RPM bucket, TPM bucket (est_tokens) and concurrency counter atomically; keys `rl:{tenant_id}:{rpm\|tpm\|conc}` → `RateLimitedError(retry_after_s)` |
| `async release(ticket: AdmissionTicket, actual_tokens: int) -> None` | decrements concurrency; refunds `est - actual` TPM; never raises |
| Redis down | fail-open: ticket `degraded=True`, metric `switchyard_ratelimit_degraded_total` (Redis loss resets limits only, NFR-15) |

### 1.3 BudgetService — `application/budget_service.py` (FR-61, FR-74–82, NFR-05/06)
| Item | Spec |
|---|---|
| Ctor | `(budgets: BudgetRepository, ledger: LedgerRepository, estimator: CostEstimator, clock: Clock, reservation_ttl: timedelta)`; TTL = `deadline_ms + 5 min` (OQ-03) |
| `async reserve(ctx: TenantContext, request_id: str, req: CanonicalRequest, candidates: list[ModelSpec], execution: ExecutionPolicy) -> Reservation` | amount = `max_m(in_est × in_price_m) × max_attempts + max_m(max_tokens × out_price_m)` (input re-billed per attempt; output billed once because no retry after first token). Single `UPDATE budgets ... WHERE spent+reserved+amt <= limit RETURNING id` + `INSERT budget_reservations(status='reserved')` in one txn. Hard limit, 0 rows → `BudgetExceededError`; soft limit, 0 rows → reserve anyway, `soft_exceeded=True`, alert event |
| `async settle(inp: SettlementInput) -> SettlementResult` | one txn: `SELECT reservation FOR UPDATE`; `INSERT ledger ... ON CONFLICT (tenant_id, request_id) DO NOTHING` (0 rows → `already_settled=True`, no-op); `spent += Σ attempt cost`, `reserved -= amount`, status `committed` (cost>0) or `released` (cost=0). If the reservation is already `expired`: add cost to `spent` only, `late=True` |
| `cost_attempts(attempts: list[AttemptRecord], specs: Mapping[str, ModelSpec]) -> list[AttemptCost]` | pure, per-attempt pricing via `CostEstimator.actual_cost` (attempts can use different models) |
| Errors | `BudgetExceededError` (402); DB errors propagate (money must never be guessed) |

### 1.4 IdempotencyService — `application/idempotency_service.py` (FR-83–87, NFR-07)
| Item | Spec |
|---|---|
| Ctor | `(repo: IdempotencyRepository, clock: Clock, retention: timedelta = 24h, lease: timedelta)`; lease = reservation TTL |
| `request_hash(req: CanonicalRequest) -> str` | pure: sha256 of canonical JSON (sorted keys, `exclude_none`) |
| `async begin(ctx, key: str, request_hash: str, request_id: str) -> IdempotencyOutcome` | `INSERT ... ON CONFLICT (tenant_id, key) DO NOTHING RETURNING`; on conflict read row: hash differs → `IdempotencyMismatchError` (422); `in_progress` and `locked_until > now` → `IdempotencyConflictError` (409); `in_progress` with lease expired or `failed` → take over (CAS update) → `IdempotencyClaimed`; `completed` → `IdempotencyReplay` |
| `async complete(ctx, key, response: CanonicalResponse) -> None` | store response (JSONB, `response_ref`), `status='completed'` |
| `async abandon(ctx, key) -> None` | `status='failed'` so the next retry re-executes (failures are not replayed) |
| Key validation | 1–255 printable ASCII → else `InvalidRequestError` |

### 1.5 CacheService — `application/cache_service.py` (FR-88–92, NFR-11)
| Item | Spec |
|---|---|
| Ctor | `(redis: RedisClient, clock: Clock)` |
| `decide(ctx, resolved: ResolvedPolicy, req: CanonicalRequest) -> CacheDecision` | pure: BYPASS unless `cache.exact` and `temperature == 0` and `stream is False` (v1 bypasses streaming; no buffering); else key `cache:{tenant_id}:{sha256(...FR-88 fields)}` |
| `async get(decision: CacheDecision) -> CanonicalResponse \| None` | Redis error/corrupt entry → `None` + metric (never raises) |
| `async put(decision, resp: CanonicalResponse) -> None` | skip if `resp` has tool calls or `finish_reason != stop`; `SET EX ttl_s` (default 3600, OQ-06); never raises |

### 1.6 PolicyService — `application/policy_service.py` (FR-93–96)
| Item | Spec |
|---|---|
| Ctor | `(repo: PolicyRepository, registry: CapabilityRegistry, validator: PolicyValidator, clock: Clock)` |
| `async load_active() -> None` | load all tenants' active versions into an in-memory snapshot; on failure keep last-known-good; raise only at startup with no LKG |
| `async refresh() -> None` | called every 10 s by lifespan task; swaps snapshot atomically |
| `resolve(ctx: TenantContext, model: str) -> ResolvedPolicy` | sync, no I/O: `model` = route id, else registry model id (implicit single-model route). Unknown → `InvalidRequestError`; route not allowed for tenant → `PermissionDeniedError` |
| `async apply(tenant_id, yaml_text: str, actor: str) -> PolicyVersionInfo` | parse → `PolicyValidator` (schema, models exist, chains capability-compatible) → insert inactive version; invalid → `InvalidRequestError`, active version untouched |
| `async activate(tenant_id, version) -> PolicyVersionInfo`, `async rollback(tenant_id, to: int \| None) -> PolicyVersionInfo`, `async list_versions(tenant_id) -> list[PolicyVersionInfo]` | activation is one txn flipping `active`; rollback default = previous active version; audit event each |

### 1.7 RetryBudget — `application/retry_budget.py` (FR-57)
| Item | Spec |
|---|---|
| Ctor | `(redis: RedisClient, policy: RetryBudgetPolicy, clock: Clock)`; scope per provider; 10 × 6 s buckets (60 s window); floor of 10 retries/window |
| `async record_request(provider: str) -> None` | once per logical request |
| `async try_acquire(provider: str) -> bool` | atomic Lua: allow iff `retries + 1 <= max(floor, ratio × requests)`; denial → metric `switchyard_retry_budget_exhausted_total` + alert |
| Redis down | in-process per-replica counters (same algorithm) |

### 1.8 CircuitBreaker — `application/circuit_breaker.py` (FR-58, FR-59)
| Item | Spec |
|---|---|
| Ctor | `(redis: RedisClient, policy: CircuitBreakerPolicy, clock: Clock)`; state in hash `cb:{model_id}`, transitions in Lua (shared across replicas) |
| `async states(model_ids: Sequence[str]) -> dict[str, BreakerState]` | one pipelined read for routing's health filter |
| `async allow(model_id) -> bool` | CLOSED → True; OPEN past `open_duration_s` → HALF_OPEN; HALF_OPEN grants ≤ `half_open_probes` permits |
| `async record_success(model_id) -> None` / `async record_failure(model_id, error_class: ErrorClass) -> None` | counts only provider_unavailable, timeout, malformed_response (not 429/4xx/cancel); `failure_threshold` in `rolling_window_s` → OPEN; probe failure → OPEN; all probes OK → CLOSED |
| Redis down | treated as CLOSED (fail-open) + metric |

### 1.9 ApiKeyService — `security/api_keys.py` (FR-63–66)
| Item | Spec |
|---|---|
| Ctor | `(keys: ApiKeyRepository, tenants: TenantRepository, audit: AuditRepository, hasher: ApiKeyHasher, clock: Clock)` |
| Key format | `sy_<prefix:8>_<secret:32 base62>`; stored `prefix` + `HMAC-SHA-256(pepper, raw)`; pepper from Secrets Manager |
| `async authenticate(raw_key: str) -> TenantContext` | lookup by prefix, `hmac.compare_digest`; unknown/expired/revoked → `AuthenticationError` (same message), audit `auth.failed` / `key.expired` (prefix only); 10 s in-process positive cache |
| `async create(tenant_id, name, expires_at: datetime \| None) -> IssuedApiKey` | raw key returned once; audit `key.created` |
| `async rotate(key_id, grace: timedelta) -> IssuedApiKey` | new key; old `expires_at = now + grace`; audit `key.rotated` |
| `async revoke(key_id) -> None` / `async list_keys(tenant_id) -> list[ApiKeyInfo]` | audit `key.revoked`; list sorted `(created_at, key_id)` |

### 1.10 Redactor — `security/redaction.py` (FR-71, NFR-14)
| Item | Spec |
|---|---|
| Ctor | `(secret_patterns: tuple[re.Pattern[str], ...])` — `sy_…`, `sk-…`, bearer tokens |
| `redact_request(req: CanonicalRequest, ctx: TenantContext) -> RedactedPayload` | sync, pure: message content and tool args → `[REDACTED len=N sha=8hex]` unless `ctx.log_prompts`; secret patterns scrubbed always |
| `redact_text(text: str, allow_content: bool) -> str` | used by `Telemetry` span/log processor |

## 2. Orchestration (layer 3)

### 2.1 GatewayService — `application/gateway_service.py` (FR-07, FR-36–41, FR-84, FR-91, FR-96)
Ctor `(policy: PolicyService, idempotency: IdempotencyService, admission: AdmissionService, budget: BudgetService, cache: CacheService, routing: RoutingService, execution: ExecutionService, api_keys: ApiKeyService, registry: CapabilityRegistry, telemetry: Telemetry, clock: Clock)`. `RoutingService` lives in `application/routing_service.py` (other part): `async route(req, resolved, ctx) -> RouteDecision`.

| Method | Returns / raises |
|---|---|
| `async handle(request: CanonicalRequest, tenant_ctx: TenantContext, idempotency_key: str \| None, request_id: str, cancel_event: asyncio.Event) -> GatewayResult` | `GatewayResult` *(new)* = `CompletedResult(response: CanonicalResponse, meta: ResponseMeta)` \| `StreamingResult(meta: ResponseMeta, events: AsyncIterator[StreamEvent])`; raises `GatewayError` subclasses only before any byte is sent |
| `async authenticate(raw_key: str) -> TenantContext` | delegates to `ApiKeyService` (keeps API → orchestration → service) |
| `list_models(ctx) -> list[ModelSpec]` | `active` registry models + tenant routes, sorted by id (FR-02) |
| `async readiness() -> ReadinessReport` | *(new: db_ok, redis_ok, policy_loaded, draining)*; DB required, Redis degraded still ready |

`ResponseMeta` *(new)*: request_id, cache: CacheStatus, provider \| None, model \| None, attempts: int, policy_version \| None, replay: bool.

**Pipeline** (`lc = RequestLifecycle(request_id)` created in RECEIVED before step 1):

| # | Step | Success transition | On error |
|---|---|---|---|
| 1 | `policy.resolve(ctx, req.model)`; `admission.validate_shape` | — | `InvalidRequestError`/`PermissionDeniedError` → REJECTED → settle no-op → 400/403 |
| 2 | if key: `idempotency.begin(...)` | Claimed → continue; Replay → ADMITTED→CACHE_HIT→COMPLETED, zero-cost settle, `meta.replay=True`, cache header `bypass` | 409/422 → REJECTED → settle no-op |
| 3 | `admission.admit(...)` then `budget.reserve(..., candidates=route candidates)` | RECEIVED→ADMITTED | `RateLimitedError` → REJECTED (429); `BudgetExceededError` → release ticket, REJECTED (402) |
| 4 | `cache.decide` + `cache.get` | hit → ADMITTED→CACHE_HIT→COMPLETED; settle cost 0 (reservation `released`, ledger row cache=hit) | Redis failure = miss |
| 5–6 | `routing.route(...)` (capability → breaker health → strategy) → `RouteDecision.chain` | ADMITTED→ROUTED | `NoEligibleModelError(reason=capability_mismatch\|no_healthy_candidate)` → FAILED → 400/503 |
| 7 | `execution.run(...)` / `execution.stream(...)` | ROUTED→ATTEMPTING(⇄RETRY_WAIT\|FALLBACK)→[STREAMING]→COMPLETED | FAILED/CANCELLED set by ExecutionService |
| 8 | normalization is inside adapters; attach `ResponseMeta`; on success `cache.put`, `idempotency.complete` | — | failure → `idempotency.abandon` |
| 9 | `_settle_once(...)` in `finally` (2.4) | terminal→SETTLED | settle errors logged + metric; reservation left to expiry worker |

Streaming: `handle` pre-pulls events from `execution.stream` until the first content event (`ContentDelta`/`ToolCallDelta`) or a terminal event, so every retry/fallback happens before headers are committed; `events` replays the buffered events, then continues the live iterator. Headers carry the real provider/model/attempts.

### 2.2 ExecutionService — `application/execution_service.py` (FR-39–60)
Ctor `(adapters: AdapterRegistry, breaker: CircuitBreaker, retry_budget: RetryBudget, clock: Clock, rng: random.Random, telemetry: Telemetry)`.
- `async run(req, decision: RouteDecision, execution: ExecutionPolicy, lc: RequestLifecycle, cancel_event) -> CanonicalResponse`
- `stream(req, decision, execution, lc, cancel_event) -> AsyncIterator[StreamEvent]` (exactly one terminal `StreamEnd`/`StreamError`, FR-12)

Attempt loop (shared; `deadline = clock.monotonic() + deadline_ms`):
```
idx = attempts = fallbacks = retry_n = 0
await retry_budget.record_request(chain[0].provider)
loop:
  model = chain[idx]
  if not await breaker.allow(model.id):              # opened mid-request: skip, no transition, no attempt
      idx += 1; if idx == len(chain): raise NoEligibleModelError(no_healthy_candidate)
      continue
  if deadline - now <= 0: raise ProviderTimeoutError(kind=deadline)
  attempts += 1; lc.transition(ATTEMPTING); ctx = AttemptContext(uuid7(), deadline, timeouts, cancel_event)
  try:   run adapter.complete / iterate adapter.stream (first-token rule below)
         await breaker.record_success(model.id); lc.transition(COMPLETED); return
  except (ClientCancelledError, CancelledError): lc.transition(CANCELLED); raise   # never retried
  except GatewayError as e:
         record attempt usage (2.3); await breaker.record_failure(model.id, e.error_class)
         if lc.first_token_seen: yield StreamError(e); lc.transition(FAILED); return
         d = classify(e)
         if d is FAIL or attempts >= max_attempts:            -> FAILED, raise e
         if not await retry_budget.try_acquire(model.provider): -> FAILED, raise e (fail fast)
         wait = e.retry_after_s if d is RETRY_AFTER else full_jitter(retry_n)
         same_ok = (d is RETRY) or wait <= max_backoff_ms
         if same_ok and now + wait < deadline:  RETRY_WAIT; sleep(wait) racing cancel_event; retry_n += 1
         elif fallbacks < max_fallbacks and idx + 1 < len(chain):  FALLBACK; idx += 1; fallbacks += 1; retry_n = 0
         else:                                   -> FAILED, raise e
```
| Rule | Spec |
|---|---|
| Full jitter | `rng.uniform(0, min(max_backoff_ms, initial_backoff_ms × 2**retry_n))` ms |
| Retry-After | honoured exactly, never shortened; exceeds `max_backoff_ms` or remaining deadline → fall back now, else fail fast (FR-51) |
| Never retried | 400, 401/403 (+ `provider_auth_alert` metric), context overflow, cancellation (FR-53–56) |
| Timeouts | adapter enforces `connect_ms`, `first_token_ms`, `idle_stream_ms`; every wait = `min(timeout, deadline - now)`; expiry → `ProviderTimeoutError(kind)` (FR-46/48) |
| First-token rule | first `ContentDelta`/`ToolCallDelta` yielded → `lc.first_token_seen`, ATTEMPTING→STREAMING; afterwards any error ends the stream with `StreamError`: no retry, no fallback, no provider switch (FR-39, FR-42–44) |
| Correlated outage | all candidates fail/open → last typed error (503) before `deadline_ms`, since every sleep/wait is clipped to the deadline (FR-60) |
| Cancellation | API disconnect watcher (or drain-timeout task cancel) sets `cancel_event` → adapter `aclose()`s its httpx stream → `ClientCancelledError` → CANCELLED; `asyncio.CancelledError` re-raised after settlement (FR-40, FR-45) |
| Spans | one child span per attempt: attempt_id, model, error class, retry/fallback reason, wait_ms (FR-97) |

### 2.3 Usage from failed billable attempts (FR-41, FR-79)
| Case | `AttemptRecord.usage` |
|---|---|
| Success | reported `Usage` (`REPORTED`); missing → estimate (`ESTIMATED`) |
| Rejected before provider accepted it (connect error, 429, 4xx, 5xx status before body) | `None` (not billable) |
| Failed after acceptance (TTFT/idle/deadline timeout, stream drop, malformed chunk, cancel after send) | last `UsageEvent` if any; else input-token estimate + output tokens counted from emitted deltas, `ESTIMATED` |

Accumulation: `RequestLifecycle.billable_attempts()` *(proposed addition to lifecycle)* returns attempts with non-null usage; `BudgetService.cost_attempts` prices each with its own model; one ledger row lists all `attempt_ids`; `usage_source=ESTIMATED` if any attempt was estimated.

### 2.4 Settlement — exactly once
```
try:     steps 1-8 (non-stream)  |  generator body wrapping execution.stream (stream)
finally:
    if lc.settle():                                  # idempotent; True only on the first call
        await asyncio.shield(self._settle_once(lc, reservation, ticket))
```
- `_settle_once`: `budget.settle(SettlementInput(...))` then `admission.release(ticket, actual_tokens)`; idempotency complete/abandon runs before it.
- Streaming: Starlette `aclose()`s the generator on disconnect, so `finally` runs on success, error, disconnect and drain-cancel; `shield` stops a cancel interrupting the commit.
- Two guards: `lc.settle()` (in-process) + ledger `UNIQUE(tenant_id, request_id)` (cross-process). Crash before settle → reservation expires (3), NFR-06.

## 3. Workers (layer 3, `switchyard.workers`)
Both run as lifespan background tasks on every replica (`SKIP LOCKED` keeps replicas safe) and via `switchyard worker run` *(new)*. Loop: `while not stop.is_set(): await tick(); await wait_for(stop, interval)`; a failed tick is logged + counted and never kills the loop.

| Worker | Interval / batch | Query | Writes |
|---|---|---|---|
| `ReservationExpiryWorker(budgets: BudgetRepository, ledger: LedgerRepository, telemetry, clock)`, `workers/reservation_expiry.py` (FR-82) | 30 s / 500, repeat while batch full | `SELECT id, tenant_id, request_id, period, amount_usd FROM budget_reservations WHERE status='reserved' AND expires_at < now() ORDER BY expires_at, id LIMIT 500 FOR UPDATE SKIP LOCKED` | one txn per batch: `status='expired'`; `budgets.reserved_usd -= Σamount` per (tenant_id, period); ledger marker `kind='expiry', cost=0, flagged=true`; metric `switchyard_reservations_expired_total` (alert > 0) |
| `IdempotencyCleanupWorker(repo: IdempotencyRepository, telemetry, clock)`, `workers/idempotency_cleanup.py` (FR-87) | 300 s / 1000 | `DELETE FROM idempotency_keys WHERE (tenant_id, key) IN (SELECT tenant_id, key FROM idempotency_keys WHERE expires_at < now() ORDER BY expires_at LIMIT 1000 FOR UPDATE SKIP LOCKED)` | deletes rows + stored responses; metric `switchyard_idempotency_deleted_total` |

Late settlement after expiry still adds the actual cost to `spent` (tokens were consumed), with `late=True` and a metric.

## 4. API surface (layer 4, `switchyard.api`)

### 4.1 `create_app(settings: Settings) -> FastAPI` and lifespan
| Phase | Actions (in order) |
|---|---|
| Startup | `Telemetry.init` → `Database.connect` (fail = abort) → `RedisClient.connect` (fail = degraded, not abort) → load + validate `CapabilityRegistry` (invalid = abort, FR-24) → load secrets + build `AdapterRegistry` (shared `httpx.AsyncClient` per provider) → `PolicyService.load_active` (no LKG = abort) → wire services into a `Container` *(new, `app.state.container`)* → start tasks: policy refresh (10 s), `ReservationExpiryWorker`, `IdempotencyCleanupWorker` |
| SIGTERM | `switchyard serve` runs `GracefulServer` *(new, `uvicorn.Server` subclass)*: `handle_exit` first sets `ShutdownCoordinator.draining=True` (`/readyz` → 503, new `/v1/*` requests → 503 `server_draining` + `Retry-After: 1`), then uvicorn stops accepting with `timeout_graceful_shutdown = drain_timeout_s` (default 30 s, below ECS `stopTimeout` 60 s) |
| Drain | `ShutdownCoordinator` *(new)* counts active SSE streams; in-flight streams run to completion; after `drain_timeout_s` the rest get `cancel_event` set → typed `server_shutdown` `StreamError` → settled (FR-107, NFR-12) |
| Shutdown | stop workers + refresh task (await) → wait for pending settlements → close adapters' httpx clients → Redis → DB → `Telemetry.shutdown` (flush) |

### 4.2 Middleware (pure ASGI, no `BaseHTTPMiddleware`, so streams are not buffered)
| Order (outer → inner) | Middleware | Job |
|---|---|---|
| 1 | `RequestIdMiddleware` | accept valid inbound `x-request-id` (≤ 64 chars, `[A-Za-z0-9-]`) else uuid7; set on scope + response header first (FR-05) |
| 2 | OTel ASGI middleware (`Telemetry`) | root span with `request_id` |
| 3 | `BodyLimitMiddleware` | reject `Content-Length` > limit or streamed body overflow → 413 before parsing (FR-06) |
| — | `get_tenant_context` (dependency, not middleware) | `Authorization: Bearer` → `GatewayService.authenticate` → `TenantContext`; missing/invalid → 401 before any service (FR-65) |

Exception handlers: `GatewayError` → `ErrorMapper` *(new)* (4.5); `RequestValidationError` → 400 `invalid_request` (never FastAPI's default 422, which is reserved for idempotency mismatch); unknown `Exception` → 500 `internal_error`, redacted log.

### 4.3 Routes (`api/routes.py`)
| Route | Auth | Behaviour |
|---|---|---|
| `GET /healthz` | no | 200 `{"status":"ok"}`; process only, no I/O (FR-03) |
| `GET /readyz` | no | `GatewayService.readiness()` → 200, or 503 if DB down / policy not loaded / draining |
| `GET /v1/models` | yes | `{"object":"list","data":[{"id","object":"model","created","owned_by"}]}`, sorted by id (FR-02) |
| `POST /v1/chat/completions` | yes | `ChatCompletionRequest` *(new, pydantic `extra="forbid"`, OpenAI wire)* → `RequestMapper` *(new)* → `CanonicalRequest` (unknown field → 400, FR-10) → `GatewayService.handle` → JSON `chat.completion` or `StreamingResponse` |

Request mapping: `Idempotency-Key` header → `idempotency_key`; `stream_options.include_usage` honoured; `DisconnectWatcher` *(new)* task polls `request.is_disconnected()` every 100 ms and sets `cancel_event`.

### 4.4 SSE framing (OpenAI-compatible, `api/sse.py`, `SseEncoder` *(new)*)
| Event | Wire |
|---|---|
| `StreamStart` | `data: {"id","object":"chat.completion.chunk","created","model","choices":[{"index":0,"delta":{"role":"assistant"},"finish_reason":null}]}\n\n` |
| `ContentDelta` / `ToolCallDelta` | same chunk shape, `delta.content` / `delta.tool_calls[{index,id,type,function{name,arguments}}]` |
| `StreamEnd` | chunk with empty `delta` + `finish_reason`; then usage chunk (`choices: []`, `usage`) if `include_usage`; then `data: [DONE]\n\n` |
| `UsageEvent` | buffered; emitted only in the final usage chunk |
| `StreamError` (mid-stream) | `data: {"error":{"message","type","code","param":null},"switchyard":{"sequence":n,"request_id"}}\n\n`, then close **without** `[DONE]` (OpenAI SDK raises `APIError`) |
| keepalive | `: ping\n\n` every 15 s with no events |

Stream headers: `content-type: text/event-stream`, `cache-control: no-cache`, `x-accel-buffering: no`, plus 4.5 headers. Status is always 200 once streaming starts; errors before the first byte use the normal JSON error (4.6).

### 4.5 Response headers (every response incl. errors, from `ResponseMeta`)
| Header | Value |
|---|---|
| `x-request-id` | request id (also on 401/413) |
| `x-switchyard-cache` | `hit` \| `miss` \| `bypass` (FR-90) |
| `x-switchyard-provider` / `x-switchyard-model` | provider and model id of the last attempt (omitted if none) |
| `x-switchyard-attempts` | int, provider attempts made (0 for cache hit/replay) |
| `x-switchyard-policy-version` | active policy version used (FR-96) |
| `retry-after` | on 429/503 when known |

### 4.6 HTTP error mapping (`ErrorMapper`, body `{"error":{"message","type","param","code"}}`, `type` = `ErrorClass` value)
| Status | Errors | `type` / `code` |
|---|---|---|
| 400 | `InvalidRequestError`, `ContextOverflowError`, `NoEligibleModelError(capability_mismatch)` | `invalid_request` / `invalid_request`, `context_overflow`, `capability_mismatch` |
| 401 | `AuthenticationError` | `auth_failed` / `invalid_api_key` |
| 402 | `BudgetExceededError` | `budget_exceeded` / `budget_exceeded` |
| 403 | `PermissionDeniedError` | `auth_failed` / `route_not_allowed` |
| 409 | `IdempotencyConflictError` | `idempotency_conflict` / `in_progress` |
| 413 | `BodyLimitMiddleware` | `invalid_request` / `body_too_large` |
| 422 | `IdempotencyMismatchError` | `idempotency_conflict` / `body_mismatch` |
| 429 | `RateLimitedError` (tenant limit or provider exhausted) | `rate_limited` / `rpm`, `tpm`, `concurrency`, `provider` + `Retry-After` |
| 502 | `MalformedProviderResponseError` | `malformed_response` |
| 503 | `ProviderOverloadedError`, `ProviderServerError`, `NoEligibleModelError(no_healthy_candidate)`, draining | `provider_unavailable` / `no_healthy_candidate`, `server_draining` |
| 504 | `ProviderTimeoutError(kind)` | `timeout` / `connect`, `ttft`, `idle`, `deadline` |
| (499, log only) | `ClientCancelledError` | `cancelled` (client is gone, nothing sent) |

Provider 401/403 maps to 503 `provider_unavailable` (it is the gateway's credential problem, not the client's) and raises the auth alert.

## 5. CLI (layer 4, `switchyard.cli`, typer)
`switchyard.cli.main:app`; each command builds a `Container` via `Settings` and calls orchestration flows `PolicyAdminFlow` / `KeyAdminFlow` *(new, `application/admin_flows.py`, layer 3: txn + audit sequencing over `PolicyService` / `ApiKeyService`)*. Output: `rich` table or `--json`; exit 0 ok, 1 validation error, 2 not found.

| Command | Args / options | Calls |
|---|---|---|
| `policy apply FILE` | `--tenant`, `--activate`, `--dry-run` | validate → `apply` (→ `activate` if flag); prints version + diff summary |
| `policy list` | `--tenant` | `list_versions`, sorted by version desc, marks active |
| `policy activate VERSION` | `--tenant` | `activate` |
| `policy rollback` | `--tenant`, `--to VERSION` | `rollback` (default previous active) |
| `keys create` | `--tenant`, `--name`, `--expires-in-days` | `create`; raw key printed once to stdout, never logged |
| `keys rotate KEY_ID` | `--grace-hours` (default 24) | `rotate` |
| `keys revoke KEY_ID` | `--yes` (else confirm prompt) | `revoke` |
| `keys list` | `--tenant` | `list_keys` (prefix only, never hashes) |
| `serve` / `worker run` | `--host`, `--port` / `--only expiry\|cleanup` | `GracefulServer` / worker loops |

## 6. Decisions for merge into `decisions.md`
| Decision | Choice | Rejected |
|---|---|---|
| Budget reservation timing | step 3, upper bound over route candidates (keeps plan order; REJECTED only before ADMITTED) | reserve after routing (needs ROUTED→REJECTED) |
| Reservation amount | input × max_attempts + output once | full cost × max_attempts (over-reserves 3×) |
| Idempotent replay lifecycle | ADMITTED→CACHE_HIT→COMPLETED, zero-cost settle | new REPLAYED state (contract change) |
| Streaming headers | pre-pull to first content event before committing headers | headers before first attempt (provider unknown) |
| Redis failure | fail-open for limits, breaker, retry budget, cache | fail-closed (Redis becomes availability SPOF) |
| Streaming cache | bypass in v1 | buffered stream caching (more complexity, little gain) |
| Proposed contract additions | `RequestLifecycle.billable_attempts()`, `NoEligibleModelError.reason`, `ProviderTimeoutError.kind`, `idempotency_keys.locked_until` | — |

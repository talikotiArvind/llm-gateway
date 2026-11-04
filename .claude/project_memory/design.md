# Switchyard — System Design

Assembled 2026-11-04 from parallel design parts (`design_parts/`). Sources: `requirements.md`, `project_plan.md`.
Decisions: `decisions.md` (ADR-000..010). Precedence on conflict: 00 contract > 03 persistence (money/SQL) > 02 services > 01 core.

Reconciliations applied at assembly:
- Composition root is `switchyard.application.container.Container` (01 §1); no `bootstrap.py`.
- `RoutePlanner` (domain, pure) is used by `RoutingService` (application, adds breaker health + latency).
- Reservation = `input_est × in_price × max_attempts + max_tokens × out_price`, priced at the most expensive route candidate.
- Late settlement after expiry appends a `late_settlement` ledger row with the real cost (never dropped).
- Alembic history strictly linear; 0005 re-pointed to 0004 at the group-O merge.
- Branch grouping changes vs the confirmed table: see Part 04 "Collisions found and fixes".
- Layer tiers refined after the M0 review (ADR-000a in decisions.md): services are mutually independent; a service-support tier (circuit_breaker | retry_budget | retry | security) sits below them; `application.models` sits just above domain; `Telemetry` gets redaction via a domain `LogRecordFilter` Protocol injected by `container` (no infrastructure → security import).

# Design naming contract (shared by all design-part writers)

Every design part MUST use these names exactly. Add new names freely, but never rename these.

## Package → layer
| Layer (CLAUDE.md) | Packages |
|---|---|
| 0. Domain (pure, no I/O; importable by all) | `switchyard.domain` |
| 1. Data access | `switchyard.infrastructure` (db, redis, telemetry, secrets, repositories), `switchyard.adapters` (provider adapters) |
| 2. Service logic | `switchyard.application.*_service` (budget, idempotency, cache, admission, policy, routing), `switchyard.security` (api_keys, redaction) |
| 3. Orchestration | `switchyard.application.gateway_service`, `switchyard.application.execution_service`, `switchyard.workers` |
| 4. API surface | `switchyard.api` (FastAPI app factory, routes, middleware, SSE), `switchyard.cli` |
Imports flow downward only: api → orchestration → service → data access → domain.

## Key type names
- domain/schema.py: `ChatMessage`, `ToolDefinition`, `ToolCall`, `ToolChoice`, `ResponseFormat`, `CanonicalRequest`, `Usage` (input/output/cached_input/reasoning tokens, `usage_source: UsageSource`), `UsageSource` (REPORTED, ESTIMATED), `FinishReason`, `CanonicalResponse`, `StreamEvent` (discriminated union: `StreamStart`, `ContentDelta`, `ToolCallDelta`, `UsageEvent`, `StreamEnd`, `StreamError`; each has `sequence: int`)
- domain/errors.py: base `GatewayError`; subclasses `InvalidRequestError`, `AuthenticationError`, `PermissionDeniedError`, `RateLimitedError(retry_after_s)`, `ProviderOverloadedError`, `ProviderServerError`, `ProviderTimeoutError`, `ContextOverflowError`, `ClientCancelledError`, `BudgetExceededError`, `IdempotencyConflictError`, `IdempotencyMismatchError`, `NoEligibleModelError`, `MalformedProviderResponseError`; enum `ErrorClass`; enum `RetryDecision` (RETRY, RETRY_AFTER, FAIL); function `classify(error) -> RetryDecision`
- domain/lifecycle.py: enum `RequestState` (RECEIVED, ADMITTED, CACHE_HIT, ROUTED, ATTEMPTING, RETRY_WAIT, FALLBACK, STREAMING, COMPLETED, FAILED, CANCELLED, REJECTED, SETTLED); class `RequestLifecycle` (owns `request_id`, `attempts: list[AttemptRecord]`, `transition(to)`, `first_token_seen`, `settle()` idempotent); `AttemptRecord(attempt_id, model_id, started_at, usage, error_class)`; `IllegalTransitionError`
- domain/capabilities.py: `ModelCapabilities`, `ModelPricing`, `ModelStatus`, `ModelSpec`, `CapabilityRegistry`, `RequiredCapabilities.from_request(req)`, `CapabilityMatcher`
- domain/pricing.py: `CostEstimator` (`estimate_reservation`, `actual_cost`), money as `Decimal`
- domain/routing.py: `RoutingStrategy` enum (FALLBACK, CHEAPEST_CAPABLE, LOWEST_LATENCY, WEIGHTED); `CandidateRanker`; `RouteDecision(chain: list[ModelSpec], policy_version)`
- domain/policy.py: `RoutePolicy`, `ExecutionPolicy`, `RetryPolicy`, `TimeoutPolicy`, `CircuitBreakerPolicy`, `RetryBudgetPolicy`, `CachePolicy`, `PolicyDocument(version)`, `PolicyValidator`
- adapters/base.py: `ProviderAdapter` (Protocol/ABC): `async complete(req, model, ctx) -> CanonicalResponse`, `stream(req, model, ctx) -> AsyncIterator[StreamEvent]`; `AttemptContext(attempt_id, deadline, timeouts, cancel_event)`; `AdapterRegistry`
- adapters/: `OpenAIAdapter`, `AnthropicAdapter`, `GeminiAdapter`
- application: `GatewayService`, `ExecutionService`, `AdmissionService`, `BudgetService`, `IdempotencyService`, `CacheService`, `PolicyService`, `RetryBudget`, `CircuitBreaker`
- infrastructure: `Database` (async engine/session factory), `RedisClient`, repositories `TenantRepository`, `ApiKeyRepository`, `PolicyRepository`, `BudgetRepository`, `LedgerRepository`, `IdempotencyRepository`, `AuditRepository`; `Settings` (pydantic-settings); `Telemetry`
- security: `ApiKeyHasher` (HMAC-SHA-256), `ApiKeyService`, `TenantContext`, `Redactor`
- workers: `ReservationExpiryWorker`, `IdempotencyCleanupWorker`
- api: `create_app(settings) -> FastAPI`, `RequestIdMiddleware`, `BodyLimitMiddleware`, auth dependency `get_tenant_context`
- fake_provider/: standalone FastAPI app `fake_provider.app:create_app`, OpenAI-shaped

## Contract additions (accepted 2026-11-04, from part 02)
- `RequestLifecycle.billable_attempts() -> list[AttemptRecord]`
- `NoEligibleModelError.reason: str`
- `ProviderTimeoutError.kind: Literal["connect","first_token","idle_stream","deadline"]`
- `idempotency_keys.locked_until` column
- `RoutingService` (application, wraps `CapabilityMatcher` + `CandidateRanker` + breaker health)


---

# Design Part 01 — Core (layering, domain, adapter contract, fake_provider)

> Names follow `00_contract.md` exactly. New names introduced here are marked *(new)*.

## 1. Layering

| Layer | Packages | May import |
|---|---|---|
| 4. API surface | `switchyard.api`, `switchyard.cli` | orchestration, domain |
| 3. Orchestration | `application.gateway_service`, `application.execution_service`, `application.container` *(new, composition root)*, `switchyard.workers` | service, domain |
| 2. Service logic | `application.*_service` (budget, idempotency, cache, admission, policy, routing), `switchyard.security` | data access, domain |
| 1. Data access | `switchyard.infrastructure`, `switchyard.adapters` | domain, 3rd-party I/O libs |
| 0. Domain (shared pure core) | `switchyard.domain` | stdlib allowlist + `pydantic` only |

- Direction: api → orchestration → service → data access → domain. No upward imports, no skips (api never imports infrastructure/adapters/services directly).
- Wiring: `application.container.Container.build(settings)` constructs infra + services; `create_app(settings)` only receives the container. `Settings` is imported by api under `TYPE_CHECKING` only.
- Sibling rule: `adapters` and `infrastructure` are independent (neither imports the other); `security` and `application.*_service` may not import each other's private modules.
- Why domain is under all four layers: models (`CanonicalRequest`, `StreamEvent`), errors, lifecycle and routing math are needed by every layer. Keeping them in one pure package with no I/O avoids a separate DTO set per layer, keeps them testable with hypothesis without mocks, and adds no dependency cycles because domain imports nothing above it. It holds rules and types only; it never sequences calls (orchestration) or touches I/O (data access).

### Enforcement
| Mechanism | Rule |
|---|---|
| import-linter `layers` contract (`pyproject.toml [tool.importlinter]`, `exclude_type_checking_imports = true`) | `switchyard.api \| switchyard.cli` > `switchyard.application.gateway_service \| switchyard.application.execution_service \| switchyard.application.container \| switchyard.workers` > `switchyard.application.budget_service \| ...cache_service \| ...idempotency_service \| ...admission_service \| ...policy_service \| ...routing_service \| switchyard.security` > `switchyard.infrastructure \| switchyard.adapters` > `switchyard.domain` |
| import-linter `forbidden` contract | `switchyard.domain` must not import `httpx, sqlalchemy, asyncpg, redis, fastapi, starlette, opentelemetry, boto3, botocore, socket, aiofiles, subprocess` |
| import-linter `independence` contract | `switchyard.adapters` ⟂ `switchyard.infrastructure` |
| `tests/unit/test_layering.py` (`unittest.TestCase`, pytest) | AST-walks `src/switchyard/domain/*.py`; fails on any import outside `DOMAIN_IMPORT_ALLOWLIST = {__future__, abc, collections, dataclasses, datetime, decimal, enum, functools, hashlib, itertools, json, math, random, re, typing, uuid, pydantic, switchyard.domain}` (no `asyncio`, `os`, `io`, `pathlib`); also runs `lint-imports` via subprocess when available (FR-13) |
| CI | `uv run lint-imports` step after ruff/mypy |

## 2. domain/schema.py (pydantic v2)

Base: `class CanonicalModel(BaseModel)` *(new)*: `model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)`. Every model below extends it, nested ones too, so any unknown field anywhere → `ValidationError` → `InvalidRequestError` → 400 (FR-10). `JsonValue` = pydantic `JsonValue`.

| Model | Fields (type, constraint) |
|---|---|
| `TextPart` *(new)* | `type: Literal["text"]`, `text: str` (v1 accepts text parts only; image/audio parts → 400 via the discriminator) |
| `FunctionCall` *(new)* | `name: str`, `arguments: str` (JSON text, as on OpenAI wire) |
| `ToolCall` | `id: str` (min 1), `type: Literal["function"]`, `function: FunctionCall` |
| `ChatMessage` | `role: Literal["system","developer","user","assistant","tool"]`, `content: str \| list[TextPart] \| None`, `name: str \| None`, `tool_calls: list[ToolCall] \| None`, `tool_call_id: str \| None`; validator: `tool` needs `tool_call_id`; `tool_calls` only for `assistant`; non-assistant needs content |
| `FunctionDefinition` *(new)* | `name: str` (`^[A-Za-z0-9_-]{1,64}$`), `description: str \| None`, `parameters: dict[str, JsonValue]` (default `{}` via `default_factory=dict`), `strict: bool \| None` |
| `ToolDefinition` | `type: Literal["function"]`, `function: FunctionDefinition`; request validator: names unique |
| `NamedToolChoice` *(new)* | `type: Literal["function"]`, `function: ToolChoiceFunction(name: str)` |
| `ToolChoice` | type alias `Literal["auto","none","required"] \| NamedToolChoice`; named tool must exist in `tools` |
| `JsonSchemaSpec` *(new)* | `name: str`, `schema_: dict[str, JsonValue]` (alias `schema`), `strict: bool \| None`, `description: str \| None` |
| `ResponseFormat` | discriminated on `type`: `TextFormat(type="text")`, `JsonObjectFormat(type="json_object")`, `JsonSchemaFormat(type="json_schema", json_schema: JsonSchemaSpec)` |
| `StreamOptions` *(new)* | `include_usage: bool = False` |
| `CanonicalRequest` | `model: str`, `messages: list[ChatMessage]` (min 1), `tools: list[ToolDefinition] \| None`, `tool_choice: ToolChoice \| None`, `parallel_tool_calls: bool \| None`, `temperature: float \| None` (0–2), `top_p: float \| None` (0–1), `max_tokens: int \| None` (≥1), `max_completion_tokens: int \| None` (explicitly mapped onto `max_tokens`; both set and different → 400), `stop: str \| list[str] \| None` (≤4, normalized to `list[str]`), `response_format: ResponseFormat \| None`, `stream: bool = False`, `stream_options: StreamOptions \| None`, `n: Literal[1] \| None`, `user: str \| None` (trace attribute; forwarded to OpenAI only), `provider_extensions: dict[ProviderName, dict[str, JsonValue]] \| None` |
| `ProviderName` *(new, StrEnum)* | `OPENAI="openai"`, `ANTHROPIC="anthropic"`, `GEMINI="gemini"` |
| `UsageSource` (StrEnum) | `REPORTED="reported"`, `ESTIMATED="estimated"` |
| `Usage` | `input_tokens, output_tokens, cached_input_tokens, reasoning_tokens: int` (≥0), `usage_source: UsageSource`; invariants `cached_input_tokens ≤ input_tokens`, `reasoning_tokens ≤ output_tokens` (reasoning is a subset of output); `zero(source) -> Usage`; `__add__` (ESTIMATED wins if either side is estimated) |
| `FinishReason` (StrEnum) | `STOP, LENGTH, TOOL_CALLS, CONTENT_FILTER, ERROR, CANCELLED` |
| `CanonicalResponse` | `id: str`, `request_id: str`, `attempt_id: str`, `created: int` (epoch s, from injected clock), `model: str` (requested), `resolved_provider: ProviderName`, `resolved_model: str`, `message: ChatMessage` (role assistant), `finish_reason: FinishReason`, `usage: Usage`, `provider_request_id: str \| None` |

### Provider extensions (namespaced)
- Wire field `provider_extensions` (OpenAI SDK sends it via `extra_body`), keyed by `ProviderName`, e.g. `{"anthropic": {"top_k": 40}}`.
- Each adapter declares `ALLOWED_EXTENSIONS: frozenset[str]` and reads only its own namespace. Unknown key in that namespace → 400. A key that duplicates a canonical field (e.g. `max_tokens`) → 400. Other providers' namespaces are left unused by design (documented explicit mapping, so not a silent drop).
- `PolicyValidator` does not inspect extensions; adapters do it in `to_provider_request`, before any network call.

### Stream events
`StreamEvent = Annotated[StreamStart | ContentDelta | ToolCallDelta | UsageEvent | StreamEnd | StreamError, Field(discriminator="type")]`. Shared base `_StreamEventBase`: `sequence: int` (≥0), `attempt_id: str`.

| Event | `type` | Extra fields |
|---|---|---|
| `StreamStart` | `"start"` | `resolved_model: str`, `provider_request_id: str \| None` |
| `ContentDelta` | `"content"` | `text: str` |
| `ToolCallDelta` | `"tool_call"` | `index: int`, `id: str \| None`, `name: str \| None`, `arguments_delta: str` |
| `UsageEvent` | `"usage"` | `usage: Usage` |
| `StreamEnd` | `"end"` | `finish_reason: FinishReason` (terminal, success) |
| `StreamError` | `"error"` | `error_class: ErrorClass`, `message: str` (redacted, ≤512 chars), `http_status: int \| None`, `retry_after_s: float \| None`, `usage: Usage \| None` (tokens used so far) (terminal, failure) |

`StreamSequenceValidator` *(new, pure)*: `feed(event) -> None` raises `MalformedProviderResponseError` if `sequence != last + 1` (starting at 0), if `StreamStart` is not first, if any event follows a terminal, or if a second terminal arrives; `assert_closed() -> None` raises if no terminal was seen (FR-12). Used in contract tests and by `ExecutionService`.

## 3. domain/errors.py

`GatewayError(Exception)`: `error_class: ClassVar[ErrorClass]`, `message: str`, `origin: ErrorOrigin` *(new enum: CLIENT, PROVIDER, GATEWAY)*, `provider: ProviderName | None`, `http_status_from_provider: int | None`, `alert: bool = False`; `http_status() -> int`; `to_error_body() -> ErrorBody` *(new model: type, code, message, param)*.

| Class | `ErrorClass` | Client HTTP | `classify()` → `RetryDecision` | Notes |
|---|---|---|---|---|
| `InvalidRequestError` | INVALID_REQUEST | 400 | FAIL | schema/unknown field, provider 400 |
| `AuthenticationError` | AUTH_FAILED | 401 (CLIENT) / 502 (PROVIDER) | FAIL | provider-origin sets `alert=True` (FR-54) |
| `PermissionDeniedError` | PERMISSION_DENIED | 403 (CLIENT) / 502 (PROVIDER) | FAIL | provider-origin `alert=True` |
| `RateLimitedError(retry_after_s: float \| None)` | RATE_LIMITED | 429 + `Retry-After` | PROVIDER: RETRY_AFTER if set, else RETRY; CLIENT (tenant limiter): FAIL | FR-51, FR-68 |
| `ProviderOverloadedError` | PROVIDER_UNAVAILABLE | 503 | RETRY | 529 / Gemini 503 UNAVAILABLE |
| `ProviderServerError` | PROVIDER_UNAVAILABLE | 503 | RETRY | 500/502/503/504 |
| `ProviderTimeoutError(kind: TimeoutKind)` | TIMEOUT | 504 | CONNECT/FIRST_TOKEN/IDLE_STREAM: RETRY; DEADLINE: FAIL | `TimeoutKind` *(new)*: CONNECT, FIRST_TOKEN, IDLE_STREAM, DEADLINE |
| `ContextOverflowError` | CONTEXT_OVERFLOW | 400 | FAIL | no truncation (FR-55) |
| `ClientCancelledError` | CANCELLED | 499 (logged only) | FAIL | FR-56 |
| `MalformedProviderResponseError` | MALFORMED_RESPONSE | 502 | RETRY | retried only before first token |
| `NoEligibleModelError(reason: IneligibleReason)` | CAPABILITY_MISMATCH / NO_HEALTHY_CANDIDATE | 400 / 503 | FAIL | `IneligibleReason` *(new)*: CAPABILITY_MISMATCH, NO_HEALTHY_CANDIDATE (FR-35) |
| `BudgetExceededError` | BUDGET_EXCEEDED | 402 | FAIL | FR-80 |
| `IdempotencyConflictError` | IDEMPOTENCY_CONFLICT | 409 | FAIL | in progress (FR-86) |
| `IdempotencyMismatchError` | IDEMPOTENCY_MISMATCH | 422 | FAIL | body hash differs (FR-85) |

- `classify(error: BaseException) -> RetryDecision`: a pure lookup on `(error_class, origin, kind, retry_after_s)`. Unknown exceptions → FAIL. `classify` never looks at deadline, budget or lifecycle state; `ExecutionService` combines it with `RequestLifecycle.can_retry()`, `Deadline`, `RetryBudget`.
- `ERROR_CLASS_TABLE: Mapping[ErrorClass, ErrorClassInfo(http_status, retryable, openai_type)]` *(new)* is the single source for the FR-62 status + retryable flag; tests assert every `ErrorClass` member has an entry.
- `ProviderErrorMapper` *(new, pure)*: `map(provider, status, body: Mapping[str, JsonValue] | None, headers: Mapping[str, str]) -> GatewayError` — status table: 400→context check, else Invalid; 401→Auth; 403→Permission; 404→Invalid; 408/504→`ProviderServerError` (connect/TTFT/idle timeouts are raised by the adapter, not mapped from status); 429→RateLimited(`parse_retry_after(headers, body)`); 500/502/503→Server; 529→Overloaded; other 5xx→Server; other→Malformed.
- `parse_retry_after(headers, body) -> float | None`: `retry-after` seconds or HTTP-date (with injected `now`), `retry-after-ms`; Gemini `error.details[@type=RetryInfo].retryDelay` ("12s"). Negative/unparseable → None.

### Context-overflow detection
`ContextOverflowDetector.matches(provider, status, body) -> bool` *(new)*. Only applies to status 400/413. Compiled patterns, case-insensitive:

| Provider | Signal |
|---|---|
| OpenAI | `error.code == "context_length_exceeded"` or message `/maximum context length/` |
| Anthropic | `error.type == "invalid_request_error"` and message `/prompt is too long\|exceed(s)? the context window\|max_tokens.*context/` |
| Gemini | `error.status == "INVALID_ARGUMENT"` and message `/exceeds the maximum number of tokens\|input token count/` |

Pre-flight: `CapabilityMatcher` drops models where `input_tokens_est + max_tokens > context_window`; if this empties the set, the error is `NoEligibleModelError(CAPABILITY_MISMATCH)` (400) with gap `CONTEXT_WINDOW`.

## 4. domain/lifecycle.py

`RequestLifecycle(request_id: str, clock: Callable[[], datetime], id_factory: Callable[[], str] = uuid4_hex)`. State starts at RECEIVED. Terminal set `TERMINAL = {COMPLETED, FAILED, CANCELLED, REJECTED}`.

| From | Allowed to |
|---|---|
| RECEIVED | ADMITTED, REJECTED, CANCELLED |
| ADMITTED | CACHE_HIT, ROUTED, REJECTED (capability mismatch), FAILED (no healthy candidate), CANCELLED |
| CACHE_HIT | COMPLETED |
| ROUTED | ATTEMPTING, FAILED, CANCELLED |
| ATTEMPTING | STREAMING, COMPLETED (non-stream), RETRY_WAIT†, FALLBACK†, FAILED, CANCELLED |
| RETRY_WAIT | ATTEMPTING, FAILED, CANCELLED |
| FALLBACK | ATTEMPTING, FAILED, CANCELLED |
| STREAMING | COMPLETED, FAILED, CANCELLED |
| COMPLETED, FAILED, CANCELLED, REJECTED | SETTLED |
| SETTLED | — |

† Guard: allowed only when `state == ATTEMPTING and not first_token_seen` (FR-39). STREAMING never leads to RETRY_WAIT/FALLBACK.

| Member | Signature / rule |
|---|---|
| `state` | `RequestState` (read-only property) |
| `transition(to: RequestState) -> None` | raises `IllegalTransitionError(from_, to, request_id)` when not in the table or the guard fails; state is unchanged on raise |
| `begin_attempt(model_id: str) -> AttemptRecord` | only valid after a transition into ATTEMPTING; new unique `attempt_id`; closes any open attempt first |
| `record_attempt_result(attempt_id, usage: Usage \| None, error_class: ErrorClass \| None) -> None` | once per attempt; unknown/duplicate id raises |
| `mark_first_token() -> None` | sets `first_token_seen = True`; requires ATTEMPTING (then moves to STREAMING) or STREAMING; idempotent |
| `can_retry() -> bool` | `state == ATTEMPTING and not first_token_seen` |
| `billable_usage() -> Usage` | sum of `usage` over all attempts with any tokens > 0, failed attempts included (FR-41) |
| `settle() -> Settlement` | requires a terminal state, else raises; first call moves to SETTLED and freezes `Settlement(request_id, terminal_state, attempt_ids: tuple[str, ...], usage: Usage)`; later calls return the same object (idempotent, `settle_count` stays 1) |

`AttemptRecord(attempt_id: str, model_id: str, started_at: datetime, usage: Usage | None = None, error_class: ErrorClass | None = None)` — frozen dataclass; `request_id` link is held by the parent lifecycle and copied into spans/ledger.

### Hypothesis invariants (`tests/unit/domain/test_lifecycle_properties.py`)
`LifecycleMachine(RuleBasedStateMachine)` rules: `transition(st.sampled_from(RequestState))` (illegal calls must raise and leave state unchanged), `begin_attempt`, `record_result(usage strategy, error_class strategy)`, `mark_first_token`, `cancel`, `settle` (any number of times). Teardown drives any non-terminal machine to FAILED then calls `settle()` twice.

| Requirement | Invariant checked |
|---|---|
| FR-37 | `request_id` never changes; all `attempt_id`s are unique; each is in `Settlement.attempt_ids` |
| FR-38 | at most one terminal state is ever entered; after teardown `state == SETTLED`, `settle_count == 1`, repeated `settle()` returns equal object |
| FR-39 | every accepted RETRY_WAIT/FALLBACK came from ATTEMPTING with `first_token_seen == False`; any attempt after first token raised |
| FR-40 | CANCELLED is accepted from every non-terminal state except CACHE_HIT; cancellation is never followed by ATTEMPTING (adapter half is in contract tests, §6) |
| FR-41 | `Settlement.usage == sum(a.usage for a in attempts if a.usage and tokens > 0)`, including attempts with `error_class` set |

## 5. capabilities.py, pricing.py, routing.py, policy.py

### capabilities.py
| Type | Signature |
|---|---|
| `ModelStatus` (StrEnum) | ACTIVE, DEPRECATED, DISABLED |
| `ModelCapabilities` | `streaming, tools, parallel_tools, structured_output: bool` |
| `ModelPricing` | `input_per_mtok, output_per_mtok, cached_input_per_mtok: Decimal` (≥0), `pricing_version: str` |
| `ModelSpec` | `model_id: str` (`provider/alias`), `provider: ProviderName`, `provider_model: str`, `capabilities`, `context_window: int`, `max_output_tokens: int`, `pricing: ModelPricing`, `status: ModelStatus`; `is_routable -> bool` (status != DISABLED) |
| `CapabilityRegistry` | `from_mapping(raw: Mapping[str, JsonValue]) -> CapabilityRegistry` (raises `RegistryValidationError` *(new)*; FR-24); `get(model_id) -> ModelSpec`; `routable() -> list[ModelSpec]` sorted by `model_id`; `all() -> list[ModelSpec]` |
| `RequiredCapabilities` | `streaming, tools, parallel_tools, structured_output: bool`, `input_tokens_est: int`, `output_tokens: int \| None`; `from_request(req, estimator: TokenEstimator \| None = None) -> RequiredCapabilities` (`parallel_tools` = tools present and `parallel_tool_calls is not False`; `structured_output` = `json_schema` format) |
| `CapabilityGap` *(new, StrEnum)* | STREAMING, TOOLS, PARALLEL_TOOLS, STRUCTURED_OUTPUT, CONTEXT_WINDOW, MAX_OUTPUT, DISABLED |
| `CapabilityMatcher` | `gaps(spec, req: RequiredCapabilities) -> list[CapabilityGap]`; `filter(specs, req) -> list[ModelSpec]` (order kept; FR-29) |

Fit rules: `input_tokens_est + (output_tokens or 0) ≤ context_window`; `output_tokens ≤ max_output_tokens`.

### pricing.py (money is `Decimal`, quantized to `Decimal("0.00000001")`, `ROUND_HALF_EVEN`)
| Type | Signature |
|---|---|
| `TokenEstimator` *(new)* | `estimate_input(req) -> int` = `ceil(chars/4) + 4·messages + tool schema chars/4`; `estimate_output_text(text) -> int` (deterministic heuristic, used when usage is ESTIMATED) |
| `CostEstimator` | `estimate_reservation(spec, input_tokens_est: int, max_tokens: int, max_attempts: int) -> Decimal` = `(in_est·in + max_tokens·out)/10^6 · max_attempts` (FR-61, FR-76); `estimate_cost(spec, input_tokens_est, max_tokens) -> Decimal` (one attempt, used for ranking); `actual_cost(usage: Usage, pricing: ModelPricing) -> Decimal` = `((input − cached)·in + cached·cached_in + output·out)/10^6` (FR-27) |

### routing.py
| Type | Signature |
|---|---|
| `RoutingStrategy` | FALLBACK, CHEAPEST_CAPABLE, LOWEST_LATENCY, WEIGHTED |
| `HealthSnapshot` *(new)* | `open_model_ids: frozenset[str]` (from `CircuitBreaker`, built by `RoutingService`) |
| `EwmaLatency` *(new)* | `ALPHA = 0.2`; `update(prev_ms: float \| None, sample_ms: float) -> float` = sample if prev is None else `0.2·sample + 0.8·prev` |
| `LatencySnapshot` *(new)* | `ewma_ms: Mapping[str, float]` |
| `RouteDecision` | `chain: list[ModelSpec]`, `policy_version: int`, `strategy: RoutingStrategy`, `excluded: dict[str, list[CapabilityGap]]` (for traces) |
| `CandidateRanker` | `__init__(cost: CostEstimator, rng: random.Random)`; `rank(candidates: list[ModelSpec], route: RoutePolicy, req: RequiredCapabilities, latency: LatencySnapshot) -> list[ModelSpec]` |
| `RoutePlanner` *(new)* | `__init__(matcher, ranker)`; `plan(route, registry, req, health, latency, policy_version, max_fallbacks) -> RouteDecision`; raises `NoEligibleModelError` |

Pipeline (FR-28): resolve route candidates (`route.chain`, or all routable for non-FALLBACK routes with empty chain) → drop DISABLED → `CapabilityMatcher.filter` (empty → CAPABILITY_MISMATCH 400) → drop `health.open_model_ids` (empty → NO_HEALTHY_CANDIDATE 503) → `rank` → truncate to `1 + max_fallbacks`. Every model in the chain passed the same `RequiredCapabilities` (FR-34).

| Strategy | Ranking (input is pre-sorted by `model_id`; all sorts stable) |
|---|---|
| FALLBACK | keep `route.chain` order |
| CHEAPEST_CAPABLE | sort key `(estimate_cost(spec, in_est, max_tokens or spec.max_output_tokens), model_id)` |
| LOWEST_LATENCY | key `(0, ewma)` for known, `(1, 0.0)` for unknown (unknown go last), then `model_id` |
| WEIGHTED | primary drawn with `rng.random()·Σw` over cumulative weights in `model_id` order (weight 0 → never primary); remaining sorted by `(-weight, model_id)`; the same seeded `rng` gives the same chain; FR-33 test: 10 000 draws with `Random(42)`, chi-square p > 0.001 |

### policy.py
| Type | Fields / signature (defaults per FR-48..58) |
|---|---|
| `TimeoutPolicy` | `connect_ms=2000, first_token_ms=15000, idle_stream_ms=10000` (each > 0) |
| `RetryPolicy` | `initial_backoff_ms=200, max_backoff_ms=2000, jitter: Literal["full"]="full"`; `backoff_ms(retry_index: int, rng: random.Random) -> int` = `rng.uniform(0, min(max, initial·2^retry_index))` |
| `CircuitBreakerPolicy` | `failure_threshold=5, rolling_window_s=30, open_duration_s=15, half_open_probes=2` |
| `RetryBudgetPolicy` | `max_retry_ratio=0.2` (0–1), `window_s=60` |
| `CachePolicy` | `exact: bool=False, ttl_s: int=3600` |
| `ExecutionPolicy` | `deadline_ms=60000, max_attempts=3, max_fallbacks=2, retry, timeouts, circuit_breaker, retry_budget`; validator: `max_fallbacks < max_attempts`, `first_token_ms ≤ deadline_ms` |
| `RoutePolicy` | `route_id: str`, `strategy: RoutingStrategy`, `chain: list[str]`, `weights: dict[str, int] \| None` (WEIGHTED only, keys == chain), `cache: CachePolicy`, `requires: ModelCapabilities \| None` (minimum every chain member must meet), `execution: ExecutionPolicy \| None` (overrides doc default) |
| `PolicyDocument` | `version: int`, `routes: dict[str, RoutePolicy]`, `execution: ExecutionPolicy`, `default_route: str`; `effective_execution(route_id) -> ExecutionPolicy` |
| `Deadline` *(new)* | `expires_at: float` (monotonic s); `remaining_s(now: float) -> float`; `allows_wait(delay_s, now) -> bool` (FR-50/51) |
| `PolicyIssue` *(new)* | `path: str`, `code: str`, `message: str` |
| `PolicyValidator` | `__init__(registry: CapabilityRegistry, matcher: CapabilityMatcher)`; `validate(doc) -> list[PolicyIssue]` sorted by `path` — rules: every chain model exists and is not DISABLED; FALLBACK chain non-empty; WEIGHTED weights match chain and sum > 0; every chain member meets `requires` (if set) and no fallback lacks a capability the primary has; `default_route` exists (FR-94) |

All policy models extend `CanonicalModel` (`extra="forbid"`), so a YAML typo fails validation.

## 6. adapters/base.py

```python
@dataclass(frozen=True)
class AttemptContext:
    attempt_id: str
    request_id: str
    deadline: Deadline            # one per request, shared by all attempts (deadline_ms)
    timeouts: TimeoutPolicy       # connect / first_token / idle_stream
    cancel_event: asyncio.Event   # set by ExecutionService on client disconnect
    clock: Callable[[], float] = time.monotonic

class ProviderAdapter(Protocol):
    provider: ClassVar[ProviderName]
    ALLOWED_EXTENSIONS: ClassVar[frozenset[str]]
    async def complete(self, req: CanonicalRequest, model: ModelSpec, ctx: AttemptContext) -> CanonicalResponse: ...
    def stream(self, req: CanonicalRequest, model: ModelSpec, ctx: AttemptContext) -> AsyncIterator[StreamEvent]: ...

class AdapterRegistry:
    def __init__(self, adapters: Sequence[ProviderAdapter]) -> None: ...   # duplicate provider -> ValueError
    def get(self, provider: ProviderName) -> ProviderAdapter: ...          # missing -> KeyError (fails at wiring)
```

`BaseHttpAdapter` *(new, ABC)* holds shared mechanics (timeouts, cancellation, sequencing, SSE parsing). Subclasses add only mapping hooks: `_build_request(req, model) -> ProviderHttpRequest` *(new: url, headers, json)*, `_parse_response(body, model, ctx) -> CanonicalResponse`, `_parse_chunk(raw: str, state: ChunkState) -> list[UnsequencedEvent]`, `_map_error(status, body, headers) -> GatewayError` (delegates to `ProviderErrorMapper`). Base URLs are `ClassVar` constants (FR-22); the shared `httpx.AsyncClient` is constructor-injected.

| Contract rule | Detail |
|---|---|
| `complete` errors | raises `GatewayError` subclasses only; any other exception is wrapped as `MalformedProviderResponseError` |
| `stream` errors | never raises for provider/transport failures: `StreamStart` (seq 0) once headers are 200, then deltas, then exactly one terminal (`StreamEnd` or `StreamError`). Non-200 or connect failure → a single `StreamError` (seq 0). Only `asyncio.CancelledError` propagates |
| Sequence | adapter-owned counter, +1 per event, from 0 |
| First token | `ExecutionService` holds back `StreamStart` until the first `ContentDelta`/`ToolCallDelta`. A `StreamError` before that is retryable per `classify` + `can_retry()` (FR-42); after it, the error goes to the client as the terminal event (FR-43/44) |

### Cancellation contract (FR-21, FR-40, FR-45)
- The HTTP call runs inside `async with client.stream(...) as resp:`. Every read goes through `_read_next(aiter, timeout_s)`, which races `anext()` against `ctx.cancel_event.wait()` (`asyncio.wait(FIRST_COMPLETED)`).
- `cancel_event` set → pending read cancelled, `async with` exits (`resp.aclose()` closes the TCP connection), adapter yields `StreamError(error_class=CANCELLED, usage=estimated so far)`.
- `task.cancel()` or consumer `aclose()` → `CancelledError`/`GeneratorExit` unwinds through `finally`, which closes the response; `CancelledError` is re-raised.
- Contract test: fake_provider `/admin/stats.closed_connections` rises within 200 ms of `cancel_event.set()`.

### Timeouts (FR-46, FR-48)
| Timeout | Enforced where | Expiry |
|---|---|---|
| `connect_ms` | `httpx.Timeout(connect=min(connect, remaining), pool=same, read=None)` per request | `ProviderTimeoutError(CONNECT)` / `StreamError(TIMEOUT)` |
| `first_token_ms` | adapter `_read_next` for the first data-bearing chunk (stream) or the response headers (complete); bound `min(first_token_ms, remaining)` | `FIRST_TOKEN` |
| `idle_stream_ms` | adapter `_read_next` for every later chunk; bound `min(idle_stream_ms, remaining)` | `IDLE_STREAM` |
| `deadline_ms` | `ExecutionService` creates one `Deadline` at ROUTED; adapter clamps every wait (and the `complete` body read) to `remaining_s`; `ExecutionService` skips any retry/backoff that would pass it | `DEADLINE` (FAIL) |

### Usage reporting
| Provider | Source | Canonical mapping |
|---|---|---|
| OpenAI | stream: forces `stream_options.include_usage=true`, last chunk `usage`; complete: `usage` | `prompt_tokens→input`, `completion_tokens→output`, `prompt_tokens_details.cached_tokens→cached_input`, `completion_tokens_details.reasoning_tokens→reasoning` |
| Anthropic | `message_start.message.usage` + `message_delta.usage` (cumulative output) | `input = input_tokens + cache_read_input_tokens + cache_creation_input_tokens`, `cached_input = cache_read_input_tokens`, `output = output_tokens`, `reasoning = 0` |
| Gemini | `usageMetadata` on chunks, last wins | `promptTokenCount→input`, `cachedContentTokenCount→cached_input`, `candidatesTokenCount + thoughtsTokenCount→output`, `thoughtsTokenCount→reasoning` |

One `UsageEvent` just before `StreamEnd`. No provider usage → `UsageEvent(usage_source=ESTIMATED)` from `TokenEstimator` (FR-79). `StreamError.usage` carries tokens used so far (FR-41).

### Malformed chunk handling (FR-19, FR-47)
Each SSE `data:` line → `json.loads` → provider chunk model (provider wire models use `extra="ignore"` so new provider fields do not break parsing; only client-facing canonical models forbid extras). `JSONDecodeError`, `ValidationError`, an impossible state (delta for an unknown tool index, a second `message_start`) or end of stream without the provider terminal marker (`[DONE]`, `message_stop`, `finishReason`) → close the response, yield `StreamError(error_class=MALFORMED_RESPONSE, message="<provider> chunk N invalid: <field path>")`. Raw chunks are never logged.

### Provider mapping — key differences only
| Aspect | OpenAI | Anthropic | Gemini |
|---|---|---|---|
| Auth | `Authorization: Bearer` | `x-api-key` + `anthropic-version` | `x-goog-api-key` |
| System prompt | inline `system`/`developer` | joined into top-level `system`; must lead, else 400 | `systemInstruction` |
| Tool definition | as-is | `{name, description, input_schema}` | `tools[0].functionDeclarations[]`; unsupported JSON Schema keywords → 400 |
| `tool_choice` | as-is | auto→`auto`, required→`any`, named→`tool`, none→`none`; `parallel_tool_calls=false` → `disable_parallel_tool_use` | `functionCallingConfig.mode` AUTO/ANY/NONE + `allowedFunctionNames` |
| Tool-call IDs | provider `id` | `tool_use.id` | none on wire → synthesized `call_{attempt_id}_{index}`; results mapped back by order + name |
| Tool results | `role=tool` + `tool_call_id` | `user` message, `tool_result` block (`tool_use_id`) | `functionResponse` part by name |
| Arg streaming | `arguments` string deltas | `input_json_delta.partial_json` | whole `args` in one chunk → one `ToolCallDelta` |
| `max_tokens` | optional | required → defaults to `model.max_output_tokens` | `generationConfig.maxOutputTokens` |
| `stop` | `stop` | `stop_sequences` | `stopSequences` (>5 → 400) |
| `json_schema` | native `response_format` | forced tool `switchyard_json`, unwrapped into content | `responseMimeType=application/json` + `responseSchema` |
| Finish reason | stop / length / tool_calls / content_filter | end_turn, stop_sequence→STOP; max_tokens→LENGTH; tool_use→TOOL_CALLS; refusal→CONTENT_FILTER | STOP (TOOL_CALLS if function parts); MAX_TOKENS→LENGTH; SAFETY, RECITATION→CONTENT_FILTER |
| Overload / retry hint | 429/5xx, `retry-after` | 529 `overloaded_error`, `retry-after` | 429 RESOURCE_EXHAUSTED, 503 UNAVAILABLE, `RetryInfo.retryDelay` |
| Provider request ID | `x-request-id` header | `request-id` header | `responseId` field |

## 7. fake_provider (`fake_provider.app:create_app`)

Standalone FastAPI app, OpenAI wire format: `POST /v1/chat/completions` (stream / non-stream, optional tool call), `GET /v1/models`, `GET | POST | PUT | DELETE /admin/config` (alias `/_knobs`), `GET /admin/stats` (`requests`, `open_connections`, `closed_connections`, `by_status`).

`FakeKnobs` (pydantic, `extra="forbid"`, frozen; unknown or invalid knob → OpenAI 400). Precedence (highest first): header `X-Fake-<Knob>` (case-insensitive, `-` → `_`) > query `fake_<knob>` > global `/admin/config` | `/_knobs` > defaults. A global patch may carry `match_model: str` (exact match): its knobs form a rule layered over the unscoped globals only for requests with that `model`, so the primary fails while the fallback on the same fake stays healthy (NFR-03). Rules are kept in insertion order and at most one matches; a repeat patch for the same model merges into its rule; `DELETE` clears globals and rules. Every global patch restarts the seeded RNG streams.

| Knob | Type = default | Effect |
|---|---|---|
| `latency_ms` | int ≥ 0 = 0 | delay before response headers |
| `ttft_ms` | int ≥ 0 = 0 | delay between headers and first chunk |
| `inter_chunk_ms` | int ≥ 0 = 0 | delay between chunks |
| `error_rate` | float 0–1 = 0 | chance of an error response (seeded RNG roll) |
| `error_status` | int = 503 | injected status (one of 400, 401, 429, 500, 503, 529); OpenAI error body; 529 uses an `overloaded_error` body |
| `error_codes` | list[int] \| None = None | if set, wins over `error_status`: status picked with `rng.choice` from the same seeded stream; header/query form `429,503` |
| `retry_after_s` | float ≥ 0 \| None = None | `Retry-After` on 429/503 as integer delay-seconds, `ceil(retry_after_s)` (RFC 9110); a 429 without it sends `1`; never on other statuses |
| `hang` | `none \| before_headers \| before_first_chunk \| mid_stream` = none (bool shorthand `true` = `before_headers`) | stalls until the client disconnects or `hang_max_s` elapses (TTFT / idle / deadline tests); a pre-header hang then returns 504 |
| `hang_max_s` | float (0, 3600] = 300 | upper bound on any hang |
| `drop_after_chunks` | int ≥ 0 \| None = None | closes the stream after N chunks without `[DONE]` |
| `malformed_at_chunk` | int ≥ 0 \| None = None | sends invalid JSON as chunk N (0-based) |
| `usage` | bool = true | include `usage` (non-stream) / final usage chunk (stream) |
| `chunks`, `text` | int 1–1000 = 8, str | response shape |
| `tool_call` | bool = false | emit a tool call, arguments split across chunks |
| `seed` | int = 0 | seeds the RNG so error injection is reproducible |


---

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


---

# Part 03 — Persistence, Redis and Config

Names follow `00_contract.md`. New names added here: `TenantScopedRepository`, `DbTransaction`, `TenantId`, `*Record` dataclasses, `RateLimiter`, `ConcurrencyLimiter`, `CacheKeyBuilder`, `CacheEligibility`.
Postgres = money and tenant truth (FR-74, NFR-15). Redis = coordination only (limits, breaker, cache). Money is `NUMERIC(18,8)` in SQL and `Decimal` in Python. Timestamps are `TIMESTAMPTZ` (UTC).

## 1. Postgres schema

### Global rules
| Rule | How |
|---|---|
| Tenant composite keys | Every child table has `UNIQUE (tenant_id, id)`. Every FK to a tenant-owned row is composite `(tenant_id, x_id) → parent (tenant_id, id)`, so a row can never point to another tenant's row (FR-67) |
| IDs | `UUID DEFAULT gen_random_uuid()` (PG ≥ 13), except append-only tables use `BIGINT GENERATED ALWAYS AS IDENTITY` |
| Enums | `TEXT` + `CHECK (col IN (...))` (simpler Alembic diffs than PG `ENUM`) |
| Roles | `switchyard_owner` owns schema and runs migrations. `switchyard_app` is the runtime role: `SELECT, INSERT, UPDATE, DELETE` on mutable tables; only `SELECT, INSERT` on `ledger` and `audit_events` |
| Append-only | `REVOKE UPDATE, DELETE, TRUNCATE ON ledger, audit_events FROM switchyard_app` **and** trigger `sy_forbid_mutation()` (`BEFORE UPDATE OR DELETE ... FOR EACH ROW` and `BEFORE TRUNCATE ... FOR EACH STATEMENT` → `RAISE EXCEPTION 'append-only table %', TG_TABLE_NAME`). Two layers: the grant stops the app, the trigger stops the owner role by mistake |

### tenants
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| slug | TEXT NOT NULL UNIQUE | `^[a-z0-9-]{3,63}$` CHECK |
| name | TEXT NOT NULL | |
| status | TEXT NOT NULL DEFAULT 'active' | `active, suspended` |
| rpm_limit / tpm_limit / concurrency_limit | INTEGER NOT NULL | CHECK > 0; defaults from `Settings` |
| log_unredacted | BOOLEAN NOT NULL DEFAULT false | FR-71 opt-in |
| created_at / updated_at | TIMESTAMPTZ NOT NULL DEFAULT now() | |

### api_keys
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | `UNIQUE (tenant_id, id)` |
| tenant_id | UUID NOT NULL | FK → tenants(id) |
| key_prefix | TEXT NOT NULL | non-secret, e.g. `sy_` + 8 chars; display only |
| key_hash | BYTEA NOT NULL UNIQUE | HMAC-SHA-256 (32 bytes, CHECK `octet_length = 32`) |
| hmac_key_id | TEXT NOT NULL | which server HMAC key made the hash (HMAC key rotation) |
| name | TEXT NOT NULL | |
| status | TEXT NOT NULL DEFAULT 'active' | `active, revoked` (expiry is computed from `expires_at`) |
| expires_at | TIMESTAMPTZ NULL | |
| revoked_at | TIMESTAMPTZ NULL | CHECK `(status='revoked') = (revoked_at IS NOT NULL)` |
| rotated_from_id | UUID NULL | composite FK `(tenant_id, rotated_from_id)` → api_keys |
| created_at | TIMESTAMPTZ NOT NULL | |
Indexes: `UNIQUE (key_hash)` (auth lookup), `(tenant_id, status)`.

### policies (versioned, one active per tenant)
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | `UNIQUE (tenant_id, id)` |
| tenant_id | UUID NOT NULL | FK → tenants |
| version | INTEGER NOT NULL | `UNIQUE (tenant_id, version)`; monotonic per tenant |
| document | JSONB NOT NULL | validated `PolicyDocument` (routes + execution) |
| source_sha256 | BYTEA NOT NULL | hash of the applied YAML (audit, no-op apply detection) |
| is_active | BOOLEAN NOT NULL DEFAULT false | |
| created_by | TEXT NOT NULL | CLI actor |
| created_at / activated_at | TIMESTAMPTZ | |
Indexes: `UNIQUE (tenant_id) WHERE is_active` (partial — one active per tenant), `(tenant_id, version DESC)`. Rows are immutable after insert except `is_active`/`activated_at` (enforced by repository; only invalid policies are never inserted, FR-94).

### budgets
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | `UNIQUE (tenant_id, id)` |
| tenant_id | UUID NOT NULL | FK → tenants |
| period_kind | TEXT NOT NULL | `monthly, daily` (OQ-02) |
| period_key | TEXT NOT NULL | `2026-11` or `2026-11-04` (UTC) |
| enforcement | TEXT NOT NULL | `hard, soft` |
| limit_usd / spent_usd / reserved_usd | NUMERIC(18,8) NOT NULL | spent/reserved DEFAULT 0, CHECK ≥ 0 |
| soft_alert_ratio | NUMERIC(5,4) NOT NULL DEFAULT 0.8 | OQ-07 |
| updated_at | TIMESTAMPTZ NOT NULL | |
Indexes: `UNIQUE (tenant_id, period_kind, period_key)`. No CHECK `spent ≤ limit`: settlement of real usage must never fail; the reservation guard is the control (see §2).

### reservations
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | `UNIQUE (tenant_id, id)` |
| tenant_id | UUID NOT NULL | |
| budget_id | UUID NOT NULL | composite FK `(tenant_id, budget_id)` → budgets |
| request_id | UUID NOT NULL | `UNIQUE (tenant_id, request_id, budget_id)` — one row per budget hit |
| amount_usd | NUMERIC(18,8) NOT NULL | CHECK > 0 |
| actual_usd | NUMERIC(18,8) NULL | set on commit |
| state | TEXT NOT NULL DEFAULT 'reserved' | `reserved, committed, released, expired` |
| policy_version | INTEGER NOT NULL | copied to expiry ledger marker |
| expires_at | TIMESTAMPTZ NOT NULL | `now() + deadline_ms + 5 min` (OQ-03) |
| created_at / finalized_at | TIMESTAMPTZ | CHECK `(state='reserved') = (finalized_at IS NULL)` |
Indexes: `(expires_at) WHERE state = 'reserved'` (expiry worker), `(tenant_id, request_id)`.
Transitions only `reserved → committed | released | expired` (FR-77): every UPDATE has `AND state = 'reserved'`; trigger `sy_reservation_transition()` rejects any UPDATE where `OLD.state <> 'reserved'`.

### ledger (append-only)
| Column | Type | Notes |
|---|---|---|
| id | BIGINT IDENTITY PK | `UNIQUE (tenant_id, id)` |
| tenant_id | UUID NOT NULL | FK → tenants |
| request_id | UUID NOT NULL | settlement idempotency key (FR-78), unique per `entry_kind` |
| entry_kind | TEXT NOT NULL | `settlement, expired, late_settlement` |
| attempt_ids | UUID[] NOT NULL DEFAULT '{}' | FR-81, all billable attempts |
| route_id | TEXT NULL | |
| provider / model_id | TEXT NULL | CHECK NOT NULL when `entry_kind='settlement' AND cache_status <> 'hit'` |
| input_tokens / output_tokens / cached_input_tokens / reasoning_tokens | INTEGER NOT NULL DEFAULT 0 | summed over attempts |
| cost_usd | NUMERIC(18,8) NOT NULL | CHECK ≥ 0 |
| reserved_usd | NUMERIC(18,8) NOT NULL | total released by this entry |
| pricing_version | TEXT NULL | NOT NULL when cost_usd > 0 |
| policy_version | INTEGER NOT NULL | FR-96 |
| usage_source | TEXT NOT NULL | `reported, estimated` (`UsageSource`) |
| cache_status | TEXT NOT NULL DEFAULT 'bypass' | `hit, miss, bypass` |
| terminal_state | TEXT NOT NULL | `COMPLETED, FAILED, CANCELLED, REJECTED` or `EXPIRED` |
| trace_id | TEXT NULL | NFR-16 correlation |
| created_at | TIMESTAMPTZ NOT NULL DEFAULT now() | |
Indexes: `UNIQUE (request_id, entry_kind)`, CHECK `entry_kind <> 'settlement'` OR no `expired` row exists (enforced in the settle tx, not a constraint), `(tenant_id, created_at DESC)`, `(tenant_id, entry_kind) WHERE entry_kind='expired'`. Append-only per global rules.

### idempotency_keys
| Column | Type | Notes |
|---|---|---|
| tenant_id | UUID NOT NULL | PK part 1; FK → tenants |
| key | TEXT NOT NULL | PK part 2; CHECK `length BETWEEN 1 AND 255` |
| request_hash | BYTEA NOT NULL | SHA-256 of canonical body (same canonical JSON as §7, all fields) |
| request_id | UUID NOT NULL | original request |
| status | TEXT NOT NULL | `in_progress, completed, failed` |
| response_ref | UUID NULL | = ledger.request_id of the original (replay audit) |
| response_body | JSONB NULL | stored `CanonicalResponse` for replay; NULL while in progress |
| http_status | SMALLINT NULL | replayed status |
| lease_expires_at | TIMESTAMPTZ NOT NULL | `now() + deadline_ms + 30 s`; stale `in_progress` past lease may be taken over |
| expires_at | TIMESTAMPTZ NOT NULL | `created_at + 24 h` (OQ-03) |
| created_at / updated_at | TIMESTAMPTZ | |
PK `(tenant_id, key)` (scoped by tenant, FR-83). Indexes: `(expires_at)` (cleanup worker). Retryable failures (5xx class) are stored `failed` and **not** replayed: next call with same key re-executes; non-retryable 4xx results are replayed.

### audit_events (append-only)
| Column | Type | Notes |
|---|---|---|
| id | BIGINT IDENTITY PK | |
| tenant_id | UUID NULL | NULL only for `auth_failed` with an unknown key; FK → tenants when set |
| event_type | TEXT NOT NULL | `key_created, key_rotated, key_revoked, key_expired_used, auth_failed, policy_applied, policy_activated, policy_rejected, reservation_expired, late_settlement_applied` |
| api_key_id | UUID NULL | composite FK `(tenant_id, api_key_id)` → api_keys (MATCH SIMPLE) |
| key_prefix | TEXT NULL | never the secret |
| actor | TEXT NOT NULL | `api`, `cli:<user>`, `worker:<name>` |
| request_id | UUID NULL | |
| details | JSONB NOT NULL DEFAULT '{}' | redacted by `Redactor` before insert |
| created_at | TIMESTAMPTZ NOT NULL DEFAULT now() | |
Indexes: `(tenant_id, created_at DESC)`, `(event_type, created_at DESC)`.

## 2. Money SQL (all `READ COMMITTED`; row locks give the atomicity)

### Reserve (BudgetRepository.reserve, one tx) — FR-75/76
```sql
-- :keys = current period keys for the tenant, :n = number of budget rows those keys match (list_current)
UPDATE budgets SET reserved_usd = reserved_usd + :amt, updated_at = now()
WHERE tenant_id = :t AND period_key = ANY(:keys)
  AND (enforcement = 'soft' OR spent_usd + reserved_usd + :amt <= limit_usd)
RETURNING id, enforcement, limit_usd, spent_usd, reserved_usd;
-- rows < :n → ROLLBACK → BudgetExceededError (402). This one conditional UPDATE is the overspend guard (NFR-05).
INSERT INTO reservations (tenant_id, budget_id, request_id, amount_usd, policy_version, expires_at)
SELECT :t, id, :r, :amt, :pv, now() + :ttl FROM unnest(:returned_ids) AS id;
COMMIT;
```
Soft rows with `(spent+reserved)/limit ≥ soft_alert_ratio` come back flagged → `BudgetService` emits the alert (FR-80). `:amt` = `CostEstimator.estimate_reservation` = `input_tokens_est × in_price × max_attempts + max_tokens × out_price` (retries happen only before the first token, so output is reserved once), taking the highest-priced candidate model in the route (see 02 §6). A tenant with no budget rows gets no reservation, but the ledger row is still written.

### Settle (LedgerRepository.append + BudgetRepository.settle in one `DbTransaction`) — FR-78/79
```sql
BEGIN;
SELECT id FROM reservations WHERE tenant_id = :t AND request_id = :r FOR UPDATE;  -- serialises settle vs expiry
INSERT INTO ledger (tenant_id, request_id, entry_kind, attempt_ids, route_id, provider, model_id,
  input_tokens, output_tokens, cached_input_tokens, reasoning_tokens, cost_usd, reserved_usd,
  pricing_version, policy_version, usage_source, cache_status, terminal_state, trace_id)
VALUES (:t, :r, 'settlement', ...)
ON CONFLICT (request_id, entry_kind) DO NOTHING RETURNING id;
-- (guarded: only attempted when the locked reservation is still 'reserved' or there is no reservation)
-- no row → already settled → COMMIT, SettlementResult(applied=False)
UPDATE budgets b SET spent_usd = b.spent_usd + :cost, reserved_usd = b.reserved_usd - r.amount_usd, updated_at = now()
FROM reservations r
WHERE r.tenant_id = :t AND r.request_id = :r AND r.state = 'reserved'
  AND b.tenant_id = r.tenant_id AND b.id = r.budget_id;
UPDATE reservations SET state = CASE WHEN :cost > 0 THEN 'committed' ELSE 'released' END,
  actual_usd = :cost, finalized_at = now()
WHERE tenant_id = :t AND request_id = :r AND state = 'reserved';
COMMIT;
```
`:cost` is added to every budget the request reserved against (each period counts the spend). A cache hit, or a request rejected before any attempt, settles with cost 0 → `released`. **Late settle after expiry (real usage is never dropped):** if the locked reservation is already `expired`, the tx instead inserts `entry_kind='late_settlement'` with the real cost (`ON CONFLICT (request_id, entry_kind) DO NOTHING`, so it stays idempotent) and does `spent_usd += :cost` on each reserved budget (no `reserved_usd` change; expiry already released it). This may push `spent` over `limit` — allowed, because there is no CHECK, and flagged with a `late_settlement_applied` audit event + `switchyard_late_settlements_total` metric + an alert. TTL = deadline + 5 min, so this only happens after a crash or stall. Ledger reads for a request: `late_settlement` supersedes `expired`.

### Expire (BudgetRepository.expire_due — WORKER-ONLY, one statement) — FR-82
```sql
WITH due AS (
  SELECT id FROM reservations WHERE state = 'reserved' AND expires_at < now()
  ORDER BY expires_at, id LIMIT :batch FOR UPDATE SKIP LOCKED),
exp AS (
  UPDATE reservations r SET state = 'expired', finalized_at = now() FROM due
  WHERE r.id = due.id AND r.state = 'reserved'
  RETURNING r.tenant_id, r.budget_id, r.request_id, r.amount_usd, r.policy_version),
rel AS (
  UPDATE budgets b SET reserved_usd = b.reserved_usd - s.amt, updated_at = now()
  FROM (SELECT tenant_id, budget_id, sum(amount_usd) AS amt FROM exp GROUP BY 1, 2) s
  WHERE b.tenant_id = s.tenant_id AND b.id = s.budget_id)
INSERT INTO ledger (tenant_id, request_id, entry_kind, cost_usd, reserved_usd, policy_version,
                    usage_source, terminal_state)
SELECT tenant_id, request_id, 'expired', 0, sum(amount_usd), max(policy_version), 'estimated', 'EXPIRED'
FROM exp GROUP BY tenant_id, request_id
ON CONFLICT (request_id) DO NOTHING
RETURNING tenant_id, request_id, reserved_usd;
```
The worker loops until 0 rows are returned. It emits `switchyard_reservations_expired_total` and one `reservation_expired` audit event per row.

### Idempotency acquire (IdempotencyRepository.acquire)
`INSERT ... (status='in_progress') ON CONFLICT (tenant_id, key) DO NOTHING RETURNING request_id` → inserted ⇒ `ACQUIRED`. Otherwise `SELECT ... FOR UPDATE`: hash differs ⇒ `MISMATCH` (422); `completed` or non-retryable `failed` ⇒ `REPLAY`; `in_progress` with a live lease ⇒ `IN_PROGRESS` (409); lease past, or retryable `failed` ⇒ `UPDATE` to the new request_id + lease ⇒ `ACQUIRED`.

## 3. Repositories (`switchyard.infrastructure.repositories`)
All methods are `async`. `TenantId = NewType("TenantId", UUID)`. Records are frozen `@dataclass(slots=True)` in `repositories/records.py`. Every SQL statement filters `tenant_id = :t` unless marked otherwise.
`Database.transaction() -> AsyncContextManager[DbTransaction]` wraps `AsyncSession.begin()`. Methods that take `tx` join the caller's tx; the others open their own.

| Class | Method signature | Notes |
|---|---|---|
| `TenantScopedRepository` (base) | `__init__(self, database: Database) -> None`; `_require_tenant(tenant_id: TenantId) -> None` | raises `ValueError` on nil UUID; base of all below |
| `TenantRepository` | `get(tenant_id: TenantId) -> TenantRecord \| None` | |
| | `get_limits(tenant_id: TenantId) -> TenantLimits` | rpm/tpm/concurrency/log_unredacted |
| | `create(slug: str, name: str, limits: TenantLimits) -> TenantRecord` | **ADMIN/CLI-ONLY** (no tenant yet) |
| `ApiKeyRepository` | `find_by_hash(key_hash: bytes) -> ApiKeyRecord \| None` | **AUTH-BOOTSTRAP-ONLY**: no tenant_id (this call resolves it) |
| | `create(tenant_id: TenantId, record: NewApiKey, tx: DbTransaction) -> ApiKeyRecord` | |
| | `rotate(tenant_id: TenantId, old_key_id: UUID, new: NewApiKey, tx: DbTransaction) -> ApiKeyRecord` | sets old `expires_at = now() + grace` |
| | `revoke(tenant_id: TenantId, key_id: UUID, at: datetime, tx: DbTransaction) -> bool` | |
| | `list(tenant_id: TenantId) -> list[ApiKeyRecord]` | sorted by created_at, id |
| `PolicyRepository` | `get_active(tenant_id: TenantId) -> PolicyRecord \| None` | LKG source |
| | `get_version(tenant_id: TenantId, version: int) -> PolicyRecord \| None` | |
| | `insert_and_activate(tenant_id: TenantId, document: PolicyDocument, source_sha256: bytes, actor: str) -> PolicyRecord` | one tx: lock tenant row `FOR UPDATE`, version = max+1, flip `is_active` |
| | `activate(tenant_id: TenantId, version: int, actor: str) -> PolicyRecord` | rollback to an older version |
| | `list_versions(tenant_id: TenantId, limit: int = 20) -> list[PolicyRecord]` | version DESC, limit ≤ 100 |
| `BudgetRepository` | `list_current(tenant_id: TenantId, at: datetime) -> list[BudgetRecord]` | |
| | `reserve(tenant_id: TenantId, request_id: UUID, amount: Decimal, period_keys: list[str], expected_rows: int, policy_version: int, ttl: timedelta) -> ReservationOutcome` | `ReservationOutcome(accepted, budgets, soft_alerts)` |
| | `settle(tenant_id: TenantId, request_id: UUID, cost: Decimal, tx: DbTransaction) -> SettledReservations` | budget + reservation updates from §2 |
| | `upsert_budget(tenant_id: TenantId, spec: BudgetSpec) -> BudgetRecord` | ADMIN/CLI |
| | `expire_due(now: datetime, batch: int) -> list[ExpiredReservation]` | **WORKER-ONLY**, cross-tenant (`ReservationExpiryWorker`) |
| `LedgerRepository` | `append(tenant_id: TenantId, entry: LedgerEntry, tx: DbTransaction) -> bool` | `False` = conflict (already settled) |
| | `get(tenant_id: TenantId, request_id: UUID) -> LedgerEntry \| None` | |
| | `list_recent(tenant_id: TenantId, since: datetime, limit: int = 100) -> list[LedgerEntry]` | created_at DESC, id DESC |
| `IdempotencyRepository` | `acquire(tenant_id: TenantId, key: str, request_hash: bytes, request_id: UUID, lease: timedelta, ttl: timedelta) -> IdempotencyAcquireResult` | `(outcome: IdempotencyOutcome, record)`; outcomes `ACQUIRED, REPLAY, IN_PROGRESS, MISMATCH` |
| | `complete(tenant_id: TenantId, key: str, request_id: UUID, response: CanonicalResponse, http_status: int) -> None` | guarded by `WHERE request_id = :r` |
| | `fail(tenant_id: TenantId, key: str, request_id: UUID, retryable: bool, http_status: int) -> None` | |
| | `delete_expired(now: datetime, batch: int) -> int` | **WORKER-ONLY** (`IdempotencyCleanupWorker`) |
| `AuditRepository` | `record(tenant_id: TenantId \| None, event: AuditEvent, tx: DbTransaction \| None = None) -> None` | `None` only for unknown-key `auth_failed` |
| | `list(tenant_id: TenantId, since: datetime, limit: int = 100) -> list[AuditEvent]` | |

`BudgetService.settle()` owns the tx: `async with db.transaction() as tx:` → `applied = await ledger.append(t, e, tx)` → if `applied`: `await budgets.settle(t, r, cost, tx)`.

## 4. Alembic
| Item | Choice |
|---|---|
| Layout | `alembic.ini` at repo root; `src/switchyard/infrastructure/db/migrations/{env.py,script.py.mako,versions/}`; async `env.py`, URL from `Settings.database_url`, `target_metadata = switchyard.infrastructure.db.metadata` |
| File name | `versions/NNNN_<snake_slug>.py`, e.g. `0004_budget_ledger.py`; `revision = "NNNN"` (pre-assigned, not random hex) |
| History | Strictly linear. CI checks `alembic heads` = 1, then runs `upgrade head` → `downgrade base` → `upgrade head` on a clean PG |
| Raw SQL | Triggers, grants and partial indexes via `op.execute()`; every migration has a working `downgrade()` |

| Rev | Branch (milestone) | Adds | down_revision |
|---|---|---|---|
| 0001 | feat/persistence-foundation (M3) | roles + grants, `sy_forbid_mutation()`, `tenants` | None |
| 0002 | feat/policy-versioning (M3) | `policies` + partial unique index | 0001 |
| 0003 | feat/tenant-auth (M5) | `api_keys`, `audit_events` + append-only trigger/revoke | 0002 |
| 0004 | feat/budget-ledger (M6) | `budgets`, `reservations` (+ transition trigger), `ledger` (+ append-only) | 0003 |
| 0005 | feat/idempotency-keys (M6) | `idempotency_keys` | 0003 in its worktree; rewritten to **0004** at the explicit group-O merge (both are group O; keeps history linear) |

## 5. Redis (`RedisClient`; scripts loaded with `SCRIPT LOAD`, called by `EVALSHA`, reload on `NOSCRIPT`)
`{...}` in key names is a Redis Cluster hash tag: all keys of one tenant (or one model) share a slot, so multi-key Lua stays legal on ElastiCache cluster mode.

| Key | Type | Fields / members | TTL | Owner |
|---|---|---|---|---|
| `sy:{tenant}:rl:rpm` | HASH | `tokens`, `ts_ms` | `PEXPIRE` 2 × 60 s, refreshed on every call | `RateLimiter` (`AdmissionService`) |
| `sy:{tenant}:rl:tpm` | HASH | `tokens`, `ts_ms` | 2 × 60 s, refreshed | `RateLimiter` |
| `sy:{tenant}:rl:conc` | ZSET | member `attempt lease id`, score `lease_expiry_ms` | `deadline_ms` + 60 s, refreshed on acquire | `ConcurrencyLimiter` |
| `sy:breaker:{model}` | HASH | `state` (closed/open/half_open), `opened_at_ms`, `probes_in_flight` | 1 h, refreshed on write | `CircuitBreaker` |
| `sy:breaker:{model}:fail` | ZSET | member `attempt_id`, score `ts_ms` | `rolling_window_s` × 2 | `CircuitBreaker` (rolling failure count) |
| `sy:{tenant}:cache:{policy_version}:{sha256}` | STRING | JSON `{"v":1,"response":CanonicalResponse,"stored_at":...}` | route `cache.ttl_s` (default 3600, OQ-06) | `CacheService` |
Time comes from `redis.call('TIME')` inside scripts, not from the replica clock, so 3 replicas agree (NFR-09 ±5%). TPM debits `input_est + max_tokens` at admission and credits back `estimate − actual` at settle (negative cost, capped at capacity).

**Token bucket** (`KEYS[1]` = rpm or tpm key; `ARGV` = capacity, refill_per_s, cost):
```
now_ms = TIME(); b = HMGET(KEYS[1], tokens, ts_ms)
tokens = b.tokens or capacity; ts = b.ts_ms or now_ms
tokens = min(capacity, tokens + (now_ms - ts) * refill_per_s / 1000)
if cost <= tokens: tokens -= cost; allowed = 1; retry_ms = 0
else: allowed = 0; retry_ms = ceil((cost - tokens) * 1000 / refill_per_s)
HSET(KEYS[1], tokens, tokens, ts_ms, now_ms); PEXPIRE(KEYS[1], 2 * ceil(capacity / refill_per_s) * 1000)
return {allowed, floor(tokens), retry_ms}       -- allowed=0 → RateLimitedError(retry_after_s = ceil(retry_ms/1000))
```
RPM and TPM run in one script call (`KEYS[1..2]`): both are checked before either is debited, so a TPM denial does not burn RPM.

**Concurrency semaphore** (`KEYS[1]` = conc key; `ARGV` = limit, lease_id, lease_ms):
```
now_ms = TIME(); ZREMRANGEBYSCORE(KEYS[1], -inf, now_ms)            -- drop leases of crashed replicas
if ZCARD(KEYS[1]) < limit: ZADD(KEYS[1], now_ms + lease_ms, lease_id); PEXPIRE(KEYS[1], lease_ms + 60000); return {1, 0}
oldest = ZRANGE(KEYS[1], 0, 0, WITHSCORES); return {0, oldest.score - now_ms}
release: ZREM(KEYS[1], lease_id)     -- in `finally` of the request; lease_ms = deadline_ms + 5 s
```

**Redis loss** (NFR-15, `failure-modes.md`): limits, breaker state and cache are lost; nothing else.
| Lost | Behaviour while Redis is down / after it returns |
|---|---|
| RPM/TPM/concurrency counters | Fail-open with `switchyard_redis_degraded` metric + alert; Postgres budget reservation still caps money. Buckets restart full |
| Breaker state | Each replica falls back to a process-local `CircuitBreaker` (same thresholds); shared state rebuilds from new failures |
| Exact cache | Every lookup = `miss` (or `bypass` on error), never an error (FR-92); entries refill naturally |
| Not lost | Tenants, keys, policies, budgets, reservations, ledger, idempotency, audit (all Postgres) |

## 6. Config shapes (YAML holds no secrets; secrets only via Secrets Manager references)

### `config/models.yaml` → `CapabilityRegistry` (loaded into `ModelSpec`; invalid file fails startup, FR-24)
| Field | Type | Rule |
|---|---|---|
| `registry_version` | str | required, e.g. `2026-11-01` |
| `models.<model_id>` | map key | `^(openai\|anthropic\|google)/[a-z0-9.-]+$`; this is the logical ID routes use |
| `.provider` | `openai \| anthropic \| gemini` | must match an `AdapterRegistry` entry; base URL is fixed in code (FR-22) |
| `.provider_model_id` | str | the ID sent upstream |
| `.capabilities` | `{streaming, tools, parallel_tools, structured_output}: bool` | all four required |
| `.context_window` / `.max_output_tokens` | int > 0 | `max_output_tokens ≤ context_window` |
| `.pricing` | `{input_per_mtok, output_per_mtok, cached_input_per_mtok}` | parsed as `Decimal` from strings, ≥ 0 |
| `.pricing_version` | str (date) | stamped into ledger |
| `.status` | `active \| deprecated \| disabled` | `disabled` never routable (FR-26) |

OQ-01 defaults (prices are placeholders: pin from provider price pages at M2 and set `pricing_version`):
| model_id | provider_model_id | ctx / max_out | in / out / cached per Mtok |
|---|---|---|---|
| `openai/gpt-4o` | `gpt-4o` | 128000 / 16384 | 2.50 / 10.00 / 1.25 |
| `openai/gpt-4o-mini` | `gpt-4o-mini` | 128000 / 16384 | 0.15 / 0.60 / 0.075 |
| `anthropic/claude-sonnet` | latest Sonnet ID (confirm M2) | 200000 / 64000 | 3.00 / 15.00 / 0.30 |
| `anthropic/claude-haiku` | latest Haiku ID (confirm M2) | 200000 / 64000 | 1.00 / 5.00 / 0.10 |
| `google/gemini-pro` | `gemini-2.5-pro` | 1048576 / 65536 | 1.25 / 10.00 / 0.31 |
| `google/gemini-flash` | `gemini-2.5-flash` | 1048576 / 65536 | 0.30 / 2.50 / 0.075 |
All six: `streaming, tools, parallel_tools, structured_output: true`, `status: active`.

### `config/policies/<tenant_slug>.yaml` → `PolicyDocument` (applied by `switchyard policy apply`)
| Path | Type | Default / rule |
|---|---|---|
| `tenant` | str | slug; must exist |
| `default_route` | str | must be a key of `routes` |
| `routes.<route_id>.strategy` | `RoutingStrategy` value | `fallback \| cheapest_capable \| lowest_latency \| weighted` |
| `routes.<route_id>.chain` | list[model_id] | 1–5 items, unique, all in registry, capability-compatible (FR-94) |
| `routes.<route_id>.weights` | map model_id → int ≥ 0 | required iff `weighted`; keys = chain |
| `routes.<route_id>.cache` | `{exact: bool, ttl_s: int}` | `false`, 3600 → `CachePolicy` |
| `routes.<route_id>.execution` | partial `ExecutionPolicy` | optional per-route override, merged over `execution` |
| `execution.deadline_ms / max_attempts / max_fallbacks` | int | 60000 / 3 / 2 |
| `execution.retry` | `{initial_backoff_ms, max_backoff_ms, jitter: full}` | 200 / 2000 → `RetryPolicy` |
| `execution.timeouts` | `{connect_ms, first_token_ms, idle_stream_ms}` | 2000 / 15000 / 10000 → `TimeoutPolicy` |
| `execution.circuit_breaker` | `{failure_threshold, rolling_window_s, open_duration_s, half_open_probes}` | 5 / 30 / 15 / 2 |
| `execution.retry_budget` | `{max_retry_ratio}` | 0.2 → `RetryBudgetPolicy` |
Unknown keys are rejected (`extra="forbid"`). `version` is assigned by Postgres, never written in YAML.

### `Settings` (pydantic-settings, prefix `SWITCHYARD_`, `extra="forbid"`; no `.env` file is read in prod)
| Env var | Type | Default | Notes |
|---|---|---|---|
| `SWITCHYARD_DATABASE_URL` | `SecretStr` (postgresql+asyncpg) | — required | password part may come from Secrets Manager in ECS task def |
| `SWITCHYARD_DB_POOL_SIZE` / `_DB_MAX_OVERFLOW` | int | 20 / 10 | |
| `SWITCHYARD_REDIS_URL` | `SecretStr` (redis/rediss) | — required | |
| `SWITCHYARD_API_KEY_HMAC_SECRET_REF` | str | — required | Secrets Manager ARN/name; value fetched at startup |
| `SWITCHYARD_API_KEY_HMAC_KEY_ID` | str | `k1` | current `hmac_key_id`; older IDs listed in the secret JSON for verification |
| `SWITCHYARD_PROVIDER_SECRET_REFS` | JSON map provider → ARN | `{}` | e.g. `{"openai":"arn:...:switchyard/openai"}` |
| `SWITCHYARD_SECRETS_BACKEND` | `aws \| env` | `aws` | `env` = test/dev only: reads `SWITCHYARD_PROVIDER_KEY_<PROVIDER>` injected outside the repo |
| `SWITCHYARD_AWS_REGION` | str | `us-east-1` | OQ-08 |
| `SWITCHYARD_OTEL_EXPORTER_OTLP_ENDPOINT` | AnyUrl | `http://otel-collector:4317` | |
| `SWITCHYARD_MODELS_PATH` | Path | `config/models.yaml` | |
| `SWITCHYARD_MAX_BODY_BYTES` | int | 1048576 | OQ-05 (1 MiB) → 413 |
| `SWITCHYARD_MAX_MESSAGES` | int | 256 | OQ-05 → 400 |
| `SWITCHYARD_MAX_TOOL_PAYLOAD_BYTES` | int | 65536 | OQ-05 (64 KiB) → 400 |
| `SWITCHYARD_MAX_TOKENS_CAP` | `model` | `model` | `max_tokens` capped at the model's `max_output_tokens` (OQ-05) |
| `SWITCHYARD_DEFAULT_RPM` / `_TPM` / `_CONCURRENCY` | int | 600 / 200000 / 20 | new-tenant defaults |
| `SWITCHYARD_RESERVATION_GRACE_S` | int | 300 | TTL = deadline + grace (OQ-03) |
| `SWITCHYARD_IDEMPOTENCY_TTL_S` | int | 86400 | OQ-03 |
| `SWITCHYARD_CACHE_MAX_VALUE_BYTES` | int | 262144 | larger responses are not stored |
| `SWITCHYARD_WORKER_BATCH` / `_WORKER_INTERVAL_S` | int | 500 / 30 | expiry + cleanup workers |

## 7. Exact cache key (`CacheKeyBuilder`, `switchyard.application.cache_service`; pure, deterministic)
1. Build the ordered **JSON array** (position fixes field order, FR-88): `["sy-cache-v1", tenant_id, route_id, policy_version, model, messages, tools, tool_choice, parallel_tool_calls, temperature, top_p, max_tokens, response_format, stop]`. `model` = the requested `model` field (lookup runs before routing).
2. Normalise: `messages` → each `{role, content, name?, tool_call_id?, tool_calls?}`, absent/None keys dropped; string content stays a string, content parts stay a list in order; whitespace and order are kept. `tools` kept in request order (order can change output). `stop`: string → `[string]`, absent → `[]`. Absent `tool_choice` → `"auto"` only if `tools` non-empty else `null`; absent `top_p`/`max_tokens` → `null`; absent `response_format` → `{"type":"text"}`. Numbers: `temperature`/`top_p` → `float`, so `0` and `0.0` match.
3. Serialise: `json.dumps(arr, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)` → UTF-8 → `sha256().hexdigest()`. Redis key = `sy:{tenant}:cache:{policy_version}:{hex}` (tenant and version also in the key: defence in depth, FR-73).
4. Excluded: `stream`, `stream_options`, `user`, `metadata`, `seed`, `n` (must be 1), `Idempotency-Key`, `request_id`, auth headers.

| Eligibility check | Lookup | Store | Fails → |
|---|---|---|---|
| Route `cache.exact == true` | yes | yes | `bypass` |
| `temperature` present and `== 0` | yes | yes | `bypass` |
| `n` absent or 1; no provider `extensions` set | yes | yes | `bypass` |
| Streaming request: lookup allowed (hit replayed as SSE); store only if the full stream was buffered and ended with `StreamEnd`, no `StreamError` | yes | yes | `bypass` (store skipped) |
| Response has no tool calls and `finish_reason == stop` | — | yes | not stored |
| Serialised value ≤ `SWITCHYARD_CACHE_MAX_VALUE_BYTES` | — | yes | not stored |
| Redis error / timeout (50 ms) | yes | yes | `bypass` on error, never raised |
Header `x-switchyard-cache`: `hit` (served), `miss` (eligible, not found), `bypass` (ineligible or Redis down). A hit settles with cost 0 and a ledger row with `cache_status='hit'` (FR-91).


---

## 8. Test layout

| Dir | Scope | Infra | Covers |
|---|---|---|---|
| `tests/unit/` | domain + services with mocked deps (`MagicMock(spec=...)`); hypothesis property tests for lifecycle | none | lifecycle invariants (FR-37..41), error classification, routing, pricing, cache key, retry/backoff, breaker logic |
| `tests/contract/` | adapters vs recorded provider fixtures (`tests/contract/fixtures/{openai,anthropic,gemini}/*.json|*.sse`) via `respx`; one shared `AdapterContractTests` base run per provider | none | schema normalisation, streaming, tool calls, usage, malformed chunks |
| `tests/integration/` | full app + real Postgres/Redis (testcontainers or compose) + `fake_provider` | PG, Redis | gateway pipeline, budgets (200 concurrent), idempotency (1,000 dup), settlement, workers, policy apply/LKG |
| `tests/chaos/` | fault injection via `fake_provider` knobs + toxiproxy | PG, Redis, toxiproxy | NFR resilience, correlated outage, mid-stream drop, Redis loss, process kill |
| `tests/security/` | negative cross-tenant suite, key revocation/expiry, log redaction | PG, Redis | tenant isolation acceptance gate |
| `loadtest/` | k6 scripts (not pytest) | full stack | overhead p95, TTFT, rate-limit ±5% |

pytest markers: `unit`, `contract`, `integration`, `chaos`, `security`. CI default job runs `unit` + `contract`; integration/security run in a compose-backed job; chaos runs nightly. Layering is enforced by `import-linter` contracts in `pyproject.toml` (checked in CI) mirroring §1.

## 9. Branch file map and collision fixes

Paths relative to repo root; `sy/` = `src/switchyard/`.

### Cross-cutting ownership rules (apply to every parallel group)
1. **`pyproject.toml` / `uv.lock`** — owned by `chore/repo-bootstrap`, which pre-declares **every** v1 runtime + dev dependency (fastapi, uvicorn, pydantic, pydantic-settings, httpx, sqlalchemy[asyncio], asyncpg, alembic, redis, typer, pyyaml, opentelemetry-*; pytest, pytest-asyncio, pytest-cov, hypothesis, respx, testcontainers, ruff, mypy, bandit, pip-audit, import-linter). Later branches avoid editing it; if unavoidable, merge = union of dependency lists, re-run `uv lock`.
2. **All `__init__.py` files** — created empty by `chore/repo-bootstrap`; no branch adds re-exports.
3. **Composition root `sy/application/container.py` (`Container.build(settings)`, see 01 §1)** (builds adapters, services, `GatewayService`) — wiring changes happen only in the *integrating* branch named per group below; parallel branches ship standalone, unit-tested components.
4. **Alembic migrations** — pre-assigned revision numbers (see 03 §4), strictly linear history; when two branches in one group add migrations, the later one's `down_revision` is re-pointed at merge time.
5. **`code_index.md` / `metrics.md`** — merged per CLAUDE.md protocol (section merge / counter sum).

### Per-branch files
| # | Branch | Creates / edits |
|---|---|---|
| 1 | chore/repo-bootstrap | delete `src/ai/`, `src/app/`, `src/__init__.py`, `test/`; create `pyproject.toml`, `uv.lock`, `sy/**/__init__.py` (all packages), `sy/infrastructure/settings.py` (`Settings` skeleton), `tests/{unit,contract,integration,chaos,security}/__init__.py`, `tests/conftest.py`, `.github/workflows/ci.yml` (replace python-checks/unit-test), `.pre-commit-config.yaml`, `.gitignore`, `CLAUDE.md` (test path) |
| 2 | chore/compose-stack | `docker-compose.yml` (pg, redis, otel-collector, gateway, fake-provider service built from `fake_provider/Dockerfile`), `Dockerfile`, `infra/otel/collector.yaml`, `sy/api/app.py` (`create_app` + `/healthz`, `/readyz`), `sy/api/health.py`, `tests/unit/api/test_health.py` |
| 3 | feat/fake-provider | `fake_provider/{__init__,app,knobs,streaming}.py`, `fake_provider/Dockerfile`, `tests/unit/fake_provider/*` |
| 4 | docs/adr-001-002 | `docs/adr/0001-*.md`, `docs/adr/0002-*.md`, `docs/adr/README.md` |
| 5 | feat/canonical-schema | `sy/domain/schema.py`, `sy/domain/errors.py`, `sy/domain/capabilities.py` (**models only**: `ModelCapabilities`, `ModelPricing`, `ModelStatus`, `ModelSpec`), tests |
| 6 | feat/lifecycle-state-machine | `sy/domain/lifecycle.py`, `tests/unit/domain/test_lifecycle*.py`, `docs/adr/0003-*.md` |
| 7 | feat/adapter-openai | `sy/adapters/base.py`, `sy/adapters/openai.py`, `tests/contract/fixtures/openai/*`, `tests/contract/test_openai_adapter.py`, `tests/contract/base.py` (`AdapterContractTests`) |
| 8 | feat/api-surface | `sy/api/{routes,middleware,sse,errors,deps}.py` (see 02 §4), edit `sy/api/app.py` (router include), tests |
| 9 | feat/gateway-service-v1 | `sy/application/{gateway_service,execution_service}.py`, `sy/application/container.py`, edit `sy/api/routes.py` (call service), `tests/integration/test_openai_sdk_e2e.py` |
| 10 | feat/capability-registry | edit `sy/domain/capabilities.py` (add `CapabilityRegistry`, `RequiredCapabilities`, `CapabilityMatcher`), `sy/domain/pricing.py`, `sy/infrastructure/registry_loader.py`, `config/models.yaml`, `tests/unit/test_registry_completeness.py`, `docs/adr/0007-*.md` |
| 11 | feat/adapter-anthropic | `sy/adapters/anthropic.py`, `tests/contract/fixtures/anthropic/*`, `tests/contract/test_anthropic_adapter.py` |
| 12 | feat/adapter-gemini | `sy/adapters/gemini.py`, `tests/contract/fixtures/gemini/*`, `tests/contract/test_gemini_adapter.py` |
| 13 | test/provider-contract-suite | edit `tests/contract/base.py`, edit `sy/application/container.py` (register 3 adapters + registry), `tests/contract/test_all_providers.py` |
| 14 | feat/persistence-foundation | `sy/infrastructure/{db,redis_client}.py`, `sy/infrastructure/repositories/base.py`, `alembic.ini`, `sy/infrastructure/db/migrations/{env.py,versions/0001_tenants.py}`, edit `sy/infrastructure/settings.py`, tests |
| 15 | feat/routing-strategies | `sy/domain/routing.py` (`CandidateRanker`, `RoutePlanner`), `sy/application/routing_service.py` (`RoutingService`), tests |
| 16 | feat/policy-versioning | `sy/domain/policy.py`, `sy/application/policy_service.py`, `sy/infrastructure/repositories/policy_repository.py`, `sy/infrastructure/db/migrations/versions/0002_policies.py`, `sy/cli/{__init__,main,policy}.py`, `config/policies/default.yaml`, edit `sy/application/container.py`, edit `gateway_service.py` (policy resolve + route), `docs/adr/0010-*.md` |
| 17 | feat/retry-and-timeouts | `sy/application/{retry,retry_budget}.py`, edit `sy/adapters/base.py` (timeout helpers), tests, `docs/adr/0004-*.md` |
| 18 | feat/circuit-breaker | `sy/application/circuit_breaker.py`, `sy/infrastructure/lua/breaker.lua` (if used), tests |
| 19 | feat/execution-orchestrator | edit `sy/application/execution_service.py`, edit `sy/application/container.py`, `docs/adr/0005-*.md`, tests |
| 20 | test/chaos-suite | `tests/chaos/*`, compose override `docker-compose.chaos.yml` (toxiproxy), `.github/workflows/nightly.yml` |
| 21 | feat/tenant-auth | `sy/security/{api_keys,tenant_context}.py`, `sy/infrastructure/repositories/{tenant,api_key,audit}_repository.py`, `sy/infrastructure/db/migrations/versions/0003_api_keys_audit.py`, `sy/cli/keys.py`, edit `sy/api/middleware.py` + `sy/api/deps.py`, `docs/adr/0008-*.md` — **integrating branch for group M** (edits `gateway_service.py`, `container.py`) |
| 22 | feat/rate-limits | `sy/application/admission_service.py`, `sy/infrastructure/lua/{token_bucket,concurrency}.lua`, tests (standalone; no wiring) |
| 23 | feat/log-redaction | `sy/security/redaction.py`, `sy/infrastructure/logging.py`, `docs/security.md`, tests (standalone; no wiring) |
| 24 | test/tenant-isolation | wire `AdmissionService` + `Redactor` into `gateway_service.py`/`container.py`, `tests/security/*` |
| 25 | feat/budget-ledger | `sy/application/budget_service.py`, `sy/infrastructure/repositories/{budget,ledger}_repository.py`, `sy/infrastructure/db/migrations/versions/0004_budgets_ledger.py`, `docs/adr/0006-*.md`, tests (standalone) |
| 26 | feat/idempotency-keys | `sy/application/idempotency_service.py`, `sy/infrastructure/repositories/idempotency_repository.py`, `.../versions/0005_idempotency_keys.py` (down_revision 0003 in its worktree; re-pointed to **0004** at the group-O merge, keeping history linear), tests (standalone) |
| 27 | feat/maintenance-workers | `sy/workers/{reservation_expiry,idempotency_cleanup,runner}.py`, **wires budget + idempotency into `gateway_service.py`/`container.py`**, crash test |
| 28 | feat/exact-cache | `sy/application/cache_service.py`, edit `gateway_service.py`, `container.py`, `sy/api/routes.py` (header), `docs/adr/0009-*.md` |
| 29 | feat/observability | `sy/infrastructure/telemetry.py`, edits across services for spans, `dashboards/*.json`, `infra/alerts/*.yaml` |
| 30 | feat/graceful-shutdown | edit `sy/api/app.py` (lifespan drain), `sy/api/sse.py`, tests |
| 31 | chore/terraform-infra | `infra/terraform/**` |
| 32 | chore/cd-pipeline | `.github/workflows/{cd,smoke}.yml` |
| 33 | chore/loadtest-and-docs | `loadtest/**`, `docs/{architecture,failure-modes}.md`, `docs/runbooks/*`, `README.md` |

### Collisions found and fixes (changes to the confirmed branch table)
| Group | Collision | Fix |
|---|---|---|
| B (2,3,4) | `docker-compose.yml` needs the fake-provider service | #2 owns compose and references `fake_provider/Dockerfile` + `fake_provider.app:create_app` by contract; #3 never edits compose |
| C (5,6) | `lifecycle.AttemptRecord` imports `Usage` / `ErrorClass` from #5 → **not independent** | Move #6 into group **D**: #5 alone, then #6, #7, #8 in parallel |
| D (7,8) | both could edit `pyproject.toml` | pre-declared by #1 |
| F (10,11,12) | adapters need `ModelSpec`; registering adapters touches `container.py` | `ModelSpec` & friends created in #5 (models only); #10 adds registry/matcher; adapter registration done in #13 |
| J (17,18) | none on files; both need `RedisClient` from #14 | fine (H merged first) |
| M (21,22,23) | `gateway_service.py`, `container.py`, `api/middleware.py` | only #21 edits them; #22, #23 standalone; wiring moved into #24 (now "wire admission + redaction + isolation suite") |
| O (25,26) | two Alembic heads; both would wire `gateway_service.py` | 0005 re-pointed to 0004 at the group merge (CI asserts `alembic heads` = 1); wiring in #27 |
| all | `code_index.md`, `metrics.md` | CLAUDE.md merge protocol |

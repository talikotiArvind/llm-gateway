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

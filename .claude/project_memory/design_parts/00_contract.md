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

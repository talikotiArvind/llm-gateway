# Code Index

Auto-updated by `.claude/hooks/update_code_index.py` when source files are edited.

**AGENTS: Read this file first before reading any source file.**
Use it to understand what exists before loading full files.
Only load a full source file when you need to inspect specific logic.

---

<!-- Entries are auto-inserted below by the hook -->

<!-- BEGIN: C:/Users/ATALIK~1/AppData/Local/Temp/claude/8c63851b6bd4bcdb/b3358041-f6ae-480b-8b87-8fdecc074b49/scratchpad/apply.py -->
## C:/Users/ATALIK~1/AppData/Local/Temp/claude/8c63851b6bd4bcdb/b3358041-f6ae-480b-8b87-8fdecc074b49/scratchpad/apply.py
*Updated: 2026-11-05 00:27*

**Purpose**: No module docstring
<!-- END: C:/Users/ATALIK~1/AppData/Local/Temp/claude/8c63851b6bd4bcdb/b3358041-f6ae-480b-8b87-8fdecc074b49/scratchpad/apply.py -->

<!-- BEGIN: src/switchyard/infrastructure/settings.py -->
## src/switchyard/infrastructure/settings.py
*Updated: 2026-11-05 00:36*

**Purpose**: Process configuration loaded from ``SWITCHYARD_*`` environment variables.
**Classes**:
  - `Settings(BaseSettings)`: Typed gateway settings; invalid or unknown values fail at construction.
    - `@model_validator(mode='before') @classmethod _reject_unknown_env(cls, data: object) -> object`: 
    - `@classmethod _is_unknown_env(cls, name: str) -> bool`: 
<!-- END: src/switchyard/infrastructure/settings.py -->

<!-- BEGIN: fake_provider/app.py -->
## fake_provider/app.py
*Updated: 2026-11-05 00:36*

**Purpose**: ASGI app factory for the OpenAI-shaped fake provider (``fake_provider.app:create_app``).
**Classes**:
  - `ChatCompletionRequest(BaseModel)`: The subset of the OpenAI chat request the fake provider inspects.
    - `first_tool_name(self) -> str | None`: Return the first declared function name, if any.
  - `ProviderStats`: Request and connection counters exposed on ``/admin/stats``.
    - `snapshot(self) -> dict[str, Any]`: Return a JSON-ready copy with statuses sorted.
  - `ErrorResponder`: Shapes OpenAI-style error responses.
    - `respond(self, status: int, message: str, retry_after_s: float | None = None) -> Response`: Return a JSON error with an optional ``Retry-After`` header.
  - `CompletionService`: Orchestrates one chat completion: knobs, delays, fault injection, response.
    - `__init__(self, resolver: KnobResolver, rngs: RngPool, clock: Clock, stats: ProviderStats, errors: ErrorResponder) -> None`: 
    - `async handle(self, request: ChatCompletionRequest, headers: Mapping[str, str], disconnected: DisconnectProbe = never_disconnected) -> Response`: Return the completion (JSON or SSE) or an injected error.
    - `_injected_status(self, knobs: FakeKnobs) -> int | None`: 
    - `_error_for(self, status: int, knobs: FakeKnobs) -> Response`: 
    - `_stream_response(self, plan: CompletionPlan, disconnected: DisconnectProbe) -> StreamingResponse`: 
    - `async _tracked(self, plan: CompletionPlan, disconnected: DisconnectProbe) -> AsyncIterator[str]`: 
    - `_record(self, response: Response) -> Response`: 
  - `AdminService`: Global knob management and stats for test harnesses.
    - `__init__(self, store: KnobStore, rngs: RngPool, stats: ProviderStats) -> None`: 
    - `current(self) -> dict[str, Any]`: Return the effective global knobs.
    - `update(self, patch: Mapping[str, Any]) -> dict[str, Any]`: Merge ``patch`` into the global knobs and restart the seeded RNG streams.
    - `reset(self) -> dict[str, Any]`: Clear every global override, restart RNG streams, and return the defaults.
    - `stats(self) -> dict[str, Any]`: Return the counters snapshot.
**Functions**:
- `_models_body() -> dict[str, Any]`: 
- `_register_error_handlers(app: FastAPI, errors: ErrorResponder) -> None`: 
- `_register_admin_routes(app: FastAPI, admin: AdminService) -> None`: 
- `_patch_route(admin: AdminService) -> Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]`: 
- `create_app(clock: Clock | None = None) -> FastAPI`: Build the fake provider app; pass a fake ``clock`` in tests to skip real sleeps.
<!-- END: fake_provider/app.py -->

<!-- BEGIN: fake_provider/knobs.py -->
## fake_provider/knobs.py
*Updated: 2026-11-05 00:36*

**Purpose**: Fault-injection knobs for the fake provider: model, global store, per-request resolution.
**Classes**:
  - `KnobError(ValueError)`: Raised when a knob name or value is invalid.
  - `HangMode(StrEnum)`: Where the provider stalls until the client disconnects or ``hang_max_s`` elapses.
  - `FakeKnobs(BaseModel)`: Effective knobs for one request (defaults < global store < x-fake-* headers).
    - `@field_validator('error_status') @classmethod _check_error_status(cls, value: int) -> int`: 
    - `@field_validator('hang', mode='before') @classmethod _coerce_hang(cls, value: object) -> object`: 
    - `@classmethod from_overrides(cls, overrides: Mapping[str, Any]) -> FakeKnobs`: Validate ``overrides`` on top of the defaults; raise ``KnobError`` if invalid.
  - `KnobStore`: Process-wide knob overrides set through the admin endpoints.
    - `__init__(self) -> None`: 
    - `overrides(self) -> dict[str, Any]`: Return a copy of the current global overrides.
    - `update(self, patch: Mapping[str, Any]) -> FakeKnobs`: Merge ``patch`` into the global overrides after validating the result.
    - `reset(self) -> None`: Drop every global override.
  - `KnobResolver`: Combines global overrides with ``x-fake-*`` request headers.
    - `__init__(self, store: KnobStore) -> None`: 
    - `resolve(self, headers: Mapping[str, str]) -> FakeKnobs`: Return the effective knobs; headers win over the global store.
    - `@staticmethod _from_headers(headers: Mapping[str, str]) -> dict[str, str]`: 
  - `RngPool`: One ``random.Random`` per seed, so a request sequence replays identically.
    - `__init__(self) -> None`: 
    - `for_seed(self, seed: int) -> random.Random`: Return the RNG stream for ``seed``, creating it on first use.
    - `reset(self) -> None`: Restart every seeded stream from the beginning.
**Functions**:
- `_describe(exc: ValidationError) -> str`: 
<!-- END: fake_provider/knobs.py -->

<!-- BEGIN: fake_provider/streaming.py -->
## fake_provider/streaming.py
*Updated: 2026-11-05 00:36*

**Purpose**: OpenAI-shaped payload building and SSE chunk streaming with fault injection.
**Classes**:
  - `StreamDroppedError(ConnectionError)`: Raised mid-stream so the server aborts the connection without ``[DONE]``.
  - `Clock(Protocol)`: Time source; injected so tests never really sleep.
    - `now(self) -> float`: Return the current UNIX time in seconds.
    - `monotonic(self) -> float`: Return a monotonic time in seconds (for measuring elapsed waits).
    - `async sleep(self, seconds: float) -> None`: Wait ``seconds``.
  - `SystemClock`: Real wall clock and asyncio sleeps.
    - `now(self) -> float`: Return the current UNIX time in seconds.
    - `monotonic(self) -> float`: Return ``time.monotonic()``.
    - `async sleep(self, seconds: float) -> None`: Wait ``seconds`` (no-op for non-positive values).
  - `HangWaiter`: Stalls until the client disconnects or ``max_s`` elapses, whichever comes first.
    - `__init__(self, clock: Clock, poll_interval_s: float = HANG_POLL_INTERVAL_S) -> None`: 
    - `async wait(self, max_s: float, disconnected: DisconnectProbe) -> bool`: Return True if the client disconnected, False if ``max_s`` elapsed first.
  - `CompletionPlan`: Everything needed to render one completion deterministically.
    - `@classmethod create(cls, model: str, messages: Sequence[Any], tool_name: str | None, knobs: FakeKnobs, now: float) -> CompletionPlan`: Build a plan; the id is a hash of seed, model and messages so replays match.
  - `CompletionBuilder`: Pure transformation from a ``CompletionPlan`` to OpenAI wire payloads.
    - `pieces(self, plan: CompletionPlan) -> list[str]`: Split the text (or tool arguments) into ``knobs.chunks`` non-empty pieces.
    - `completion(self, plan: CompletionPlan) -> dict[str, Any]`: Return a non-streaming ``chat.completion`` body.
    - `chunks(self, plan: CompletionPlan) -> list[dict[str, Any]]`: Return every ``chat.completion.chunk`` payload, in order, without ``[DONE]``.
    - `usage(self, plan: CompletionPlan) -> dict[str, int]`: Return deterministic token counts for the plan.
    - `_first_delta(self, plan: CompletionPlan) -> dict[str, Any]`: 
    - `@staticmethod _piece_delta(plan: CompletionPlan, piece: str) -> dict[str, Any]`: 
    - `_chunk(self, plan: CompletionPlan, delta: dict[str, Any], finish: str | None) -> dict[str, Any]`: 
    - `@staticmethod _envelope(plan: CompletionPlan, obj: str) -> dict[str, Any]`: 
    - `@staticmethod _tool_call(plan: CompletionPlan) -> dict[str, Any]`: 
    - `@staticmethod _finish(plan: CompletionPlan) -> str`: 
  - `ChunkStreamer`: Turns chunk payloads into SSE frames, honouring timing and stream-fault knobs.
    - `__init__(self, builder: CompletionBuilder, clock: Clock, waiter: HangWaiter) -> None`: 
    - `async stream(self, plan: CompletionPlan, disconnected: DisconnectProbe = never_disconnected) -> AsyncIterator[str]`: Yield SSE frames ending with ``data: [DONE]`` unless a fault cuts the stream.
    - `async _before_frame(self, knobs: FakeKnobs, index: int, disconnected: DisconnectProbe) -> None`: 
    - `async _hang(self, knobs: FakeKnobs, disconnected: DisconnectProbe, index: int) -> None`: 
    - `@staticmethod _render(knobs: FakeKnobs, index: int, payload: dict[str, Any]) -> str`: 
**Functions**:
- `async never_disconnected() -> bool`: Disconnect probe for callers with no client connection to watch.
<!-- END: fake_provider/streaming.py -->

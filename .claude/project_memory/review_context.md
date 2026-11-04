# Review Context — 2026-11-05 00:38
Comparing: `8738372` → HEAD

## Session Stats
| Metric | Value |
|--------|-------|
| Files changed | 9 |
| Lines added | +329 |
| Lines removed | -65 |
| Index coverage | 4/9 files indexed |
| Layers touched (computed) | ai (data access) |
| High-risk area touched (computed) | no |
| Unresolved CRITICAL from last review (computed) | 0 |

> Reviewer: use the three computed rows above for the Risk Assessment table's 'Layers touched' and 'Unresolved CRITICAL' rows instead of re-deriving them from memory — they're read from the diff and review_log.md, not self-reported.

## Changed Files
- `fake_provider/app.py` — ✓ indexed
- `fake_provider/knobs.py` — ✓ indexed
- `fake_provider/streaming.py` — ✓ indexed
- `src/switchyard/infrastructure/settings.py` — ✓ indexed
- `tests/unit/fake_provider/support.py` — ✗ not indexed
- `tests/unit/fake_provider/test_app.py` — ✗ not indexed
- `tests/unit/fake_provider/test_streaming.py` — ✗ not indexed
- `tests/unit/test_layering.py` — ✗ not indexed
- `tests/unit/test_settings.py` — ✗ not indexed

---

## Code Index — Changed Files Only

### fake_provider/app.py
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

### fake_provider/knobs.py
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

### fake_provider/streaming.py
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

### src/switchyard/infrastructure/settings.py
## src/switchyard/infrastructure/settings.py
*Updated: 2026-11-05 00:36*

**Purpose**: Process configuration loaded from ``SWITCHYARD_*`` environment variables.
**Classes**:
  - `Settings(BaseSettings)`: Typed gateway settings; invalid or unknown values fail at construction.
    - `@model_validator(mode='before') @classmethod _reject_unknown_env(cls, data: object) -> object`: 
    - `@classmethod _is_unknown_env(cls, name: str) -> bool`:

---

## Git Diff
```diff
diff --git a/fake_provider/app.py b/fake_provider/app.py
index 80cfaa7..1b6a564 100644
--- a/fake_provider/app.py
+++ b/fake_provider/app.py
@@ -18,18 +18,23 @@ from fake_provider.streaming import (
     Clock,
     CompletionBuilder,
     CompletionPlan,
+    DisconnectProbe,
+    HangWaiter,
     SystemClock,
+    never_disconnected,
 )
 
 MODEL_IDS = ("fake-model", "fake-model-fallback", "fake-model-mini")
 OWNER = "switchyard-fake"
 DEFAULT_429_RETRY_AFTER_S = 1.0
+HANG_EXPIRED_STATUS = 504
 _ERROR_TYPES = {
     400: ("invalid_request_error", "invalid_request"),
     401: ("authentication_error", "invalid_api_key"),
     429: ("rate_limit_error", "rate_limit_exceeded"),
     500: ("server_error", "internal_error"),
     503: ("server_error", "service_unavailable"),
+    504: ("server_error", "upstream_timeout"),
     529: ("overloaded_error", "overloaded"),
 }
 KnobPatch = Annotated[dict[str, Any], Body()]
@@ -101,17 +106,33 @@ class CompletionService:
         self._stats = stats
         self._errors = errors
         self._builder = CompletionBuilder()
-        self._streamer = ChunkStreamer(self._builder, clock)
+        self._waiter = HangWaiter(clock)
+        self._streamer = ChunkStreamer(self._builder, clock, self._waiter)
 
-    async def handle(self, request: ChatCompletionRequest, headers: Mapping[str, str]) -> Response:
-        """Return the completion (JSON or SSE) or an injected error."""
+    async def handle(
+        self,
+        request: ChatCompletionRequest,
+        headers: Mapping[str, str],
+        disconnected: DisconnectProbe = never_disconnected,
+    ) -> Response:
+        """Return the completion (JSON or SSE) or an injected error.
+
+        A hang before headers ends with a 504 once the client disconnects or
+        ``hang_max_s`` elapses, so no handler is ever parked forever.
+        """
         self._stats.requests += 1
-        knobs = self._resolver.resolve(headers)
+        try:
+            knobs = self._resolver.resolve(headers)
+        except KnobError:
+            self._stats.by_status[400] += 1
+            raise
         await self._clock.sleep(knobs.latency_ms / 1000)
         if knobs.hang is not HangMode.NONE and (
             knobs.hang is HangMode.BEFORE_HEADERS or not request.stream
         ):
-            await self._clock.hang()
+            await self._waiter.wait(knobs.hang_max_s, disconnected)
+            message = f"fake provider hang ended after at most {knobs.hang_max_s:g}s"
+            return self._record(self._errors.respond(HANG_EXPIRED_STATUS, message))
         injected = self._injected_status(knobs)
         if injected is not None:
             return self._record(self._error_for(injected, knobs))
@@ -119,7 +140,7 @@ class CompletionService:
             request.model, request.messages, request.first_tool_name(), knobs, self._clock.now()
         )
         if request.stream:
-            return self._record(self._stream_response(plan))
+            return self._record(self._stream_response(plan, disconnected))
         await self._clock.sleep(knobs.ttft_ms / 1000)
         return self._record(JSONResponse(self._builder.completion(plan)))
 
@@ -137,16 +158,20 @@ class CompletionService:
             retry_after = None
         return self._errors.respond(status, f"fake provider injected HTTP {status}", retry_after)
 
-    def _stream_response(self, plan: CompletionPlan) -> StreamingResponse:
+    def _stream_response(
+        self, plan: CompletionPlan, disconnected: DisconnectProbe
+    ) -> StreamingResponse:
         headers = {"Cache-Control": "no-cache"}
         return StreamingResponse(
-            self._tracked(plan), media_type="text/event-stream", headers=headers
+            self._tracked(plan, disconnected), media_type="text/event-stream", headers=headers
         )
 
-    async def _tracked(self, plan: CompletionPlan) -> AsyncIterator[str]:
+    async def _tracked(
+        self, plan: CompletionPlan, disconnected: DisconnectProbe
+    ) -> AsyncIterator[str]:
         self._stats.open_connections += 1
         try:
-            async for frame in self._streamer.stream(plan):
+            async for frame in self._streamer.stream(plan, disconnected):
                 yield frame
         finally:
             self._stats.open_connections -= 1
@@ -232,7 +257,7 @@ def create_app(clock: Clock | None = None) -> FastAPI:
     @app.post("/v1/chat/completions")
     async def chat_completions(body: ChatCompletionRequest, request: Request) -> Response:
         """OpenAI ``POST /v1/chat/completions``."""
-        return await service.handle(body, request.headers)
+        return await service.handle(body, request.headers, request.is_disconnected)
 
     @app.get("/v1/models")
     async def list_models() -> dict[str, Any]:
diff --git a/fake_provider/knobs.py b/fake_provider/knobs.py
index 603c95c..7577853 100644
--- a/fake_provider/knobs.py
+++ b/fake_provider/knobs.py
@@ -13,6 +13,8 @@ HEADER_PREFIX = "x-fake-"
 SUPPORTED_ERROR_STATUSES = frozenset({400, 401, 429, 500, 503, 529})
 DEFAULT_TEXT = "Hello from the Switchyard fake provider. This reply is deterministic."
 MAX_CHUNKS = 1_000
+DEFAULT_HANG_MAX_S = 300.0  # every hang ends: a real server never cancels a stalled handler
+MAX_HANG_S = 3_600.0
 _TRUE_VALUES = frozenset({"true", "1", "yes", "on"})
 _FALSE_VALUES = frozenset({"false", "0", "no", "off", ""})
 
@@ -22,7 +24,7 @@ class KnobError(ValueError):
 
 
 class HangMode(StrEnum):
-    """Where the provider stalls until the client disconnects."""
+    """Where the provider stalls until the client disconnects or ``hang_max_s`` elapses."""
 
     NONE = "none"
     BEFORE_HEADERS = "before_headers"
@@ -42,6 +44,7 @@ class FakeKnobs(BaseModel):
     error_status: int = 503
     retry_after_s: float | None = Field(default=None, ge=0.0)
     hang: HangMode = HangMode.NONE
+    hang_max_s: float = Field(default=DEFAULT_HANG_MAX_S, gt=0.0, le=MAX_HANG_S)
     drop_after_chunks: int | None = Field(default=None, ge=0)
     malformed_at_chunk: int | None = Field(default=None, ge=0)
     usage: bool = True
@@ -124,7 +127,12 @@ class KnobResolver:
 
 
 class RngPool:
-    """One ``random.Random`` per seed, so a request sequence replays identically."""
+    """One ``random.Random`` per seed, so a request sequence replays identically.
+
+    Streams are process-global per seed and seeded RNGs are used for fault injection, not
+    crypto. Replay is deterministic only for sequential requests: concurrent requests with
+    the same seed interleave their draws.
+    """
 
     def __init__(self) -> None:
         self._by_seed: dict[int, random.Random] = {}
@@ -132,7 +140,7 @@ class RngPool:
     def for_seed(self, seed: int) -> random.Random:
         """Return the RNG stream for ``seed``, creating it on first use."""
         if seed not in self._by_seed:
-            self._by_seed[seed] = random.Random(seed)  # noqa: S311  # nosec B311 - fault injection, not crypto
+            self._by_seed[seed] = random.Random(seed)  # noqa: S311  # nosec B311
         return self._by_seed[seed]
 
     def reset(self) -> None:
diff --git a/fake_provider/streaming.py b/fake_provider/streaming.py
index 7937864..cebc464 100644
--- a/fake_provider/streaming.py
+++ b/fake_provider/streaming.py
@@ -6,7 +6,7 @@ import asyncio
 import hashlib
 import json
 import time
-from collections.abc import AsyncIterator, Sequence
+from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
 from dataclasses import dataclass
 from typing import Any, Protocol
 
@@ -16,6 +16,9 @@ DONE_FRAME = "data: [DONE]\n\n"
 MALFORMED_FRAME = 'data: {"id": "chatcmpl-malformed", "choices": [\n\n'
 DEFAULT_TOOL_NAME = "get_weather"
 TOOL_ARGUMENTS = '{"location": "Paris", "unit": "celsius"}'
+HANG_POLL_INTERVAL_S = 0.1
+
+DisconnectProbe = Callable[[], Awaitable[bool]]
 
 
 class StreamDroppedError(ConnectionError):
@@ -29,12 +32,12 @@ class Clock(Protocol):
         """Return the current UNIX time in seconds."""
         ...
 
-    async def sleep(self, seconds: float) -> None:
-        """Wait ``seconds``."""
+    def monotonic(self) -> float:
+        """Return a monotonic time in seconds (for measuring elapsed waits)."""
         ...
 
-    async def hang(self) -> None:
-        """Wait until cancelled (the client disconnects)."""
+    async def sleep(self, seconds: float) -> None:
+        """Wait ``seconds``."""
         ...
 
 
@@ -45,14 +48,46 @@ class SystemClock:
         """Return the current UNIX time in seconds."""
         return time.time()
 
+    def monotonic(self) -> float:
+        """Return ``time.monotonic()``."""
+        return time.monotonic()
+
     async def sleep(self, seconds: float) -> None:
         """Wait ``seconds`` (no-op for non-positive values)."""
         if seconds > 0:
             await asyncio.sleep(seconds)
 
-    async def hang(self) -> None:
-        """Wait until the surrounding task is cancelled."""
-        await asyncio.Event().wait()
+
+async def never_disconnected() -> bool:
+    """Disconnect probe for callers with no client connection to watch."""
+    return False
+
+
+class HangWaiter:
+    """Stalls until the client disconnects or ``max_s`` elapses, whichever comes first.
+
+    Uvicorn does not cancel a handler when its client goes away, and a streaming response
+    notices a disconnect only when it next sends. So a hang must poll for the disconnect
+    and must have a cap, or every hung request parks a coroutine forever.
+    """
+
+    def __init__(self, clock: Clock, poll_interval_s: float = HANG_POLL_INTERVAL_S) -> None:
+        if poll_interval_s <= 0:
+            raise ValueError("poll_interval_s must be positive")
+        self._clock = clock
+        self._poll_interval_s = poll_interval_s
+
+    async def wait(self, max_s: float, disconnected: DisconnectProbe) -> bool:
+        """Return True if the client disconnected, False if ``max_s`` elapsed first."""
+        if max_s <= 0:
+            raise ValueError("max_s must be positive")
+        deadline = self._clock.monotonic() + max_s
+        while not await disconnected():
+            remaining = deadline - self._clock.monotonic()
+            if remaining <= 0:
+                return False
+            await self._clock.sleep(min(self._poll_interval_s, remaining))
+        return True
 
 
 @dataclass(frozen=True)
@@ -176,30 +211,43 @@ class CompletionBuilder:
 class ChunkStreamer:
     """Turns chunk payloads into SSE frames, honouring timing and stream-fault knobs."""
 
-    def __init__(self, builder: CompletionBuilder, clock: Clock) -> None:
+    def __init__(self, builder: CompletionBuilder, clock: Clock, waiter: HangWaiter) -> None:
         self._builder = builder
         self._clock = clock
+        self._waiter = waiter
+
+    async def stream(
+        self, plan: CompletionPlan, disconnected: DisconnectProbe = never_disconnected
+    ) -> AsyncIterator[str]:
+        """Yield SSE frames ending with ``data: [DONE]`` unless a fault cuts the stream.
 
-    async def stream(self, plan: CompletionPlan) -> AsyncIterator[str]:
-        """Yield SSE frames ending with ``data: [DONE]`` unless a fault cuts the stream."""
+        A hang ends the stream without ``[DONE]`` once the client disconnects or
+        ``hang_max_s`` elapses.
+        """
         knobs = plan.knobs
         await self._clock.sleep(knobs.ttft_ms / 1000)
         if knobs.hang is HangMode.BEFORE_FIRST_CHUNK:
-            await self._clock.hang()
+            await self._hang(knobs, disconnected, 0)
         for index, payload in enumerate(self._builder.chunks(plan)):
-            await self._before_frame(knobs, index)
+            await self._before_frame(knobs, index, disconnected)
             yield self._render(knobs, index, payload)
         yield DONE_FRAME
 
-    async def _before_frame(self, knobs: FakeKnobs, index: int) -> None:
+    async def _before_frame(
+        self, knobs: FakeKnobs, index: int, disconnected: DisconnectProbe
+    ) -> None:
         if knobs.drop_after_chunks is not None and index >= knobs.drop_after_chunks:
             raise StreamDroppedError(f"fake stream dropped after {index} chunks")
         if index == 0:
             return
         if knobs.hang is HangMode.MID_STREAM and index == 1:
-            await self._clock.hang()
+            await self._hang(knobs, disconnected, index)
         await self._clock.sleep(knobs.inter_chunk_ms / 1000)
 
+    async def _hang(self, knobs: FakeKnobs, disconnected: DisconnectProbe, index: int) -> None:
+        await self._waiter.wait(knobs.hang_max_s, disconnected)
+        raise StreamDroppedError(f"fake stream hung after {index} chunks and was ended")
+
     @staticmethod
     def _render(knobs: FakeKnobs, index: int, payload: dict[str, Any]) -> str:
         if knobs.malformed_at_chunk == index:
diff --git a/src/switchyard/infrastructure/settings.py b/src/switchyard/infrastructure/settings.py
index 6c46a41..013e18a 100644
--- a/src/switchyard/infrastructure/settings.py
+++ b/src/switchyard/infrastructure/settings.py
@@ -2,10 +2,11 @@
 
 from __future__ import annotations
 
+import os
 from pathlib import Path
 from typing import Literal
 
-from pydantic import AnyUrl, Field, PositiveInt
+from pydantic import AnyUrl, Field, PositiveInt, model_validator
 from pydantic_settings import BaseSettings, SettingsConfigDict
 
 DEFAULT_MAX_BODY_BYTES = 1_048_576  # OQ-05: 1 MiB, larger bodies get 413
@@ -14,18 +15,25 @@ DEFAULT_MAX_TOOL_PAYLOAD_BYTES = 65_536  # OQ-05: 64 KiB
 DEFAULT_RPM = 600
 DEFAULT_TPM = 200_000
 DEFAULT_CONCURRENCY = 20
+ENV_PREFIX = "SWITCHYARD_"
+# Read directly by other components, not by Settings: the "env" secrets backend.
+RESERVED_ENV_PREFIXES = ("SWITCHYARD_PROVIDER_KEY_",)
 
 
 class Settings(BaseSettings):
     """Typed gateway settings; invalid or unknown values fail at construction.
 
+    Unknown ``SWITCHYARD_*`` environment variables are rejected too (``extra="forbid"`` only
+    covers init kwargs), so a typo such as ``SWITCHYARD_DEFAULT_RMP`` cannot silently fall back
+    to a default. ``RESERVED_ENV_PREFIXES`` are exempt.
+
     Only fields that need no I/O live here for now. Database/Redis fields are added
     by T14 and API-key HMAC fields by T21.
     """
 
     # No env_file: production config comes only from the process environment.
     model_config = SettingsConfigDict(
-        env_prefix="SWITCHYARD_",
+        env_prefix=ENV_PREFIX,
         extra="forbid",
         frozen=True,
     )
@@ -43,3 +51,18 @@ class Settings(BaseSettings):
     default_rpm: PositiveInt = DEFAULT_RPM
     default_tpm: PositiveInt = DEFAULT_TPM
     default_concurrency: PositiveInt = DEFAULT_CONCURRENCY
+
+    @model_validator(mode="before")
+    @classmethod
+    def _reject_unknown_env(cls, data: object) -> object:
+        unknown = sorted(name for name in os.environ if cls._is_unknown_env(name))
+        if unknown:
+            raise ValueError(f"unknown {ENV_PREFIX}* environment variable(s): {', '.join(unknown)}")
+        return data
+
+    @classmethod
+    def _is_unknown_env(cls, name: str) -> bool:
+        upper = name.upper()
+        if not upper.startswith(ENV_PREFIX) or upper.startswith(RESERVED_ENV_PREFIXES):
+            return False
+        return upper[len(ENV_PREFIX) :].lower() not in cls.model_fields
diff --git a/tests/unit/fake_provider/support.py b/tests/unit/fake_provider/support.py
index ec2d01e..cdc6b8e 100644
--- a/tests/unit/fake_provider/support.py
+++ b/tests/unit/fake_provider/support.py
@@ -3,28 +3,24 @@
 from __future__ import annotations
 
 
-class HangCalledError(Exception):
-    """Raised by ``FakeClock.hang`` so a stall is observable without waiting."""
-
-
 class FakeClock:
-    """Records requested sleeps and turns ``hang`` into an immediate exception."""
+    """Records requested sleeps; each sleep advances the monotonic time instantly."""
 
     NOW = 1_700_000_000.5
 
     def __init__(self) -> None:
         self.sleeps: list[float] = []
-        self.hangs = 0
+        self.elapsed = 0.0
 
     def now(self) -> float:
         """Return a fixed timestamp."""
         return self.NOW
 
+    def monotonic(self) -> float:
+        """Return the total time "slept" so far."""
+        return self.elapsed
+
     async def sleep(self, seconds: float) -> None:
-        """Record ``seconds`` and return immediately."""
+        """Record ``seconds``, advance the monotonic time and return immediately."""
         self.sleeps.append(seconds)
-
-    async def hang(self) -> None:
-        """Record the stall and raise instead of waiting forever."""
-        self.hangs += 1
-        raise HangCalledError
+        self.elapsed += max(seconds, 0.0)
diff --git a/tests/unit/fake_provider/test_app.py b/tests/unit/fake_provider/test_app.py
index 50c7394..cbb87a7 100644
--- a/tests/unit/fake_provider/test_app.py
+++ b/tests/unit/fake_provider/test_app.py
@@ -12,7 +12,7 @@ import pytest
 from fake_provider.app import MODEL_IDS, create_app
 from fake_provider.streaming import DONE_FRAME, MALFORMED_FRAME, StreamDroppedError
 
-from .support import FakeClock, HangCalledError
+from .support import FakeClock
 
 CHAT_PATH = "/v1/chat/completions"
 BODY: dict[str, Any] = {"model": "fake-model", "messages": [{"role": "user", "content": "hi"}]}
@@ -136,15 +136,34 @@ class ErrorInjectionTest(FakeProviderTestCase):
 class StreamFaultTest(FakeProviderTestCase):
     """Hang, drop and malformed-chunk knobs through the HTTP surface."""
 
-    async def test_hang_before_headers_sends_no_first_byte(self) -> None:
+    async def test_hang_before_headers_ends_with_504_at_cap(self) -> None:
         for stream in (False, True):
-            with self.subTest(stream=stream), self.assertRaises(HangCalledError):
-                await self._chat({"hang": "true"}, stream=stream)
-        self.assertEqual(2, self.clock.hangs)
+            with self.subTest(stream=stream):
+                self.clock.elapsed = 0.0
+                response = await self._chat({"hang": "true", "hang_max_s": "2"}, stream=stream)
+                self.assertEqual(504, response.status_code)
+                self.assertEqual("server_error", response.json()["error"]["type"])
+                self.assertAlmostEqual(2.0, self.clock.elapsed)
 
     async def test_non_stream_hangs_for_any_hang_mode(self) -> None:
-        with self.assertRaises(HangCalledError):
-            await self._chat({"hang": "mid_stream"})
+        response = await self._chat({"hang": "mid_stream", "hang_max_s": "1"})
+        self.assertEqual(504, response.status_code)
+        self.assertAlmostEqual(1.0, self.clock.elapsed)
+
+    async def test_hang_default_cap_is_bounded(self) -> None:
+        response = await self._chat({"hang": "true"})
+        self.assertEqual(504, response.status_code)
+        self.assertAlmostEqual(300.0, self.clock.elapsed)
+        self.assertLessEqual(max(self.clock.sleeps), 0.1)
+
+    async def test_mid_stream_hang_ends_and_releases_connection(self) -> None:
+        headers = {"x-fake-hang": "mid_stream", "x-fake-hang-max-s": "1"}
+        async with self._client(raise_app_exceptions=False) as client:
+            response = await client.post(CHAT_PATH, json={**BODY, "stream": True}, headers=headers)
+            stats = (await client.get("/admin/stats")).json()
+        self.assertEqual(1, len(self._frames(response)))
+        self.assertEqual(0, stats["open_connections"])
+        self.assertEqual(1, stats["closed_connections"])
 
     async def test_drop_after_chunks_has_no_done(self) -> None:
         headers = {"x-fake-drop-after-chunks": "3"}
@@ -190,6 +209,13 @@ class AdminAndValidationTest(FakeProviderTestCase):
             response = await client.post(CHAT_PATH, json={"model": "fake-model", "messages": []})
         self.assertEqual(400, response.status_code)
 
+    async def test_invalid_knob_is_counted_as_400(self) -> None:
+        async with self._client() as client:
+            response = await client.post(CHAT_PATH, json=BODY, headers={"x-fake-chunks": "0"})
+            stats = (await client.get("/admin/stats")).json()
+        self.assertEqual(400, response.status_code)
+        self.assertEqual({"400": 1}, stats["by_status"])
+
     async def test_stats_count_requests_statuses_and_connections(self) -> None:
         await self._chat()
         await self._chat(stream=True)
diff --git a/tests/unit/fake_provider/test_streaming.py b/tests/unit/fake_provider/test_streaming.py
index c2f644b..c924c51 100644
--- a/tests/unit/fake_provider/test_streaming.py
+++ b/tests/unit/fake_provider/test_streaming.py
@@ -2,7 +2,6 @@
 
 from __future__ import annotations
 
-import asyncio
 import json
 import unittest
 from unittest.mock import AsyncMock, patch
@@ -16,11 +15,13 @@ from fake_provider.streaming import (
     ChunkStreamer,
     CompletionBuilder,
     CompletionPlan,
+    HangWaiter,
     StreamDroppedError,
     SystemClock,
+    never_disconnected,
 )
 
-from .support import FakeClock, HangCalledError
+from .support import FakeClock
 
 MESSAGES = [{"role": "user", "content": "hi there"}]
 
@@ -98,7 +99,7 @@ class ChunkStreamerTest(unittest.IsolatedAsyncioTestCase):
 
     def setUp(self) -> None:
         self.clock = FakeClock()
-        self.streamer = ChunkStreamer(CompletionBuilder(), self.clock)
+        self.streamer = ChunkStreamer(CompletionBuilder(), self.clock, HangWaiter(self.clock))
 
     async def _collect(self, plan: CompletionPlan) -> list[str]:
         return [frame async for frame in self.streamer.stream(plan)]
@@ -132,19 +133,59 @@ class ChunkStreamerTest(unittest.IsolatedAsyncioTestCase):
             json.loads(frames[2][len("data: ") :])
         self.assertEqual(DONE_FRAME, frames[-1])
 
-    async def test_hang_before_first_chunk(self) -> None:
+    async def test_hang_before_first_chunk_ends_at_cap_without_done(self) -> None:
         received: list[str] = []
-        with self.assertRaises(HangCalledError):
-            async for frame in self.streamer.stream(_plan(hang=HangMode.BEFORE_FIRST_CHUNK)):
+        plan = _plan(hang=HangMode.BEFORE_FIRST_CHUNK, hang_max_s=3)
+        with self.assertRaises(StreamDroppedError):
+            async for frame in self.streamer.stream(plan):
                 received.append(frame)
         self.assertEqual([], received)
+        self.assertAlmostEqual(3.0, self.clock.elapsed)
 
-    async def test_hang_mid_stream(self) -> None:
+    async def test_hang_mid_stream_ends_on_disconnect(self) -> None:
         received: list[str] = []
-        with self.assertRaises(HangCalledError):
-            async for frame in self.streamer.stream(_plan(hang=HangMode.MID_STREAM)):
+        disconnected = AsyncMock(side_effect=[False, False, True])
+        plan = _plan(hang=HangMode.MID_STREAM)
+        with self.assertRaises(StreamDroppedError):
+            async for frame in self.streamer.stream(plan, disconnected):
                 received.append(frame)
         self.assertEqual(1, len(received))
+        self.assertEqual(3, disconnected.await_count)
+        self.assertAlmostEqual(0.2, self.clock.elapsed)
+
+
+@pytest.mark.unit
+class HangWaiterTest(unittest.IsolatedAsyncioTestCase):
+    """Hangs poll for a disconnect and always end by ``max_s``."""
+
+    def setUp(self) -> None:
+        self.clock = FakeClock()
+        self.waiter = HangWaiter(self.clock, poll_interval_s=0.5)
+
+    async def test_returns_false_when_cap_elapses(self) -> None:
+        self.assertFalse(await self.waiter.wait(1.2, never_disconnected))
+        self.assertEqual([0.5, 0.5], self.clock.sleeps[:2])
+        self.assertAlmostEqual(0.2, self.clock.sleeps[2])
+        self.assertAlmostEqual(1.2, self.clock.elapsed)
+
+    async def test_returns_true_on_disconnect_without_sleeping(self) -> None:
+        disconnected = AsyncMock(return_value=True)
+        self.assertTrue(await self.waiter.wait(10, disconnected))
+        self.assertEqual([], self.clock.sleeps)
+
+    async def test_returns_true_after_polling(self) -> None:
+        disconnected = AsyncMock(side_effect=[False, True])
+        self.assertTrue(await self.waiter.wait(10, disconnected))
+        self.assertEqual([0.5], self.clock.sleeps)
+
+    async def test_rejects_non_positive_arguments(self) -> None:
+        with self.assertRaises(ValueError):
+            HangWaiter(self.clock, poll_interval_s=0)
+        with self.assertRaises(ValueError):
+            await self.waiter.wait(0, never_disconnected)
+
+    async def test_never_disconnected_probe(self) -> None:
+        self.assertFalse(await never_disconnected())
 
 
 @pytest.mark.unit
@@ -157,9 +198,9 @@ class SystemClockTest(unittest.IsolatedAsyncioTestCase):
             await SystemClock().sleep(0.25)
         fake_sleep.assert_awaited_once_with(0.25)
 
-    async def test_hang_waits_until_cancelled(self) -> None:
-        with self.assertRaises(TimeoutError):
-            await asyncio.wait_for(SystemClock().hang(), timeout=0.01)
+    def test_monotonic_delegates_to_time(self) -> None:
+        with patch("fake_provider.streaming.time.monotonic", return_value=42.0):
+            self.assertEqual(42.0, SystemClock().monotonic())
 
     def test_now_is_positive(self) -> None:
         self.assertGreater(SystemClock().now(), 0)
diff --git a/tests/unit/test_layering.py b/tests/unit/test_layering.py
index af14780..3180c01 100644
--- a/tests/unit/test_layering.py
+++ b/tests/unit/test_layering.py
@@ -1,16 +1,24 @@
-"""Layering guard: the domain package stays pure (FR-13)."""
+"""Layering guards: the domain stays pure and every application module is layered (FR-13)."""
 
 from __future__ import annotations
 
 import ast
+import re
 import shutil
 import subprocess
+import tomllib
 import unittest
+from collections.abc import Iterable
 from pathlib import Path
+from tempfile import TemporaryDirectory
 
 import pytest
 
-DOMAIN_DIR = Path(__file__).resolve().parents[2] / "src" / "switchyard" / "domain"
+REPO_ROOT = Path(__file__).resolve().parents[2]
+DOMAIN_DIR = REPO_ROOT / "src" / "switchyard" / "domain"
+APPLICATION_DIR = REPO_ROOT / "src" / "switchyard" / "application"
+PYPROJECT = REPO_ROOT / "pyproject.toml"
+APPLICATION_MODULE_RE = re.compile(r"switchyard\.application\.[A-Za-z_][A-Za-z0-9_]*")
 DOMAIN_IMPORT_ALLOWLIST = frozenset(
     {
         "__future__",
@@ -58,6 +66,63 @@ class DomainImportCollector:
         return any(prefix in DOMAIN_IMPORT_ALLOWLIST for prefix in prefixes)
 
 
+class LayersContract:
+    """Reads the import-linter ``layers`` contract and finds application modules it misses."""
+
+    def __init__(self, layers: Iterable[str]) -> None:
+        self._named = frozenset(
+            name for layer in layers for name in APPLICATION_MODULE_RE.findall(layer)
+        )
+
+    @classmethod
+    def from_pyproject(cls, path: Path) -> LayersContract:
+        """Load the contract whose id is ``layers`` from ``path``."""
+        config = tomllib.loads(path.read_text(encoding="utf-8"))
+        contracts = config["tool"]["importlinter"]["contracts"]
+        layers = next(c["layers"] for c in contracts if c.get("id") == "layers")
+        return cls(layers)
+
+    @staticmethod
+    def application_modules(package_dir: Path) -> list[str]:
+        """Return the sorted top-level modules and subpackages of ``package_dir``."""
+        names = {p.stem for p in package_dir.glob("*.py") if p.name != "__init__.py"}
+        names |= {p.parent.name for p in package_dir.glob("*/__init__.py")}
+        return sorted(f"switchyard.application.{name}" for name in names)
+
+    def unlayered(self, modules: Iterable[str]) -> list[str]:
+        """Return the sorted modules that no layer names."""
+        return sorted(m for m in modules if m not in self._named)
+
+
+@pytest.mark.unit
+class ApplicationLayeringTest(unittest.TestCase):
+    """A new switchyard.application module cannot escape the layers contract."""
+
+    def setUp(self) -> None:
+        self.contract = LayersContract.from_pyproject(PYPROJECT)
+
+    def test_every_application_module_is_layered(self) -> None:
+        modules = LayersContract.application_modules(APPLICATION_DIR)
+        self.assertEqual([], self.contract.unlayered(modules))
+
+    def test_unlisted_module_is_reported(self) -> None:
+        contract = LayersContract(["(switchyard.application.budget_service) | switchyard.security"])
+        found = contract.unlayered(
+            ["switchyard.application.dto", "switchyard.application.budget_service"]
+        )
+        self.assertEqual(["switchyard.application.dto"], found)
+
+    def test_module_discovery_includes_subpackages(self) -> None:
+        with TemporaryDirectory() as tmp:
+            root = Path(tmp)
+            (root / "__init__.py").write_text("", encoding="utf-8")
+            (root / "ports.py").write_text("", encoding="utf-8")
+            (root / "dto").mkdir()
+            (root / "dto" / "__init__.py").write_text("", encoding="utf-8")
+            found = LayersContract.application_modules(root)
+        self.assertEqual(["switchyard.application.dto", "switchyard.application.ports"], found)
+
+
 @pytest.mark.unit
 class DomainLayeringTest(unittest.TestCase):
     """The domain layer imports only the stdlib allowlist, pydantic and itself."""
@@ -95,7 +160,9 @@ class DomainLayeringTest(unittest.TestCase):
         result = subprocess.run(  # fixed, trusted executable; no shell
             [executable],
             capture_output=True,
-            text=True,
+            # lint-imports prints Unicode; never decode with the locale codec (cp1252 on Windows).
+            encoding="utf-8",
+            errors="replace",
             timeout=LINT_IMPORTS_TIMEOUT_S,
             check=False,
         )
diff --git a/tests/unit/test_settings.py b/tests/unit/test_settings.py
index d4c6994..9eabca2 100644
--- a/tests/unit/test_settings.py
+++ b/tests/unit/test_settings.py
@@ -64,6 +64,36 @@ class SettingsTest(unittest.TestCase):
         with self.assertRaises(ValidationError):
             Settings(not_a_field=1)  # type: ignore[call-arg]
 
+    def test_unknown_prefixed_env_var_rejected(self) -> None:
+        with self.assertRaises(ValidationError) as ctx:
+            self._build(SWITCHYARD_DEFAULT_RMP="50")
+        self.assertIn("SWITCHYARD_DEFAULT_RMP", str(ctx.exception))
+
+    def test_unknown_env_vars_listed_sorted(self) -> None:
+        with self.assertRaises(ValidationError) as ctx:
+            self._build(SWITCHYARD_ZETA="1", SWITCHYARD_ALPHA="1", SWITCHYARD_AWS_REGION="x")
+        self.assertIn("SWITCHYARD_ALPHA, SWITCHYARD_ZETA", str(ctx.exception))
+
+    def test_unknown_env_var_check_is_case_insensitive(self) -> None:
+        with self.assertRaises(ValidationError):
+            self._build(switchyard_bogus="1")
+
+    def test_known_env_var_in_lower_case_accepted(self) -> None:
+        self.assertEqual(7, self._build(switchyard_default_rpm="7").default_rpm)
+
+    def test_reserved_provider_key_env_vars_allowed(self) -> None:
+        settings = self._build(
+            SWITCHYARD_PROVIDER_KEY_OPENAI="sk-test", SWITCHYARD_SECRETS_BACKEND="env"
+        )
+        self.assertEqual("env", settings.secrets_backend)
+
+    def test_unknown_env_var_rejected_for_kwargs_construction(self) -> None:
+        with (
+            patch.dict(os.environ, {"SWITCHYARD_BOGUS": "1"}, clear=True),
+            self.assertRaises(ValidationError),
+        ):
+            Settings(default_rpm=5)
+
     def test_settings_are_immutable(self) -> None:
         settings = self._build()
         with self.assertRaises(ValidationError):
```

---

## Reviewer Checklist
- [ ] Read index sections above — understand module context without loading full files
- [ ] Review diff for: correctness, design, security, performance, maintainability
- [ ] For any CRITICAL issue needing full context: Read only that specific file (budget: 2 reads)
- [ ] Write findings to `.claude/project_memory/review_log.md`
- [ ] Invoke `code-refactor` agent if REQUEST_CHANGES, or `unit-test` if APPROVE
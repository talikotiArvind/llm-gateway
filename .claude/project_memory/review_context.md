# Review Context — 2026-11-05 00:22
Comparing: `7e336b2` → HEAD

## Session Stats
| Metric | Value |
|--------|-------|
| Files changed | 66 |
| Lines added | +1618 |
| Lines removed | -0 |
| Index coverage | 0/66 files indexed |
| Layers touched (computed) | ai (data access), api (surface), app (service logic) |
| High-risk area touched (computed) | yes |
| Unresolved CRITICAL from last review (computed) | 0 |

> Reviewer: use the three computed rows above for the Risk Assessment table's 'Layers touched' and 'Unresolved CRITICAL' rows instead of re-deriving them from memory — they're read from the diff and review_log.md, not self-reported.

## Changed Files
- `fake_provider/__init__.py` — ✗ not indexed
- `fake_provider/app.py` — ✗ not indexed
- `fake_provider/knobs.py` — ✗ not indexed
- `fake_provider/streaming.py` — ✗ not indexed
- `src/__init__.py` — ✗ not indexed
- `src/ai/__init__.py` — ✗ not indexed
- `src/ai/a2a/__init__.py` — ✗ not indexed
- `src/ai/a2a/protocol.py` — ✗ not indexed
- `src/ai/a2a/router.py` — ✗ not indexed
- `src/ai/a2a/tool_adapter.py` — ✗ not indexed
- `src/ai/base_agent.py` — ✗ not indexed
- `src/ai/base_claude.py` — ✗ not indexed
- `src/ai/base_gemini.py` — ✗ not indexed
- `src/ai/base_openai.py` — ✗ not indexed
- `src/app/__init__.py` — ✗ not indexed
- `src/app/agents/__init__.py` — ✗ not indexed
- `src/app/agents/analyst_claude_agent.py` — ✗ not indexed
- `src/app/agents/coder_openai_pipeline_agent.py` — ✗ not indexed
- `src/app/agents/fact_checker_gemini_agent.py` — ✗ not indexed
- `src/app/agents/football_match_analyzer.py` — ✗ not indexed
- `src/app/agents/football_match_analyzer_gemini_agent.py` — ✗ not indexed
- `src/app/agents/python_coder_agent.py` — ✗ not indexed
- `src/app/agents/python_coder_claude_agent.py` — ✗ not indexed
- `src/app/agents/python_coder_gemini_agent.py` — ✗ not indexed
- `src/app/agents/reviewer_claude_agent.py` — ✗ not indexed
- `src/switchyard/__init__.py` — ✗ not indexed
- `src/switchyard/adapters/__init__.py` — ✗ not indexed
- `src/switchyard/api/__init__.py` — ✗ not indexed
- `src/switchyard/api/app.py` — ✗ not indexed
- `src/switchyard/api/health.py` — ✗ not indexed
- `src/switchyard/application/__init__.py` — ✗ not indexed
- `src/switchyard/cli/__init__.py` — ✗ not indexed
- `src/switchyard/domain/__init__.py` — ✗ not indexed
- `src/switchyard/infrastructure/__init__.py` — ✗ not indexed
- `src/switchyard/infrastructure/db/__init__.py` — ✗ not indexed
- `src/switchyard/infrastructure/repositories/__init__.py` — ✗ not indexed
- `src/switchyard/infrastructure/settings.py` — ✗ not indexed
- `src/switchyard/security/__init__.py` — ✗ not indexed
- `src/switchyard/workers/__init__.py` — ✗ not indexed
- `test/__init__.py` — ✗ not indexed
- `test/conftest.py` — ✗ not indexed
- `test/test_base_claude.py` — ✗ not indexed
- `test/test_base_gemini.py` — ✗ not indexed
- `test/test_base_openai.py` — ✗ not indexed
- `test/test_football_match_analyzer.py` — ✗ not indexed
- `test/test_football_match_analyzer_gemini_agent.py` — ✗ not indexed
- `test/test_pipeline_agents.py` — ✗ not indexed
- `test/test_python_coder_agent.py` — ✗ not indexed
- `test/test_python_coder_claude_agent.py` — ✗ not indexed
- `test/test_python_coder_gemini_agent.py` — ✗ not indexed
- `tests/chaos/__init__.py` — ✗ not indexed
- `tests/conftest.py` — ✗ not indexed
- `tests/contract/__init__.py` — ✗ not indexed
- `tests/integration/__init__.py` — ✗ not indexed
- `tests/security/__init__.py` — ✗ not indexed
- `tests/unit/__init__.py` — ✗ not indexed
- `tests/unit/api/__init__.py` — ✗ not indexed
- `tests/unit/api/test_health.py` — ✗ not indexed
- `tests/unit/fake_provider/__init__.py` — ✗ not indexed
- `tests/unit/fake_provider/support.py` — ✗ not indexed
- `tests/unit/fake_provider/test_app.py` — ✗ not indexed
- `tests/unit/fake_provider/test_isolation.py` — ✗ not indexed
- `tests/unit/fake_provider/test_knobs.py` — ✗ not indexed
- `tests/unit/fake_provider/test_streaming.py` — ✗ not indexed
- `tests/unit/test_layering.py` — ✗ not indexed
- `tests/unit/test_settings.py` — ✗ not indexed

---

## Code Index — Changed Files Only
_No indexed entries for changed files. Run coding-agent to write code and auto-index._

---

## Git Diff
```diff
diff --git a/fake_provider/__init__.py b/fake_provider/__init__.py
new file mode 100644
index 0000000..12f0f81
--- /dev/null
+++ b/fake_provider/__init__.py
@@ -0,0 +1 @@
+"""OpenAI-shaped fake LLM provider for tests; never imported by ``switchyard``."""
diff --git a/fake_provider/app.py b/fake_provider/app.py
new file mode 100644
index 0000000..80cfaa7
--- /dev/null
+++ b/fake_provider/app.py
@@ -0,0 +1,242 @@
+"""ASGI app factory for the OpenAI-shaped fake provider (``fake_provider.app:create_app``)."""
+
+from __future__ import annotations
+
+from collections import Counter
+from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
+from dataclasses import dataclass, field
+from typing import Annotated, Any
+
+from fastapi import Body, FastAPI, Request
+from fastapi.exceptions import RequestValidationError
+from fastapi.responses import JSONResponse, Response, StreamingResponse
+from pydantic import BaseModel, ConfigDict, Field
+
+from fake_provider.knobs import FakeKnobs, HangMode, KnobError, KnobResolver, KnobStore, RngPool
+from fake_provider.streaming import (
+    ChunkStreamer,
+    Clock,
+    CompletionBuilder,
+    CompletionPlan,
+    SystemClock,
+)
+
+MODEL_IDS = ("fake-model", "fake-model-fallback", "fake-model-mini")
+OWNER = "switchyard-fake"
+DEFAULT_429_RETRY_AFTER_S = 1.0
+_ERROR_TYPES = {
+    400: ("invalid_request_error", "invalid_request"),
+    401: ("authentication_error", "invalid_api_key"),
+    429: ("rate_limit_error", "rate_limit_exceeded"),
+    500: ("server_error", "internal_error"),
+    503: ("server_error", "service_unavailable"),
+    529: ("overloaded_error", "overloaded"),
+}
+KnobPatch = Annotated[dict[str, Any], Body()]
+
+
+class ChatCompletionRequest(BaseModel):
+    """The subset of the OpenAI chat request the fake provider inspects."""
+
+    model_config = ConfigDict(extra="allow")
+
+    model: str = Field(min_length=1)
+    messages: list[dict[str, Any]] = Field(min_length=1)
+    stream: bool = False
+    tools: list[dict[str, Any]] | None = None
+
+    def first_tool_name(self) -> str | None:
+        """Return the first declared function name, if any."""
+        for tool in self.tools or []:
+            name = tool.get("function", {}).get("name")
+            if isinstance(name, str) and name:
+                return name
+        return None
+
+
+@dataclass
+class ProviderStats:
+    """Request and connection counters exposed on ``/admin/stats``."""
+
+    requests: int = 0
+    open_connections: int = 0
+    closed_connections: int = 0
+    by_status: Counter[int] = field(default_factory=Counter)
+
+    def snapshot(self) -> dict[str, Any]:
+        """Return a JSON-ready copy with statuses sorted."""
+        return {
+            "requests": self.requests,
+            "open_connections": self.open_connections,
+            "closed_connections": self.closed_connections,
+            "by_status": {str(code): self.by_status[code] for code in sorted(self.by_status)},
+        }
+
+
+class ErrorResponder:
+    """Shapes OpenAI-style error responses."""
+
+    def respond(self, status: int, message: str, retry_after_s: float | None = None) -> Response:
+        """Return a JSON error with an optional ``Retry-After`` header."""
+        err_type, code = _ERROR_TYPES.get(status, ("server_error", "error"))
+        body = {"error": {"message": message, "type": err_type, "param": None, "code": code}}
+        headers = {} if retry_after_s is None else {"Retry-After": f"{retry_after_s:g}"}
+        return JSONResponse(status_code=status, content=body, headers=headers)
+
+
+class CompletionService:
+    """Orchestrates one chat completion: knobs, delays, fault injection, response."""
+
+    def __init__(
+        self,
+        resolver: KnobResolver,
+        rngs: RngPool,
+        clock: Clock,
+        stats: ProviderStats,
+        errors: ErrorResponder,
+    ) -> None:
+        self._resolver = resolver
+        self._rngs = rngs
+        self._clock = clock
+        self._stats = stats
+        self._errors = errors
+        self._builder = CompletionBuilder()
+        self._streamer = ChunkStreamer(self._builder, clock)
+
+    async def handle(self, request: ChatCompletionRequest, headers: Mapping[str, str]) -> Response:
+        """Return the completion (JSON or SSE) or an injected error."""
+        self._stats.requests += 1
+        knobs = self._resolver.resolve(headers)
+        await self._clock.sleep(knobs.latency_ms / 1000)
+        if knobs.hang is not HangMode.NONE and (
+            knobs.hang is HangMode.BEFORE_HEADERS or not request.stream
+        ):
+            await self._clock.hang()
+        injected = self._injected_status(knobs)
+        if injected is not None:
+            return self._record(self._error_for(injected, knobs))
+        plan = CompletionPlan.create(
+            request.model, request.messages, request.first_tool_name(), knobs, self._clock.now()
+        )
+        if request.stream:
+            return self._record(self._stream_response(plan))
+        await self._clock.sleep(knobs.ttft_ms / 1000)
+        return self._record(JSONResponse(self._builder.completion(plan)))
+
+    def _injected_status(self, knobs: FakeKnobs) -> int | None:
+        if knobs.error_rate <= 0:
+            return None
+        roll = self._rngs.for_seed(knobs.seed).random()
+        return knobs.error_status if roll < knobs.error_rate else None
+
+    def _error_for(self, status: int, knobs: FakeKnobs) -> Response:
+        retry_after = knobs.retry_after_s
+        if status == 429 and retry_after is None:
+            retry_after = DEFAULT_429_RETRY_AFTER_S
+        if status not in (429, 503):
+            retry_after = None
+        return self._errors.respond(status, f"fake provider injected HTTP {status}", retry_after)
+
+    def _stream_response(self, plan: CompletionPlan) -> StreamingResponse:
+        headers = {"Cache-Control": "no-cache"}
+        return StreamingResponse(
+            self._tracked(plan), media_type="text/event-stream", headers=headers
+        )
+
+    async def _tracked(self, plan: CompletionPlan) -> AsyncIterator[str]:
+        self._stats.open_connections += 1
+        try:
+            async for frame in self._streamer.stream(plan):
+                yield frame
+        finally:
+            self._stats.open_connections -= 1
+            self._stats.closed_connections += 1
+
+    def _record(self, response: Response) -> Response:
+        self._stats.by_status[response.status_code] += 1
+        return response
+
+
+class AdminService:
+    """Global knob management and stats for test harnesses."""
+
+    def __init__(self, store: KnobStore, rngs: RngPool, stats: ProviderStats) -> None:
+        self._store = store
+        self._rngs = rngs
+        self._stats = stats
+
+    def current(self) -> dict[str, Any]:
+        """Return the effective global knobs."""
+        return FakeKnobs.from_overrides(self._store.overrides()).model_dump(mode="json")
+
+    def update(self, patch: Mapping[str, Any]) -> dict[str, Any]:
+        """Merge ``patch`` into the global knobs and restart the seeded RNG streams."""
+        knobs = self._store.update(patch)
+        self._rngs.reset()
+        return knobs.model_dump(mode="json")
+
+    def reset(self) -> dict[str, Any]:
+        """Clear every global override, restart RNG streams, and return the defaults."""
+        self._store.reset()
+        self._rngs.reset()
+        return self.current()
+
+    def stats(self) -> dict[str, Any]:
+        """Return the counters snapshot."""
+        return self._stats.snapshot()
+
+
+def _models_body() -> dict[str, Any]:
+    data = [{"id": m, "object": "model", "created": 0, "owned_by": OWNER} for m in MODEL_IDS]
+    return {"object": "list", "data": data}
+
+
+def _register_error_handlers(app: FastAPI, errors: ErrorResponder) -> None:
+    async def on_knob_error(_: Request, exc: Exception) -> Response:
+        """Map an invalid knob to an OpenAI 400."""
+        return errors.respond(400, f"invalid fake knob: {exc}")
+
+    async def on_validation_error(_: Request, exc: Exception) -> Response:
+        """Map an invalid request body to an OpenAI 400."""
+        return errors.respond(400, f"invalid request: {exc}")
+
+    app.add_exception_handler(KnobError, on_knob_error)
+    app.add_exception_handler(RequestValidationError, on_validation_error)
+
+
+def _register_admin_routes(app: FastAPI, admin: AdminService) -> None:
+    for path in ("/_knobs", "/admin/config"):
+        app.add_api_route(path, admin.current, methods=["GET"])
+        app.add_api_route(path, _patch_route(admin), methods=["POST", "PUT"])
+        app.add_api_route(path, admin.reset, methods=["DELETE"])
+    app.add_api_route("/admin/stats", admin.stats, methods=["GET"])
+
+
+def _patch_route(admin: AdminService) -> Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]:
+    async def patch_knobs(patch: KnobPatch) -> dict[str, Any]:
+        """Merge a partial knob set into the global knobs."""
+        return admin.update(patch)
+
+    return patch_knobs
+
+
+def create_app(clock: Clock | None = None) -> FastAPI:
+    """Build the fake provider app; pass a fake ``clock`` in tests to skip real sleeps."""
+    active_clock: Clock = clock if clock is not None else SystemClock()
+    store, rngs, stats, errors = KnobStore(), RngPool(), ProviderStats(), ErrorResponder()
+    service = CompletionService(KnobResolver(store), rngs, active_clock, stats, errors)
+    app = FastAPI(title="Switchyard fake provider", docs_url=None, redoc_url=None)
+    _register_error_handlers(app, errors)
+    _register_admin_routes(app, AdminService(store, rngs, stats))
+
+    @app.post("/v1/chat/completions")
+    async def chat_completions(body: ChatCompletionRequest, request: Request) -> Response:
+        """OpenAI ``POST /v1/chat/completions``."""
+        return await service.handle(body, request.headers)
+
+    @app.get("/v1/models")
+    async def list_models() -> dict[str, Any]:
+        """OpenAI ``GET /v1/models``."""
+        return _models_body()
+
+    return app
diff --git a/fake_provider/knobs.py b/fake_provider/knobs.py
new file mode 100644
index 0000000..603c95c
--- /dev/null
+++ b/fake_provider/knobs.py
@@ -0,0 +1,145 @@
+"""Fault-injection knobs for the fake provider: model, global store, per-request resolution."""
+
+from __future__ import annotations
+
+import random
+from collections.abc import Mapping
+from enum import StrEnum
+from typing import Any
+
+from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
+
+HEADER_PREFIX = "x-fake-"
+SUPPORTED_ERROR_STATUSES = frozenset({400, 401, 429, 500, 503, 529})
+DEFAULT_TEXT = "Hello from the Switchyard fake provider. This reply is deterministic."
+MAX_CHUNKS = 1_000
+_TRUE_VALUES = frozenset({"true", "1", "yes", "on"})
+_FALSE_VALUES = frozenset({"false", "0", "no", "off", ""})
+
+
+class KnobError(ValueError):
+    """Raised when a knob name or value is invalid."""
+
+
+class HangMode(StrEnum):
+    """Where the provider stalls until the client disconnects."""
+
+    NONE = "none"
+    BEFORE_HEADERS = "before_headers"
+    BEFORE_FIRST_CHUNK = "before_first_chunk"
+    MID_STREAM = "mid_stream"
+
+
+class FakeKnobs(BaseModel):
+    """Effective knobs for one request (defaults < global store < x-fake-* headers)."""
+
+    model_config = ConfigDict(extra="forbid", frozen=True)
+
+    latency_ms: int = Field(default=0, ge=0)
+    ttft_ms: int = Field(default=0, ge=0)
+    inter_chunk_ms: int = Field(default=0, ge=0)
+    error_rate: float = Field(default=0.0, ge=0.0, le=1.0)
+    error_status: int = 503
+    retry_after_s: float | None = Field(default=None, ge=0.0)
+    hang: HangMode = HangMode.NONE
+    drop_after_chunks: int | None = Field(default=None, ge=0)
+    malformed_at_chunk: int | None = Field(default=None, ge=0)
+    usage: bool = True
+    chunks: int = Field(default=8, ge=1, le=MAX_CHUNKS)
+    text: str = Field(default=DEFAULT_TEXT, min_length=1)
+    tool_call: bool = False
+    seed: int = 0
+
+    @field_validator("error_status")
+    @classmethod
+    def _check_error_status(cls, value: int) -> int:
+        if value not in SUPPORTED_ERROR_STATUSES:
+            raise ValueError(f"error_status must be one of {sorted(SUPPORTED_ERROR_STATUSES)}")
+        return value
+
+    @field_validator("hang", mode="before")
+    @classmethod
+    def _coerce_hang(cls, value: object) -> object:
+        # Boolean shorthand: hang=true means "no first byte" (stall before headers).
+        if isinstance(value, bool):
+            return HangMode.BEFORE_HEADERS if value else HangMode.NONE
+        if isinstance(value, str) and value.lower() in _TRUE_VALUES:
+            return HangMode.BEFORE_HEADERS
+        if isinstance(value, str) and value.lower() in _FALSE_VALUES:
+            return HangMode.NONE
+        return value
+
+    @classmethod
+    def from_overrides(cls, overrides: Mapping[str, Any]) -> FakeKnobs:
+        """Validate ``overrides`` on top of the defaults; raise ``KnobError`` if invalid."""
+        unknown = sorted(set(overrides) - set(cls.model_fields))
+        if unknown:
+            raise KnobError(f"unknown knob(s): {', '.join(unknown)}")
+        try:
+            return cls.model_validate(dict(overrides))
+        except ValidationError as exc:
+            raise KnobError(_describe(exc)) from exc
+
+
+class KnobStore:
+    """Process-wide knob overrides set through the admin endpoints."""
+
+    def __init__(self) -> None:
+        self._overrides: dict[str, Any] = {}
+
+    def overrides(self) -> dict[str, Any]:
+        """Return a copy of the current global overrides."""
+        return dict(self._overrides)
+
+    def update(self, patch: Mapping[str, Any]) -> FakeKnobs:
+        """Merge ``patch`` into the global overrides after validating the result."""
+        merged = {**self._overrides, **patch}
+        knobs = FakeKnobs.from_overrides(merged)
+        self._overrides = {name: getattr(knobs, name) for name in sorted(merged)}
+        return knobs
+
+    def reset(self) -> None:
+        """Drop every global override."""
+        self._overrides = {}
+
+
+class KnobResolver:
+    """Combines global overrides with ``x-fake-*`` request headers."""
+
+    def __init__(self, store: KnobStore) -> None:
+        self._store = store
+
+    def resolve(self, headers: Mapping[str, str]) -> FakeKnobs:
+        """Return the effective knobs; headers win over the global store."""
+        return FakeKnobs.from_overrides({**self._store.overrides(), **self._from_headers(headers)})
+
+    @staticmethod
+    def _from_headers(headers: Mapping[str, str]) -> dict[str, str]:
+        found: dict[str, str] = {}
+        for name, value in headers.items():
+            lowered = name.lower()
+            if lowered.startswith(HEADER_PREFIX):
+                found[lowered[len(HEADER_PREFIX) :].replace("-", "_")] = value
+        return found
+
+
+class RngPool:
+    """One ``random.Random`` per seed, so a request sequence replays identically."""
+
+    def __init__(self) -> None:
+        self._by_seed: dict[int, random.Random] = {}
+
+    def for_seed(self, seed: int) -> random.Random:
+        """Return the RNG stream for ``seed``, creating it on first use."""
+        if seed not in self._by_seed:
+            self._by_seed[seed] = random.Random(seed)  # noqa: S311  # nosec B311 - fault injection, not crypto
+        return self._by_seed[seed]
+
+    def reset(self) -> None:
+        """Restart every seeded stream from the beginning."""
+        self._by_seed = {}
+
+
+def _describe(exc: ValidationError) -> str:
+    parts = [f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in exc.errors()]
+    return "; ".join(sorted(parts))
diff --git a/fake_provider/streaming.py b/fake_provider/streaming.py
new file mode 100644
index 0000000..7937864
--- /dev/null
+++ b/fake_provider/streaming.py
@@ -0,0 +1,207 @@
+"""OpenAI-shaped payload building and SSE chunk streaming with fault injection."""
+
+from __future__ import annotations
+
+import asyncio
+import hashlib
+import json
+import time
+from collections.abc import AsyncIterator, Sequence
+from dataclasses import dataclass
+from typing import Any, Protocol
+
+from fake_provider.knobs import FakeKnobs, HangMode
+
+DONE_FRAME = "data: [DONE]\n\n"
+MALFORMED_FRAME = 'data: {"id": "chatcmpl-malformed", "choices": [\n\n'
+DEFAULT_TOOL_NAME = "get_weather"
+TOOL_ARGUMENTS = '{"location": "Paris", "unit": "celsius"}'
+
+
+class StreamDroppedError(ConnectionError):
+    """Raised mid-stream so the server aborts the connection without ``[DONE]``."""
+
+
+class Clock(Protocol):
+    """Time source; injected so tests never really sleep."""
+
+    def now(self) -> float:
+        """Return the current UNIX time in seconds."""
+        ...
+
+    async def sleep(self, seconds: float) -> None:
+        """Wait ``seconds``."""
+        ...
+
+    async def hang(self) -> None:
+        """Wait until cancelled (the client disconnects)."""
+        ...
+
+
+class SystemClock:
+    """Real wall clock and asyncio sleeps."""
+
+    def now(self) -> float:
+        """Return the current UNIX time in seconds."""
+        return time.time()
+
+    async def sleep(self, seconds: float) -> None:
+        """Wait ``seconds`` (no-op for non-positive values)."""
+        if seconds > 0:
+            await asyncio.sleep(seconds)
+
+    async def hang(self) -> None:
+        """Wait until the surrounding task is cancelled."""
+        await asyncio.Event().wait()
+
+
+@dataclass(frozen=True)
+class CompletionPlan:
+    """Everything needed to render one completion deterministically."""
+
+    completion_id: str
+    model: str
+    created: int
+    tool_name: str
+    prompt_tokens: int
+    knobs: FakeKnobs
+
+    @classmethod
+    def create(
+        cls,
+        model: str,
+        messages: Sequence[Any],
+        tool_name: str | None,
+        knobs: FakeKnobs,
+        now: float,
+    ) -> CompletionPlan:
+        """Build a plan; the id is a hash of seed, model and messages so replays match."""
+        if not model:
+            raise ValueError("model must not be empty")
+        canonical = json.dumps([knobs.seed, model, list(messages)], sort_keys=True, default=str)
+        digest = hashlib.sha256(canonical.encode()).hexdigest()[:24]
+        return cls(
+            completion_id=f"chatcmpl-fake-{digest}",
+            model=model,
+            created=int(now),
+            tool_name=tool_name or DEFAULT_TOOL_NAME,
+            prompt_tokens=sum(len(json.dumps(m, default=str).split()) for m in messages),
+            knobs=knobs,
+        )
+
+
+class CompletionBuilder:
+    """Pure transformation from a ``CompletionPlan`` to OpenAI wire payloads."""
+
+    def pieces(self, plan: CompletionPlan) -> list[str]:
+        """Split the text (or tool arguments) into ``knobs.chunks`` non-empty pieces."""
+        source = TOOL_ARGUMENTS if plan.knobs.tool_call else plan.knobs.text
+        count = min(plan.knobs.chunks, len(source))
+        size, extra = divmod(len(source), count)
+        bounds = [i * size + min(i, extra) for i in range(count + 1)]
+        return [source[bounds[i] : bounds[i + 1]] for i in range(count)]
+
+    def completion(self, plan: CompletionPlan) -> dict[str, Any]:
+        """Return a non-streaming ``chat.completion`` body."""
+        message: dict[str, Any] = {"role": "assistant", "content": plan.knobs.text}
+        if plan.knobs.tool_call:
+            message = {"role": "assistant", "content": None, "tool_calls": [self._tool_call(plan)]}
+        body: dict[str, Any] = {
+            **self._envelope(plan, "chat.completion"),
+            "choices": [{"index": 0, "message": message, "finish_reason": self._finish(plan)}],
+        }
+        if plan.knobs.usage:
+            body["usage"] = self.usage(plan)
+        return body
+
+    def chunks(self, plan: CompletionPlan) -> list[dict[str, Any]]:
+        """Return every ``chat.completion.chunk`` payload, in order, without ``[DONE]``."""
+        deltas = [self._first_delta(plan)]
+        deltas += [self._piece_delta(plan, piece) for piece in self.pieces(plan)]
+        frames = [self._chunk(plan, delta, None) for delta in deltas]
+        frames.append(self._chunk(plan, {}, self._finish(plan)))
+        if plan.knobs.usage:
+            frames.append({**self._envelope(plan, "chat.completion.chunk"), "choices": []})
+            frames[-1]["usage"] = self.usage(plan)
+        return frames
+
+    def usage(self, plan: CompletionPlan) -> dict[str, int]:
+        """Return deterministic token counts for the plan."""
+        completion_tokens = len(self.pieces(plan))
+        return {
+            "prompt_tokens": plan.prompt_tokens,
+            "completion_tokens": completion_tokens,
+            "total_tokens": plan.prompt_tokens + completion_tokens,
+        }
+
+    def _first_delta(self, plan: CompletionPlan) -> dict[str, Any]:
+        if not plan.knobs.tool_call:
+            return {"role": "assistant", "content": ""}
+        call = self._tool_call(plan)
+        call["function"]["arguments"] = ""
+        return {"role": "assistant", "content": None, "tool_calls": [{"index": 0, **call}]}
+
+    @staticmethod
+    def _piece_delta(plan: CompletionPlan, piece: str) -> dict[str, Any]:
+        if plan.knobs.tool_call:
+            return {"tool_calls": [{"index": 0, "function": {"arguments": piece}}]}
+        return {"content": piece}
+
+    def _chunk(
+        self, plan: CompletionPlan, delta: dict[str, Any], finish: str | None
+    ) -> dict[str, Any]:
+        choice = {"index": 0, "delta": delta, "finish_reason": finish}
+        return {**self._envelope(plan, "chat.completion.chunk"), "choices": [choice]}
+
+    @staticmethod
+    def _envelope(plan: CompletionPlan, obj: str) -> dict[str, Any]:
+        return {
+            "id": plan.completion_id,
+            "object": obj,
+            "created": plan.created,
+            "model": plan.model,
+        }
+
+    @staticmethod
+    def _tool_call(plan: CompletionPlan) -> dict[str, Any]:
+        call_id = f"call_{plan.completion_id[-12:]}"
+        function = {"name": plan.tool_name, "arguments": TOOL_ARGUMENTS}
+        return {"id": call_id, "type": "function", "function": function}
+
+    @staticmethod
+    def _finish(plan: CompletionPlan) -> str:
+        return "tool_calls" if plan.knobs.tool_call else "stop"
+
+
+class ChunkStreamer:
+    """Turns chunk payloads into SSE frames, honouring timing and stream-fault knobs."""
+
+    def __init__(self, builder: CompletionBuilder, clock: Clock) -> None:
+        self._builder = builder
+        self._clock = clock
+
+    async def stream(self, plan: CompletionPlan) -> AsyncIterator[str]:
+        """Yield SSE frames ending with ``data: [DONE]`` unless a fault cuts the stream."""
+        knobs = plan.knobs
+        await self._clock.sleep(knobs.ttft_ms / 1000)
+        if knobs.hang is HangMode.BEFORE_FIRST_CHUNK:
+            await self._clock.hang()
+        for index, payload in enumerate(self._builder.chunks(plan)):
+            await self._before_frame(knobs, index)
+            yield self._render(knobs, index, payload)
+        yield DONE_FRAME
+
+    async def _before_frame(self, knobs: FakeKnobs, index: int) -> None:
+        if knobs.drop_after_chunks is not None and index >= knobs.drop_after_chunks:
+            raise StreamDroppedError(f"fake stream dropped after {index} chunks")
+        if index == 0:
+            return
+        if knobs.hang is HangMode.MID_STREAM and index == 1:
+            await self._clock.hang()
+        await self._clock.sleep(knobs.inter_chunk_ms / 1000)
+
+    @staticmethod
+    def _render(knobs: FakeKnobs, index: int, payload: dict[str, Any]) -> str:
+        if knobs.malformed_at_chunk == index:
+            return MALFORMED_FRAME
+        return f"data: {json.dumps(payload, separators=(',', ':'))}\n\n"
diff --git a/src/switchyard/__init__.py b/src/switchyard/__init__.py
new file mode 100644
index 0000000..e69de29
diff --git a/src/switchyard/adapters/__init__.py b/src/switchyard/adapters/__init__.py
new file mode 100644
index 0000000..e69de29
diff --git a/src/switchyard/api/__init__.py b/src/switchyard/api/__init__.py
new file mode 100644
index 0000000..e69de29
diff --git a/src/switchyard/api/app.py b/src/switchyard/api/app.py
new file mode 100644
index 0000000..4c086e5
--- /dev/null
+++ b/src/switchyard/api/app.py
@@ -0,0 +1,31 @@
+"""FastAPI application factory for the gateway."""
+
+from __future__ import annotations
+
+from typing import TYPE_CHECKING
+
+from fastapi import FastAPI
+
+from switchyard.api.health import ReadinessChecker, build_health_router
+
+if TYPE_CHECKING:
+    from switchyard.infrastructure.settings import Settings
+
+
+def create_app(settings: Settings | None = None) -> FastAPI:
+    """Build the gateway app; ``uvicorn --factory`` calls this with no arguments.
+
+    M0 scope: health endpoints only. Lifespan wiring (DB, Redis, workers) lands with T14.
+    """
+    resolved = settings if settings is not None else _load_settings()
+    app = FastAPI(title="Switchyard", version="0.1.0")
+    app.state.settings = resolved
+    app.include_router(build_health_router(ReadinessChecker()))
+    return app
+
+
+def _load_settings() -> Settings:
+    # Lazy import: Settings is only needed at runtime when uvicorn passes no settings.
+    from switchyard.infrastructure.settings import Settings
+
+    return Settings()
diff --git a/src/switchyard/api/health.py b/src/switchyard/api/health.py
new file mode 100644
index 0000000..518093f
--- /dev/null
+++ b/src/switchyard/api/health.py
@@ -0,0 +1,108 @@
+"""Liveness and readiness endpoints (FR-03)."""
+
+from __future__ import annotations
+
+import logging
+from collections.abc import Sequence
+from enum import StrEnum
+from typing import Literal, Protocol
+
+from fastapi import APIRouter, Response, status
+from pydantic import BaseModel, ConfigDict
+
+logger = logging.getLogger(__name__)
+
+# Dependencies reported as not_configured until their probes land (T14: database, redis).
+EXPECTED_DEPENDENCIES: tuple[str, ...] = ("database", "redis")
+
+
+class ProbeStatus(StrEnum):
+    """Outcome of a single readiness dependency check."""
+
+    OK = "ok"
+    FAILED = "failed"
+    NOT_CONFIGURED = "not_configured"
+
+
+class ReadinessProbe(Protocol):
+    """An async dependency check registered with the readiness endpoint."""
+
+    @property
+    def name(self) -> str:
+        """Dependency name reported in the readiness payload."""
+        ...
+
+    async def check(self) -> bool:
+        """Return True when the dependency is usable."""
+        ...
+
+
+class LivenessReport(BaseModel):
+    """Body of ``GET /healthz``."""
+
+    model_config = ConfigDict(frozen=True)
+
+    status: Literal["ok"] = "ok"
+
+
+class ReadinessReport(BaseModel):
+    """Body of ``GET /readyz``; ``checks`` is ordered by dependency name."""
+
+    model_config = ConfigDict(frozen=True)
+
+    status: Literal["ready", "not_ready"]
+    checks: dict[str, ProbeStatus]
+
+
+class ReadinessChecker:
+    """Runs registered probes and reports every expected dependency."""
+
+    def __init__(
+        self,
+        probes: Sequence[ReadinessProbe] = (),
+        expected: Sequence[str] = EXPECTED_DEPENDENCIES,
+    ) -> None:
+        names = [probe.name for probe in probes]
+        if len(names) != len(set(names)):
+            raise ValueError(f"duplicate readiness probe names: {sorted(names)}")
+        self._probes = tuple(probes)
+        self._expected = tuple(expected)
+
+    async def check(self) -> ReadinessReport:
+        """Run every probe once and aggregate the results."""
+        results = {name: ProbeStatus.NOT_CONFIGURED for name in self._expected}
+        for probe in self._probes:
+            results[probe.name] = await self._run_probe(probe)
+        ready = ProbeStatus.FAILED not in results.values()
+        return ReadinessReport(
+            status="ready" if ready else "not_ready",
+            checks=dict(sorted(results.items())),
+        )
+
+    @staticmethod
+    async def _run_probe(probe: ReadinessProbe) -> ProbeStatus:
+        try:
+            healthy = await probe.check()
+        except Exception:
+            # A probe failure must surface as not_ready, never as a 500 from /readyz.
+            logger.exception("readiness probe %s raised", probe.name)
+            return ProbeStatus.FAILED
+        return ProbeStatus.OK if healthy else ProbeStatus.FAILED
+
+
+def build_health_router(checker: ReadinessChecker) -> APIRouter:
+    """Create the router serving ``/healthz`` and ``/readyz``."""
+    router = APIRouter(tags=["health"])
+
+    @router.get("/healthz")
+    async def healthz() -> LivenessReport:
+        return LivenessReport()
+
+    @router.get("/readyz")
+    async def readyz(response: Response) -> ReadinessReport:
+        report = await checker.check()
+        if report.status != "ready":
+            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
+        return report
+
+    return router
diff --git a/src/switchyard/application/__init__.py b/src/switchyard/application/__init__.py
new file mode 100644
index 0000000..e69de29
diff --git a/src/switchyard/cli/__init__.py b/src/switchyard/cli/__init__.py
new file mode 100644
index 0000000..e69de29
diff --git a/src/switchyard/domain/__init__.py b/src/switchyard/domain/__init__.py
new file mode 100644
index 0000000..e69de29
diff --git a/src/switchyard/infrastructure/__init__.py b/src/switchyard/infrastructure/__init__.py
new file mode 100644
index 0000000..e69de29
diff --git a/src/switchyard/infrastructure/db/__init__.py b/src/switchyard/infrastructure/db/__init__.py
new file mode 100644
index 0000000..e69de29
diff --git a/src/switchyard/infrastructure/repositories/__init__.py b/src/switchyard/infrastructure/repositories/__init__.py
new file mode 100644
index 0000000..e69de29
diff --git a/src/switchyard/infrastructure/settings.py b/src/switchyard/infrastructure/settings.py
new file mode 100644
index 0000000..6c46a41
--- /dev/null
+++ b/src/switchyard/infrastructure/settings.py
@@ -0,0 +1,45 @@
+"""Process configuration loaded from ``SWITCHYARD_*`` environment variables."""
+
+from __future__ import annotations
+
+from pathlib import Path
+from typing import Literal
+
+from pydantic import AnyUrl, Field, PositiveInt
+from pydantic_settings import BaseSettings, SettingsConfigDict
+
+DEFAULT_MAX_BODY_BYTES = 1_048_576  # OQ-05: 1 MiB, larger bodies get 413
+DEFAULT_MAX_MESSAGES = 256
+DEFAULT_MAX_TOOL_PAYLOAD_BYTES = 65_536  # OQ-05: 64 KiB
+DEFAULT_RPM = 600
+DEFAULT_TPM = 200_000
+DEFAULT_CONCURRENCY = 20
+
+
+class Settings(BaseSettings):
+    """Typed gateway settings; invalid or unknown values fail at construction.
+
+    Only fields that need no I/O live here for now. Database/Redis fields are added
+    by T14 and API-key HMAC fields by T21.
+    """
+
+    # No env_file: production config comes only from the process environment.
+    model_config = SettingsConfigDict(
+        env_prefix="SWITCHYARD_",
+        extra="forbid",
+        frozen=True,
+    )
+
+    models_path: Path = Path("config/models.yaml")
+    max_body_bytes: PositiveInt = DEFAULT_MAX_BODY_BYTES
+    max_messages: PositiveInt = DEFAULT_MAX_MESSAGES
+    max_tool_payload_bytes: PositiveInt = DEFAULT_MAX_TOOL_PAYLOAD_BYTES
+    # "model" caps max_tokens at the selected model's max_output_tokens (OQ-05).
+    max_tokens_cap: Literal["model"] = "model"
+    otel_exporter_otlp_endpoint: AnyUrl = AnyUrl("http://otel-collector:4317")
+    aws_region: str = Field(default="us-east-1", min_length=1)
+    # "env" is test/dev only: provider keys come from SWITCHYARD_PROVIDER_KEY_<PROVIDER>.
+    secrets_backend: Literal["aws", "env"] = "aws"
+    default_rpm: PositiveInt = DEFAULT_RPM
+    default_tpm: PositiveInt = DEFAULT_TPM
+    default_concurrency: PositiveInt = DEFAULT_CONCURRENCY
diff --git a/src/switchyard/security/__init__.py b/src/switchyard/security/__init__.py
new file mode 100644
index 0000000..e69de29
diff --git a/src/switchyard/workers/__init__.py b/src/switchyard/workers/__init__.py
new file mode 100644
index 0000000..e69de29
diff --git a/tests/chaos/__init__.py b/tests/chaos/__init__.py
new file mode 100644
index 0000000..e69de29
diff --git a/tests/conftest.py b/tests/conftest.py
new file mode 100644
index 0000000..b9a1a60
--- /dev/null
+++ b/tests/conftest.py
@@ -0,0 +1,19 @@
+"""Shared pytest fixtures for all test suites."""
+
+from __future__ import annotations
+
+import os
+from collections.abc import Iterator
+
+import pytest
+
+SETTINGS_ENV_PREFIX = "SWITCHYARD_"
+
+
+@pytest.fixture(autouse=True)
+def clean_switchyard_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
+    """Remove every ``SWITCHYARD_*`` variable so tests never see the host config."""
+    for name in sorted(os.environ):
+        if name.startswith(SETTINGS_ENV_PREFIX):
+            monkeypatch.delenv(name, raising=False)
+    yield
diff --git a/tests/contract/__init__.py b/tests/contract/__init__.py
new file mode 100644
index 0000000..e69de29
diff --git a/tests/integration/__init__.py b/tests/integration/__init__.py
new file mode 100644
index 0000000..e69de29
diff --git a/tests/security/__init__.py b/tests/security/__init__.py
new file mode 100644
index 0000000..e69de29
diff --git a/tests/unit/__init__.py b/tests/unit/__init__.py
new file mode 100644
index 0000000..e69de29
diff --git a/tests/unit/api/__init__.py b/tests/unit/api/__init__.py
new file mode 100644
index 0000000..e69de29
diff --git a/tests/unit/api/test_health.py b/tests/unit/api/test_health.py
new file mode 100644
index 0000000..c788cd5
--- /dev/null
+++ b/tests/unit/api/test_health.py
@@ -0,0 +1,106 @@
+"""Unit tests for the health endpoints and ``create_app`` (FR-03)."""
+
+from __future__ import annotations
+
+import asyncio
+import os
+import unittest
+from dataclasses import dataclass
+from unittest.mock import patch
+
+import pytest
+from fastapi import FastAPI
+from fastapi.testclient import TestClient
+
+from switchyard.api.app import create_app
+from switchyard.api.health import (
+    ProbeStatus,
+    ReadinessChecker,
+    build_health_router,
+)
+from switchyard.infrastructure.settings import Settings
+
+
+@dataclass(frozen=True)
+class StubProbe:
+    """Readiness probe with a fixed outcome."""
+
+    name: str
+    healthy: bool = True
+    error: bool = False
+
+    async def check(self) -> bool:
+        if self.error:
+            raise ConnectionError("unreachable")
+        return self.healthy
+
+
+def _client_for(checker: ReadinessChecker) -> TestClient:
+    app = FastAPI()
+    app.include_router(build_health_router(checker))
+    return TestClient(app)
+
+
+@pytest.mark.unit
+class CreateAppTest(unittest.TestCase):
+    """The factory serves health endpoints with injected or env-loaded settings."""
+
+    def setUp(self) -> None:
+        self.settings = Settings(secrets_backend="env")
+        self.client = TestClient(create_app(self.settings))
+
+    def test_healthz_returns_ok(self) -> None:
+        response = self.client.get("/healthz")
+        self.assertEqual(200, response.status_code)
+        self.assertEqual({"status": "ok"}, response.json())
+
+    def test_readyz_without_probes_reports_not_configured(self) -> None:
+        response = self.client.get("/readyz")
+        self.assertEqual(200, response.status_code)
+        expected_checks = {"database": "not_configured", "redis": "not_configured"}
+        self.assertEqual({"status": "ready", "checks": expected_checks}, response.json())
+
+    def test_injected_settings_are_kept_on_state(self) -> None:
+        app = create_app(self.settings)
+        self.assertIs(self.settings, app.state.settings)
+
+    def test_factory_without_arguments_loads_settings_from_env(self) -> None:
+        with patch.dict(os.environ, {"SWITCHYARD_SECRETS_BACKEND": "env"}, clear=True):
+            app = create_app()
+        self.assertEqual("env", app.state.settings.secrets_backend)
+
+
+@pytest.mark.unit
+class ReadinessCheckerTest(unittest.TestCase):
+    """Probe aggregation, ordering and failure handling."""
+
+    def test_healthy_probes_report_ok_sorted_by_name(self) -> None:
+        checker = ReadinessChecker([StubProbe("redis"), StubProbe("database")])
+        report = asyncio.run(checker.check())
+        self.assertEqual("ready", report.status)
+        self.assertEqual(["database", "redis"], list(report.checks))
+        self.assertEqual({ProbeStatus.OK}, set(report.checks.values()))
+
+    def test_unhealthy_probe_returns_503(self) -> None:
+        client = _client_for(ReadinessChecker([StubProbe("database", healthy=False)]))
+        response = client.get("/readyz")
+        self.assertEqual(503, response.status_code)
+        self.assertEqual("not_ready", response.json()["status"])
+        self.assertEqual("failed", response.json()["checks"]["database"])
+        self.assertEqual("not_configured", response.json()["checks"]["redis"])
+
+    def test_raising_probe_is_reported_failed(self) -> None:
+        checker = ReadinessChecker([StubProbe("redis", error=True)])
+        with self.assertLogs("switchyard.api.health", level="ERROR"):
+            report = asyncio.run(checker.check())
+        self.assertEqual("not_ready", report.status)
+        self.assertEqual(ProbeStatus.FAILED, report.checks["redis"])
+
+    def test_extra_probe_is_included(self) -> None:
+        checker = ReadinessChecker([StubProbe("policy")], expected=())
+        report = asyncio.run(checker.check())
+        self.assertEqual({"policy": ProbeStatus.OK}, report.checks)
+
+    def test_duplicate_probe_names_are_rejected(self) -> None:
+        with self.assertRaises(ValueError):
+            ReadinessChecker([StubProbe("redis"), StubProbe("redis")])
diff --git a/tests/unit/fake_provider/__init__.py b/tests/unit/fake_provider/__init__.py
new file mode 100644
index 0000000..e69de29
diff --git a/tests/unit/fake_provider/support.py b/tests/unit/fake_provider/support.py
new file mode 100644
index 0000000..ec2d01e
--- /dev/null
+++ b/tests/unit/fake_provider/support.py
@@ -0,0 +1,30 @@
+"""Shared fakes for fake_provider tests: a clock that never really sleeps."""
+
+from __future__ import annotations
+
+
+class HangCalledError(Exception):
+    """Raised by ``FakeClock.hang`` so a stall is observable without waiting."""
+
+
+class FakeClock:
+    """Records requested sleeps and turns ``hang`` into an immediate exception."""
+
+    NOW = 1_700_000_000.5
+
+    def __init__(self) -> None:
+        self.sleeps: list[float] = []
+        self.hangs = 0
+
+    def now(self) -> float:
+        """Return a fixed timestamp."""
+        return self.NOW
+
+    async def sleep(self, seconds: float) -> None:
+        """Record ``seconds`` and return immediately."""
+        self.sleeps.append(seconds)
+
+    async def hang(self) -> None:
+        """Record the stall and raise instead of waiting forever."""
+        self.hangs += 1
+        raise HangCalledError
diff --git a/tests/unit/fake_provider/test_app.py b/tests/unit/fake_provider/test_app.py
new file mode 100644
index 0000000..50c7394
--- /dev/null
+++ b/tests/unit/fake_provider/test_app.py
@@ -0,0 +1,202 @@
+"""Unit tests for the ``fake_provider.app`` HTTP surface via ``httpx.ASGITransport``."""
+
+from __future__ import annotations
+
+import json
+import random
+import unittest
+from typing import Any
+
+import httpx
+import pytest
+from fake_provider.app import MODEL_IDS, create_app
+from fake_provider.streaming import DONE_FRAME, MALFORMED_FRAME, StreamDroppedError
+
+from .support import FakeClock, HangCalledError
+
+CHAT_PATH = "/v1/chat/completions"
+BODY: dict[str, Any] = {"model": "fake-model", "messages": [{"role": "user", "content": "hi"}]}
+
+
+class FakeProviderTestCase(unittest.IsolatedAsyncioTestCase):
+    """Builds a fresh app with a fake clock per test."""
+
+    def setUp(self) -> None:
+        self.clock = FakeClock()
+        self.app = create_app(clock=self.clock)
+
+    def _client(self, raise_app_exceptions: bool = True) -> httpx.AsyncClient:
+        transport = httpx.ASGITransport(app=self.app, raise_app_exceptions=raise_app_exceptions)
+        return httpx.AsyncClient(transport=transport, base_url="http://fake")
+
+    async def _chat(self, knobs: dict[str, str] | None = None, **body: object) -> httpx.Response:
+        headers = {f"x-fake-{k.replace('_', '-')}": v for k, v in (knobs or {}).items()}
+        async with self._client() as client:
+            return await client.post(CHAT_PATH, json={**BODY, **body}, headers=headers)
+
+    @staticmethod
+    def _frames(response: httpx.Response) -> list[str]:
+        return [f"{block}\n\n" for block in response.text.split("\n\n") if block]
+
+
+@pytest.mark.unit
+class CompletionsTest(FakeProviderTestCase):
+    """OpenAI-shaped success responses."""
+
+    async def test_non_stream_completion(self) -> None:
+        response = await self._chat()
+        self.assertEqual(200, response.status_code)
+        body = response.json()
+        self.assertEqual("chat.completion", body["object"])
+        self.assertEqual("fake-model", body["model"])
+        self.assertEqual("assistant", body["choices"][0]["message"]["role"])
+        self.assertIn("usage", body)
+
+    async def test_stream_is_sse_ending_with_done_and_usage(self) -> None:
+        response = await self._chat(stream=True)
+        self.assertTrue(response.headers["content-type"].startswith("text/event-stream"))
+        frames = self._frames(response)
+        self.assertEqual(DONE_FRAME, frames[-1])
+        payloads = [json.loads(f[len("data: ") :]) for f in frames[:-1]]
+        self.assertTrue(all(p["object"] == "chat.completion.chunk" for p in payloads))
+        self.assertEqual([], payloads[-1]["choices"])
+        self.assertIn("usage", payloads[-1])
+
+    async def test_usage_off(self) -> None:
+        self.assertNotIn("usage", (await self._chat({"usage": "false"})).json())
+        frames = self._frames(await self._chat({"usage": "false"}, stream=True))
+        self.assertNotIn('"usage"', "".join(frames))
+
+    async def test_tool_call_uses_declared_tool_name(self) -> None:
+        tools = [{"type": "function", "function": {"name": "search_docs"}}]
+        body = (await self._chat({"tool_call": "true"}, tools=tools)).json()
+        call = body["choices"][0]["message"]["tool_calls"][0]
+        self.assertEqual("search_docs", call["function"]["name"])
+        self.assertEqual("tool_calls", body["choices"][0]["finish_reason"])
+        stream = "".join(self._frames(await self._chat({"tool_call": "1"}, stream=True)))
+        self.assertIn('"tool_calls"', stream)
+
+    async def test_latency_and_ttft_are_slept_via_clock(self) -> None:
+        await self._chat({"latency_ms": "250", "ttft_ms": "40"})
+        self.assertEqual([0.25, 0.04], self.clock.sleeps)
+
+    async def test_list_models(self) -> None:
+        async with self._client() as client:
+            body = (await client.get("/v1/models")).json()
+        self.assertEqual("list", body["object"])
+        self.assertEqual(list(MODEL_IDS), [m["id"] for m in body["data"]])
+
+
+@pytest.mark.unit
+class ErrorInjectionTest(FakeProviderTestCase):
+    """Seeded error_rate and the supported error statuses."""
+
+    async def test_error_rate_is_seeded_and_reproducible(self) -> None:
+        rng = random.Random(7)  # noqa: S311 - reference stream
+        expected = [503 if rng.random() < 0.5 else 200 for _ in range(12)]
+        knobs = {"error_rate": "0.5", "seed": "7"}
+        statuses = [(await self._chat(knobs)).status_code for _ in range(12)]
+        self.assertEqual(expected, statuses)
+        self.assertIn(200, statuses)
+        self.assertIn(503, statuses)
+
+    async def test_global_knob_update_restarts_seeded_stream(self) -> None:
+        async with self._client() as client:
+            await client.post("/_knobs", json={"error_rate": 0.5, "seed": 3})
+            first = [(await client.post(CHAT_PATH, json=BODY)).status_code for _ in range(6)]
+            await client.post("/_knobs", json={})
+            second = [(await client.post(CHAT_PATH, json=BODY)).status_code for _ in range(6)]
+        self.assertEqual(first, second)
+
+    async def test_429_carries_retry_after(self) -> None:
+        response = await self._chat({"error_rate": "1", "error_status": "429"})
+        self.assertEqual(429, response.status_code)
+        self.assertEqual("1", response.headers["retry-after"])
+        self.assertEqual("rate_limit_error", response.json()["error"]["type"])
+        knobs = {"error_rate": "1", "error_status": "429", "retry_after_s": "2.5"}
+        custom = await self._chat(knobs)
+        self.assertEqual("2.5", custom.headers["retry-after"])
+
+    async def test_503_retry_after_only_when_set(self) -> None:
+        plain = await self._chat({"error_rate": "1", "error_status": "503"})
+        self.assertEqual(503, plain.status_code)
+        self.assertNotIn("retry-after", plain.headers)
+        timed = await self._chat({"error_rate": "1", "error_status": "503", "retry_after_s": "4"})
+        self.assertEqual("4", timed.headers["retry-after"])
+
+    async def test_529_is_overloaded_without_retry_after(self) -> None:
+        knobs = {"error_rate": "1", "error_status": "529", "retry_after_s": "4"}
+        response = await self._chat(knobs)
+        self.assertEqual(529, response.status_code)
+        self.assertEqual("overloaded_error", response.json()["error"]["type"])
+        self.assertNotIn("retry-after", response.headers)
+
+
+@pytest.mark.unit
+class StreamFaultTest(FakeProviderTestCase):
+    """Hang, drop and malformed-chunk knobs through the HTTP surface."""
+
+    async def test_hang_before_headers_sends_no_first_byte(self) -> None:
+        for stream in (False, True):
+            with self.subTest(stream=stream), self.assertRaises(HangCalledError):
+                await self._chat({"hang": "true"}, stream=stream)
+        self.assertEqual(2, self.clock.hangs)
+
+    async def test_non_stream_hangs_for_any_hang_mode(self) -> None:
+        with self.assertRaises(HangCalledError):
+            await self._chat({"hang": "mid_stream"})
+
+    async def test_drop_after_chunks_has_no_done(self) -> None:
+        headers = {"x-fake-drop-after-chunks": "3"}
+        async with self._client(raise_app_exceptions=False) as client:
+            response = await client.post(CHAT_PATH, json={**BODY, "stream": True}, headers=headers)
+        frames = self._frames(response)
+        self.assertEqual(3, len(frames))
+        self.assertNotIn(DONE_FRAME, frames)
+        with self.assertRaises(StreamDroppedError):
+            await self._chat({"drop_after_chunks": "3"}, stream=True)
+
+    async def test_malformed_chunk(self) -> None:
+        frames = self._frames(await self._chat({"malformed_at_chunk": "1"}, stream=True))
+        self.assertEqual(MALFORMED_FRAME, frames[1])
+        self.assertEqual(DONE_FRAME, frames[-1])
+
+
+@pytest.mark.unit
+class AdminAndValidationTest(FakeProviderTestCase):
+    """Global knobs, stats and fail-fast validation."""
+
+    async def test_global_knobs_apply_and_headers_win(self) -> None:
+        async with self._client() as client:
+            updated = (await client.post("/_knobs", json={"error_rate": 1})).json()
+            self.assertEqual(1.0, updated["error_rate"])
+            self.assertEqual(503, (await client.post(CHAT_PATH, json=BODY)).status_code)
+            ok = await client.post(CHAT_PATH, json=BODY, headers={"x-fake-error-rate": "0"})
+            self.assertEqual(200, ok.status_code)
+            await client.put("/admin/config", json={"latency_ms": 5})
+            self.assertEqual(5, (await client.get("/_knobs")).json()["latency_ms"])
+            reset = (await client.delete("/_knobs")).json()
+        self.assertEqual(0.0, reset["error_rate"])
+
+    async def test_invalid_knobs_return_400(self) -> None:
+        self.assertEqual(400, (await self._chat({"bogus": "1"})).status_code)
+        async with self._client() as client:
+            response = await client.post("/_knobs", json={"error_status": 418})
+        self.assertEqual(400, response.status_code)
+        self.assertEqual("invalid_request_error", response.json()["error"]["type"])
+
+    async def test_invalid_body_returns_400(self) -> None:
+        async with self._client() as client:
+            response = await client.post(CHAT_PATH, json={"model": "fake-model", "messages": []})
+        self.assertEqual(400, response.status_code)
+
+    async def test_stats_count_requests_statuses_and_connections(self) -> None:
+        await self._chat()
+        await self._chat(stream=True)
+        await self._chat({"error_rate": "1"})
+        async with self._client() as client:
+            stats = (await client.get("/admin/stats")).json()
+        self.assertEqual(3, stats["requests"])
+        self.assertEqual({"200": 2, "503": 1}, stats["by_status"])
+        self.assertEqual(0, stats["open_connections"])
+        self.assertEqual(1, stats["closed_connections"])
diff --git a/tests/unit/fake_provider/test_isolation.py b/tests/unit/fake_provider/test_isolation.py
new file mode 100644
index 0000000..c179cfb
--- /dev/null
+++ b/tests/unit/fake_provider/test_isolation.py
@@ -0,0 +1,44 @@
+"""Guard: the gateway package never imports the fake provider."""
+
+from __future__ import annotations
+
+import ast
+import unittest
+from pathlib import Path
+
+import pytest
+
+SWITCHYARD_DIR = Path(__file__).resolve().parents[3] / "src" / "switchyard"
+FORBIDDEN_ROOT = "fake_provider"
+
+
+class ImportScanner:
+    """Collects absolute module names imported by a Python source file."""
+
+    def imports(self, path: Path) -> list[str]:
+        """Return sorted, de-duplicated absolute imports of ``path``."""
+        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
+        names: set[str] = set()
+        for node in ast.walk(tree):
+            if isinstance(node, ast.Import):
+                names.update(alias.name for alias in node.names)
+            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
+                names.add(node.module)
+        return sorted(names)
+
+
+@pytest.mark.unit
+class SwitchyardDoesNotImportFakeProviderTest(unittest.TestCase):
+    """``fake_provider`` is test infrastructure only."""
+
+    def test_no_switchyard_module_imports_fake_provider(self) -> None:
+        scanner = ImportScanner()
+        sources = sorted(SWITCHYARD_DIR.rglob("*.py"))
+        self.assertTrue(sources, f"no sources found under {SWITCHYARD_DIR}")
+        offenders = [
+            f"{path.relative_to(SWITCHYARD_DIR)}: {name}"
+            for path in sources
+            for name in scanner.imports(path)
+            if name == FORBIDDEN_ROOT or name.startswith(f"{FORBIDDEN_ROOT}.")
+        ]
+        self.assertEqual([], offenders)
diff --git a/tests/unit/fake_provider/test_knobs.py b/tests/unit/fake_provider/test_knobs.py
new file mode 100644
index 0000000..de5a882
--- /dev/null
+++ b/tests/unit/fake_provider/test_knobs.py
@@ -0,0 +1,101 @@
+"""Unit tests for ``fake_provider.knobs``."""
+
+from __future__ import annotations
+
+import random
+import unittest
+
+import pytest
+from fake_provider.knobs import (
+    FakeKnobs,
+    HangMode,
+    KnobError,
+    KnobResolver,
+    KnobStore,
+    RngPool,
+)
+
+
+@pytest.mark.unit
+class FakeKnobsTest(unittest.TestCase):
+    """Defaults, validation and coercion of a single knob set."""
+
+    def test_defaults(self) -> None:
+        knobs = FakeKnobs()
+        self.assertEqual(0, knobs.latency_ms)
+        self.assertEqual(0.0, knobs.error_rate)
+        self.assertEqual(503, knobs.error_status)
+        self.assertIs(HangMode.NONE, knobs.hang)
+        self.assertTrue(knobs.usage)
+        self.assertEqual(0, knobs.seed)
+
+    def test_unknown_knob_is_rejected(self) -> None:
+        with self.assertRaisesRegex(KnobError, "unknown knob"):
+            FakeKnobs.from_overrides({"latency": 5})
+
+    def test_invalid_values_are_rejected(self) -> None:
+        for overrides in ({"error_status": 418}, {"error_rate": 1.5}, {"latency_ms": -1}):
+            with self.subTest(overrides=overrides), self.assertRaises(KnobError):
+                FakeKnobs.from_overrides(overrides)
+
+    def test_hang_boolean_shorthand(self) -> None:
+        cases = {"true": HangMode.BEFORE_HEADERS, "0": HangMode.NONE, True: HangMode.BEFORE_HEADERS}
+        for raw, expected in cases.items():
+            with self.subTest(raw=raw):
+                self.assertIs(expected, FakeKnobs.from_overrides({"hang": raw}).hang)
+        self.assertIs(HangMode.MID_STREAM, FakeKnobs.from_overrides({"hang": "mid_stream"}).hang)
+
+    def test_string_values_are_coerced(self) -> None:
+        knobs = FakeKnobs.from_overrides({"latency_ms": "250", "usage": "false"})
+        self.assertEqual(250, knobs.latency_ms)
+        self.assertFalse(knobs.usage)
+
+
+@pytest.mark.unit
+class KnobStoreAndResolverTest(unittest.TestCase):
+    """Global overrides merge with headers; headers win."""
+
+    def test_store_merges_and_resets(self) -> None:
+        store = KnobStore()
+        store.update({"latency_ms": 10})
+        store.update({"error_rate": 0.5})
+        self.assertEqual({"error_rate": 0.5, "latency_ms": 10}, store.overrides())
+        store.reset()
+        self.assertEqual({}, store.overrides())
+
+    def test_invalid_update_leaves_store_unchanged(self) -> None:
+        store = KnobStore()
+        store.update({"latency_ms": 10})
+        with self.assertRaises(KnobError):
+            store.update({"error_status": 999})
+        self.assertEqual({"latency_ms": 10}, store.overrides())
+
+    def test_headers_override_store(self) -> None:
+        store = KnobStore()
+        store.update({"latency_ms": 10, "seed": 3})
+        headers = {"X-Fake-Latency-Ms": "99", "authorization": "ignored"}
+        knobs = KnobResolver(store).resolve(headers)
+        self.assertEqual(99, knobs.latency_ms)
+        self.assertEqual(3, knobs.seed)
+
+    def test_unknown_header_knob_fails(self) -> None:
+        with self.assertRaises(KnobError):
+            KnobResolver(KnobStore()).resolve({"x-fake-bogus": "1"})
+
+
+@pytest.mark.unit
+class RngPoolTest(unittest.TestCase):
+    """Seeded streams are reproducible and restartable."""
+
+    def test_stream_matches_seeded_random_and_restarts(self) -> None:
+        pool = RngPool()
+        expected = random.Random(42)  # noqa: S311 - reference stream
+        first = [pool.for_seed(42).random() for _ in range(3)]
+        self.assertEqual([expected.random() for _ in range(3)], first)
+        pool.reset()
+        self.assertEqual(first, [pool.for_seed(42).random() for _ in range(3)])
+
+    def test_seeds_are_independent(self) -> None:
+        pool = RngPool()
+        self.assertIsNot(pool.for_seed(1), pool.for_seed(2))
+        self.assertIs(pool.for_seed(1), pool.for_seed(1))
diff --git a/tests/unit/fake_provider/test_streaming.py b/tests/unit/fake_provider/test_streaming.py
new file mode 100644
index 0000000..c2f644b
--- /dev/null
+++ b/tests/unit/fake_provider/test_streaming.py
@@ -0,0 +1,165 @@
+"""Unit tests for ``fake_provider.streaming``."""
+
+from __future__ import annotations
+
+import asyncio
+import json
+import unittest
+from unittest.mock import AsyncMock, patch
+
+import pytest
+from fake_provider.knobs import FakeKnobs, HangMode
+from fake_provider.streaming import (
+    DONE_FRAME,
+    MALFORMED_FRAME,
+    TOOL_ARGUMENTS,
+    ChunkStreamer,
+    CompletionBuilder,
+    CompletionPlan,
+    StreamDroppedError,
+    SystemClock,
+)
+
+from .support import FakeClock, HangCalledError
+
+MESSAGES = [{"role": "user", "content": "hi there"}]
+
+
+def _plan(**knobs: object) -> CompletionPlan:
+    return CompletionPlan.create(
+        "fake-model", MESSAGES, None, FakeKnobs.from_overrides(knobs), FakeClock.NOW
+    )
+
+
+@pytest.mark.unit
+class CompletionBuilderTest(unittest.TestCase):
+    """Pure payload construction."""
+
+    def setUp(self) -> None:
+        self.builder = CompletionBuilder()
+
+    def test_plan_is_deterministic_and_validated(self) -> None:
+        self.assertEqual(_plan().completion_id, _plan().completion_id)
+        self.assertNotEqual(_plan().completion_id, _plan(seed=1).completion_id)
+        self.assertEqual(int(FakeClock.NOW), _plan().created)
+        with self.assertRaises(ValueError):
+            CompletionPlan.create("", MESSAGES, None, FakeKnobs(), 0.0)
+
+    def test_pieces_cover_text(self) -> None:
+        plan = _plan(chunks=5, text="abcdefghijk")
+        pieces = self.builder.pieces(plan)
+        self.assertEqual(5, len(pieces))
+        self.assertEqual("abcdefghijk", "".join(pieces))
+
+    def test_more_chunks_than_characters_caps_at_length(self) -> None:
+        self.assertEqual(["a", "b"], self.builder.pieces(_plan(chunks=9, text="ab")))
+
+    def test_completion_shape_and_usage_toggle(self) -> None:
+        body = self.builder.completion(_plan())
+        self.assertEqual("chat.completion", body["object"])
+        self.assertEqual("stop", body["choices"][0]["finish_reason"])
+        self.assertEqual(FakeKnobs().text, body["choices"][0]["message"]["content"])
+        usage = body["usage"]
+        self.assertEqual(usage["prompt_tokens"] + usage["completion_tokens"], usage["total_tokens"])
+        self.assertNotIn("usage", self.builder.completion(_plan(usage=False)))
+
+    def test_tool_call_completion(self) -> None:
+        plan = CompletionPlan.create("m", MESSAGES, "lookup", FakeKnobs(tool_call=True), 0.0)
+        choice = self.builder.completion(plan)["choices"][0]
+        self.assertEqual("tool_calls", choice["finish_reason"])
+        self.assertIsNone(choice["message"]["content"])
+        call = choice["message"]["tool_calls"][0]
+        self.assertEqual("lookup", call["function"]["name"])
+        self.assertEqual(TOOL_ARGUMENTS, call["function"]["arguments"])
+
+    def test_chunks_end_with_finish_then_usage(self) -> None:
+        frames = self.builder.chunks(_plan(chunks=3))
+        self.assertEqual(1 + 3 + 1 + 1, len(frames))
+        self.assertEqual({"role": "assistant", "content": ""}, frames[0]["choices"][0]["delta"])
+        self.assertEqual("stop", frames[-2]["choices"][0]["finish_reason"])
+        self.assertEqual([], frames[-1]["choices"])
+        self.assertIn("usage", frames[-1])
+        self.assertEqual(5, len(self.builder.chunks(_plan(chunks=3, usage=False))))
+
+    def test_tool_call_chunks_reassemble_arguments(self) -> None:
+        frames = self.builder.chunks(_plan(chunks=4, tool_call=True))
+        first = frames[0]["choices"][0]["delta"]["tool_calls"][0]
+        self.assertEqual("get_weather", first["function"]["name"])
+        fragments = [
+            f["choices"][0]["delta"]["tool_calls"][0]["function"]["arguments"] for f in frames[1:5]
+        ]
+        self.assertEqual(TOOL_ARGUMENTS, "".join(fragments))
+        self.assertEqual("tool_calls", frames[5]["choices"][0]["finish_reason"])
+
+
+@pytest.mark.unit
+class ChunkStreamerTest(unittest.IsolatedAsyncioTestCase):
+    """SSE framing, timing knobs and stream faults."""
+
+    def setUp(self) -> None:
+        self.clock = FakeClock()
+        self.streamer = ChunkStreamer(CompletionBuilder(), self.clock)
+
+    async def _collect(self, plan: CompletionPlan) -> list[str]:
+        return [frame async for frame in self.streamer.stream(plan)]
+
+    async def test_frames_are_sse_and_end_with_done(self) -> None:
+        frames = await self._collect(_plan(chunks=2, ttft_ms=40, inter_chunk_ms=5))
+        self.assertEqual(DONE_FRAME, frames[-1])
+        for frame in frames[:-1]:
+            self.assertTrue(frame.startswith("data: ") and frame.endswith("\n\n"))
+            json.loads(frame[len("data: ") :])
+        self.assertEqual(0.04, self.clock.sleeps[0])
+        self.assertEqual([0.005] * (len(frames) - 2), self.clock.sleeps[1:])
+
+    async def test_drop_after_chunks_cuts_stream_without_done(self) -> None:
+        stream = self.streamer.stream(_plan(drop_after_chunks=2))
+        received = []
+        with self.assertRaises(StreamDroppedError):
+            async for frame in stream:
+                received.append(frame)
+        self.assertEqual(2, len(received))
+        self.assertNotIn(DONE_FRAME, received)
+
+    async def test_drop_after_zero_chunks(self) -> None:
+        with self.assertRaises(StreamDroppedError):
+            await self._collect(_plan(drop_after_chunks=0))
+
+    async def test_malformed_chunk_is_invalid_json(self) -> None:
+        frames = await self._collect(_plan(malformed_at_chunk=2))
+        self.assertEqual(MALFORMED_FRAME, frames[2])
+        with self.assertRaises(json.JSONDecodeError):
+            json.loads(frames[2][len("data: ") :])
+        self.assertEqual(DONE_FRAME, frames[-1])
+
+    async def test_hang_before_first_chunk(self) -> None:
+        received: list[str] = []
+        with self.assertRaises(HangCalledError):
+            async for frame in self.streamer.stream(_plan(hang=HangMode.BEFORE_FIRST_CHUNK)):
+                received.append(frame)
+        self.assertEqual([], received)
+
+    async def test_hang_mid_stream(self) -> None:
+        received: list[str] = []
+        with self.assertRaises(HangCalledError):
+            async for frame in self.streamer.stream(_plan(hang=HangMode.MID_STREAM)):
+                received.append(frame)
+        self.assertEqual(1, len(received))
+
+
+@pytest.mark.unit
+class SystemClockTest(unittest.IsolatedAsyncioTestCase):
+    """The real clock delegates to asyncio and never sleeps for zero."""
+
+    async def test_sleep_delegates_only_for_positive_values(self) -> None:
+        with patch("fake_provider.streaming.asyncio.sleep", new=AsyncMock()) as fake_sleep:
+            await SystemClock().sleep(0)
+            await SystemClock().sleep(0.25)
+        fake_sleep.assert_awaited_once_with(0.25)
+
+    async def test_hang_waits_until_cancelled(self) -> None:
+        with self.assertRaises(TimeoutError):
+            await asyncio.wait_for(SystemClock().hang(), timeout=0.01)
+
+    def test_now_is_positive(self) -> None:
+        self.assertGreater(SystemClock().now(), 0)
diff --git a/tests/unit/test_layering.py b/tests/unit/test_layering.py
new file mode 100644
index 0000000..af14780
--- /dev/null
+++ b/tests/unit/test_layering.py
@@ -0,0 +1,102 @@
+"""Layering guard: the domain package stays pure (FR-13)."""
+
+from __future__ import annotations
+
+import ast
+import shutil
+import subprocess
+import unittest
+from pathlib import Path
+
+import pytest
+
+DOMAIN_DIR = Path(__file__).resolve().parents[2] / "src" / "switchyard" / "domain"
+DOMAIN_IMPORT_ALLOWLIST = frozenset(
+    {
+        "__future__",
+        "abc",
+        "collections",
+        "dataclasses",
+        "datetime",
+        "decimal",
+        "enum",
+        "functools",
+        "hashlib",
+        "itertools",
+        "json",
+        "math",
+        "random",
+        "re",
+        "typing",
+        "uuid",
+        "pydantic",
+        "switchyard.domain",
+    }
+)
+LINT_IMPORTS_TIMEOUT_S = 120
+
+
+class DomainImportCollector:
+    """Extracts absolute imported module names from Python source."""
+
+    def collect(self, source: str, filename: str) -> list[str]:
+        """Return the sorted, de-duplicated absolute module names imported by ``source``."""
+        tree = ast.parse(source, filename=filename)
+        names: set[str] = set()
+        for node in ast.walk(tree):
+            if isinstance(node, ast.Import):
+                names.update(alias.name for alias in node.names)
+            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
+                names.add(node.module)
+        return sorted(names)
+
+    @staticmethod
+    def is_allowed(module: str) -> bool:
+        """Return True when ``module`` or one of its parent packages is allowlisted."""
+        parts = module.split(".")
+        prefixes = (".".join(parts[:i]) for i in range(1, len(parts) + 1))
+        return any(prefix in DOMAIN_IMPORT_ALLOWLIST for prefix in prefixes)
+
+
+@pytest.mark.unit
+class DomainLayeringTest(unittest.TestCase):
+    """The domain layer imports only the stdlib allowlist, pydantic and itself."""
+
+    def setUp(self) -> None:
+        self.collector = DomainImportCollector()
+
+    def test_domain_package_exists(self) -> None:
+        self.assertTrue((DOMAIN_DIR / "__init__.py").is_file())
+
+    def test_domain_imports_are_allowlisted(self) -> None:
+        violations: list[str] = []
+        for path in sorted(DOMAIN_DIR.rglob("*.py")):
+            source = path.read_text(encoding="utf-8")
+            for module in self.collector.collect(source, str(path)):
+                if not self.collector.is_allowed(module):
+                    violations.append(f"{path.name}: {module}")
+        self.assertEqual([], violations)
+
+    def test_collector_flags_forbidden_import(self) -> None:
+        source = "import os\nfrom httpx import AsyncClient\nfrom .schema import X\n"
+        modules = self.collector.collect(source, "<sample>")
+        self.assertEqual(["httpx", "os"], modules)
+        self.assertFalse(any(self.collector.is_allowed(m) for m in modules))
+
+    def test_allowlist_accepts_submodules(self) -> None:
+        self.assertTrue(self.collector.is_allowed("collections.abc"))
+        self.assertTrue(self.collector.is_allowed("switchyard.domain.schema"))
+        self.assertFalse(self.collector.is_allowed("switchyard.infrastructure"))
+
+    def test_import_linter_contracts_kept(self) -> None:
+        executable = shutil.which("lint-imports")
+        if executable is None:
+            self.skipTest("lint-imports is not installed in this environment")
+        result = subprocess.run(  # fixed, trusted executable; no shell
+            [executable],
+            capture_output=True,
+            text=True,
+            timeout=LINT_IMPORTS_TIMEOUT_S,
+            check=False,
+        )
+        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
diff --git a/tests/unit/test_settings.py b/tests/unit/test_settings.py
new file mode 100644
index 0000000..d4c6994
--- /dev/null
+++ b/tests/unit/test_settings.py
@@ -0,0 +1,70 @@
+"""Unit tests for ``switchyard.infrastructure.settings.Settings``."""
+
+from __future__ import annotations
+
+import os
+import unittest
+from pathlib import Path
+from unittest.mock import patch
+
+import pytest
+from pydantic import ValidationError
+
+from switchyard.infrastructure.settings import Settings
+
+
+@pytest.mark.unit
+class SettingsTest(unittest.TestCase):
+    """Settings defaults, env overrides and fail-fast validation (Part 03 section 6)."""
+
+    def _build(self, **env: str) -> Settings:
+        with patch.dict(os.environ, env, clear=True):
+            return Settings()
+
+    def test_defaults_match_design(self) -> None:
+        settings = self._build()
+        self.assertEqual(Path("config/models.yaml"), settings.models_path)
+        self.assertEqual(1_048_576, settings.max_body_bytes)
+        self.assertEqual(256, settings.max_messages)
+        self.assertEqual(65_536, settings.max_tool_payload_bytes)
+        self.assertEqual("model", settings.max_tokens_cap)
+        self.assertEqual("http://otel-collector:4317/", str(settings.otel_exporter_otlp_endpoint))
+        self.assertEqual("us-east-1", settings.aws_region)
+        self.assertEqual("aws", settings.secrets_backend)
+        self.assertEqual(600, settings.default_rpm)
+        self.assertEqual(200_000, settings.default_tpm)
+        self.assertEqual(20, settings.default_concurrency)
+
+    def test_env_overrides_with_prefix(self) -> None:
+        settings = self._build(
+            SWITCHYARD_MAX_BODY_BYTES="2048",
+            SWITCHYARD_SECRETS_BACKEND="env",
+            SWITCHYARD_AWS_REGION="eu-west-1",
+        )
+        self.assertEqual(2048, settings.max_body_bytes)
+        self.assertEqual("env", settings.secrets_backend)
+        self.assertEqual("eu-west-1", settings.aws_region)
+
+    def test_unprefixed_env_is_ignored(self) -> None:
+        self.assertEqual(1_048_576, self._build(MAX_BODY_BYTES="5").max_body_bytes)
+
+    def test_non_integer_limit_rejected(self) -> None:
+        with self.assertRaises(ValidationError):
+            self._build(SWITCHYARD_MAX_BODY_BYTES="abc")
+
+    def test_non_positive_limit_rejected(self) -> None:
+        with self.assertRaises(ValidationError):
+            self._build(SWITCHYARD_DEFAULT_RPM="0")
+
+    def test_unknown_secrets_backend_rejected(self) -> None:
+        with self.assertRaises(ValidationError):
+            self._build(SWITCHYARD_SECRETS_BACKEND="vault")
+
+    def test_unknown_field_rejected(self) -> None:
+        with self.assertRaises(ValidationError):
+            Settings(not_a_field=1)  # type: ignore[call-arg]
+
+    def test_settings_are_immutable(self) -> None:
+        settings = self._build()
+        with self.assertRaises(ValidationError):
+            settings.max_messages = 1  # type: ignore[misc]
```

---

## Reviewer Checklist
- [ ] Read index sections above — understand module context without loading full files
- [ ] Review diff for: correctness, design, security, performance, maintainability
- [ ] For any CRITICAL issue needing full context: Read only that specific file (budget: 2 reads)
- [ ] Write findings to `.claude/project_memory/review_log.md`
- [ ] Invoke `code-refactor` agent if REQUEST_CHANGES, or `unit-test` if APPROVE
"""ASGI app factory for the OpenAI-shaped fake provider (``fake_provider.app:create_app``)."""

from __future__ import annotations

from collections import Counter
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Annotated, Any

from fastapi import Body, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from fake_provider.knobs import FakeKnobs, HangMode, KnobError, KnobResolver, KnobStore, RngPool
from fake_provider.streaming import (
    ChunkStreamer,
    Clock,
    CompletionBuilder,
    CompletionPlan,
    DisconnectProbe,
    HangWaiter,
    SystemClock,
    never_disconnected,
)

MODEL_IDS = ("fake-model", "fake-model-fallback", "fake-model-mini")
OWNER = "switchyard-fake"
DEFAULT_429_RETRY_AFTER_S = 1.0
HANG_EXPIRED_STATUS = 504
_ERROR_TYPES = {
    400: ("invalid_request_error", "invalid_request"),
    401: ("authentication_error", "invalid_api_key"),
    429: ("rate_limit_error", "rate_limit_exceeded"),
    500: ("server_error", "internal_error"),
    503: ("server_error", "service_unavailable"),
    504: ("server_error", "upstream_timeout"),
    529: ("overloaded_error", "overloaded"),
}
KnobPatch = Annotated[dict[str, Any], Body()]


class ChatCompletionRequest(BaseModel):
    """The subset of the OpenAI chat request the fake provider inspects."""

    model_config = ConfigDict(extra="allow")

    model: str = Field(min_length=1)
    messages: list[dict[str, Any]] = Field(min_length=1)
    stream: bool = False
    tools: list[dict[str, Any]] | None = None

    def first_tool_name(self) -> str | None:
        """Return the first declared function name, if any."""
        for tool in self.tools or []:
            name = tool.get("function", {}).get("name")
            if isinstance(name, str) and name:
                return name
        return None


@dataclass
class ProviderStats:
    """Request and connection counters exposed on ``/admin/stats``."""

    requests: int = 0
    open_connections: int = 0
    closed_connections: int = 0
    by_status: Counter[int] = field(default_factory=Counter)

    def snapshot(self) -> dict[str, Any]:
        """Return a JSON-ready copy with statuses sorted."""
        return {
            "requests": self.requests,
            "open_connections": self.open_connections,
            "closed_connections": self.closed_connections,
            "by_status": {str(code): self.by_status[code] for code in sorted(self.by_status)},
        }


class ErrorResponder:
    """Shapes OpenAI-style error responses."""

    def respond(self, status: int, message: str, retry_after_s: float | None = None) -> Response:
        """Return a JSON error with an optional ``Retry-After`` header."""
        err_type, code = _ERROR_TYPES.get(status, ("server_error", "error"))
        body = {"error": {"message": message, "type": err_type, "param": None, "code": code}}
        headers = {} if retry_after_s is None else {"Retry-After": f"{retry_after_s:g}"}
        return JSONResponse(status_code=status, content=body, headers=headers)


class CompletionService:
    """Orchestrates one chat completion: knobs, delays, fault injection, response."""

    def __init__(
        self,
        resolver: KnobResolver,
        rngs: RngPool,
        clock: Clock,
        stats: ProviderStats,
        errors: ErrorResponder,
    ) -> None:
        self._resolver = resolver
        self._rngs = rngs
        self._clock = clock
        self._stats = stats
        self._errors = errors
        self._builder = CompletionBuilder()
        self._waiter = HangWaiter(clock)
        self._streamer = ChunkStreamer(self._builder, clock, self._waiter)

    async def handle(
        self,
        request: ChatCompletionRequest,
        headers: Mapping[str, str],
        disconnected: DisconnectProbe = never_disconnected,
    ) -> Response:
        """Return the completion (JSON or SSE) or an injected error.

        A hang before headers ends with a 504 once the client disconnects or
        ``hang_max_s`` elapses, so no handler is ever parked forever.
        """
        self._stats.requests += 1
        try:
            knobs = self._resolver.resolve(headers)
        except KnobError:
            self._stats.by_status[400] += 1
            raise
        await self._clock.sleep(knobs.latency_ms / 1000)
        if knobs.hang is not HangMode.NONE and (
            knobs.hang is HangMode.BEFORE_HEADERS or not request.stream
        ):
            await self._waiter.wait(knobs.hang_max_s, disconnected)
            message = f"fake provider hang ended after at most {knobs.hang_max_s:g}s"
            return self._record(self._errors.respond(HANG_EXPIRED_STATUS, message))
        injected = self._injected_status(knobs)
        if injected is not None:
            return self._record(self._error_for(injected, knobs))
        plan = CompletionPlan.create(
            request.model, request.messages, request.first_tool_name(), knobs, self._clock.now()
        )
        if request.stream:
            return self._record(self._stream_response(plan, disconnected))
        await self._clock.sleep(knobs.ttft_ms / 1000)
        return self._record(JSONResponse(self._builder.completion(plan)))

    def _injected_status(self, knobs: FakeKnobs) -> int | None:
        if knobs.error_rate <= 0:
            return None
        roll = self._rngs.for_seed(knobs.seed).random()
        return knobs.error_status if roll < knobs.error_rate else None

    def _error_for(self, status: int, knobs: FakeKnobs) -> Response:
        retry_after = knobs.retry_after_s
        if status == 429 and retry_after is None:
            retry_after = DEFAULT_429_RETRY_AFTER_S
        if status not in (429, 503):
            retry_after = None
        return self._errors.respond(status, f"fake provider injected HTTP {status}", retry_after)

    def _stream_response(
        self, plan: CompletionPlan, disconnected: DisconnectProbe
    ) -> StreamingResponse:
        headers = {"Cache-Control": "no-cache"}
        return StreamingResponse(
            self._tracked(plan, disconnected), media_type="text/event-stream", headers=headers
        )

    async def _tracked(
        self, plan: CompletionPlan, disconnected: DisconnectProbe
    ) -> AsyncIterator[str]:
        self._stats.open_connections += 1
        try:
            async for frame in self._streamer.stream(plan, disconnected):
                yield frame
        finally:
            self._stats.open_connections -= 1
            self._stats.closed_connections += 1

    def _record(self, response: Response) -> Response:
        self._stats.by_status[response.status_code] += 1
        return response


class AdminService:
    """Global knob management and stats for test harnesses."""

    def __init__(self, store: KnobStore, rngs: RngPool, stats: ProviderStats) -> None:
        self._store = store
        self._rngs = rngs
        self._stats = stats

    def current(self) -> dict[str, Any]:
        """Return the effective global knobs."""
        return FakeKnobs.from_overrides(self._store.overrides()).model_dump(mode="json")

    def update(self, patch: Mapping[str, Any]) -> dict[str, Any]:
        """Merge ``patch`` into the global knobs and restart the seeded RNG streams."""
        knobs = self._store.update(patch)
        self._rngs.reset()
        return knobs.model_dump(mode="json")

    def reset(self) -> dict[str, Any]:
        """Clear every global override, restart RNG streams, and return the defaults."""
        self._store.reset()
        self._rngs.reset()
        return self.current()

    def stats(self) -> dict[str, Any]:
        """Return the counters snapshot."""
        return self._stats.snapshot()


def _models_body() -> dict[str, Any]:
    data = [{"id": m, "object": "model", "created": 0, "owned_by": OWNER} for m in MODEL_IDS]
    return {"object": "list", "data": data}


def _register_error_handlers(app: FastAPI, errors: ErrorResponder) -> None:
    async def on_knob_error(_: Request, exc: Exception) -> Response:
        """Map an invalid knob to an OpenAI 400."""
        return errors.respond(400, f"invalid fake knob: {exc}")

    async def on_validation_error(_: Request, exc: Exception) -> Response:
        """Map an invalid request body to an OpenAI 400."""
        return errors.respond(400, f"invalid request: {exc}")

    app.add_exception_handler(KnobError, on_knob_error)
    app.add_exception_handler(RequestValidationError, on_validation_error)


def _register_admin_routes(app: FastAPI, admin: AdminService) -> None:
    for path in ("/_knobs", "/admin/config"):
        app.add_api_route(path, admin.current, methods=["GET"])
        app.add_api_route(path, _patch_route(admin), methods=["POST", "PUT"])
        app.add_api_route(path, admin.reset, methods=["DELETE"])
    app.add_api_route("/admin/stats", admin.stats, methods=["GET"])


def _patch_route(admin: AdminService) -> Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]:
    async def patch_knobs(patch: KnobPatch) -> dict[str, Any]:
        """Merge a partial knob set into the global knobs."""
        return admin.update(patch)

    return patch_knobs


def create_app(clock: Clock | None = None) -> FastAPI:
    """Build the fake provider app; pass a fake ``clock`` in tests to skip real sleeps."""
    active_clock: Clock = clock if clock is not None else SystemClock()
    store, rngs, stats, errors = KnobStore(), RngPool(), ProviderStats(), ErrorResponder()
    service = CompletionService(KnobResolver(store), rngs, active_clock, stats, errors)
    app = FastAPI(title="Switchyard fake provider", docs_url=None, redoc_url=None)
    _register_error_handlers(app, errors)
    _register_admin_routes(app, AdminService(store, rngs, stats))

    @app.post("/v1/chat/completions")
    async def chat_completions(body: ChatCompletionRequest, request: Request) -> Response:
        """OpenAI ``POST /v1/chat/completions``."""
        return await service.handle(body, request.headers, request.is_disconnected)

    @app.get("/v1/models")
    async def list_models() -> dict[str, Any]:
        """OpenAI ``GET /v1/models``."""
        return _models_body()

    return app

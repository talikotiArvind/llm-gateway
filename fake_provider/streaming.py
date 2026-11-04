"""OpenAI-shaped payload building and SSE chunk streaming with fault injection."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from fake_provider.knobs import FakeKnobs, HangMode

DONE_FRAME = "data: [DONE]\n\n"
MALFORMED_FRAME = 'data: {"id": "chatcmpl-malformed", "choices": [\n\n'
DEFAULT_TOOL_NAME = "get_weather"
TOOL_ARGUMENTS = '{"location": "Paris", "unit": "celsius"}'
HANG_POLL_INTERVAL_S = 0.1

DisconnectProbe = Callable[[], Awaitable[bool]]


class StreamDroppedError(ConnectionError):
    """Raised mid-stream so the server aborts the connection without ``[DONE]``."""


class Clock(Protocol):
    """Time source; injected so tests never really sleep."""

    def now(self) -> float:
        """Return the current UNIX time in seconds."""
        ...

    def monotonic(self) -> float:
        """Return a monotonic time in seconds (for measuring elapsed waits)."""
        ...

    async def sleep(self, seconds: float) -> None:
        """Wait ``seconds``."""
        ...


class SystemClock:
    """Real wall clock and asyncio sleeps."""

    def now(self) -> float:
        """Return the current UNIX time in seconds."""
        return time.time()

    def monotonic(self) -> float:
        """Return ``time.monotonic()``."""
        return time.monotonic()

    async def sleep(self, seconds: float) -> None:
        """Wait ``seconds`` (no-op for non-positive values)."""
        if seconds > 0:
            await asyncio.sleep(seconds)


async def never_disconnected() -> bool:
    """Disconnect probe for callers with no client connection to watch."""
    return False


class HangWaiter:
    """Stalls until the client disconnects or ``max_s`` elapses, whichever comes first.

    Uvicorn does not cancel a handler when its client goes away, and a streaming response
    notices a disconnect only when it next sends. So a hang must poll for the disconnect
    and must have a cap, or every hung request parks a coroutine forever.
    """

    def __init__(self, clock: Clock, poll_interval_s: float = HANG_POLL_INTERVAL_S) -> None:
        if poll_interval_s <= 0:
            raise ValueError("poll_interval_s must be positive")
        self._clock = clock
        self._poll_interval_s = poll_interval_s

    async def wait(self, max_s: float, disconnected: DisconnectProbe) -> bool:
        """Return True if the client disconnected, False if ``max_s`` elapsed first."""
        if max_s <= 0:
            raise ValueError("max_s must be positive")
        deadline = self._clock.monotonic() + max_s
        while not await disconnected():
            remaining = deadline - self._clock.monotonic()
            if remaining <= 0:
                return False
            await self._clock.sleep(min(self._poll_interval_s, remaining))
        return True


@dataclass(frozen=True)
class CompletionPlan:
    """Everything needed to render one completion deterministically."""

    completion_id: str
    model: str
    created: int
    tool_name: str
    prompt_tokens: int
    knobs: FakeKnobs

    @classmethod
    def create(
        cls,
        model: str,
        messages: Sequence[Any],
        tool_name: str | None,
        knobs: FakeKnobs,
        now: float,
    ) -> CompletionPlan:
        """Build a plan; the id is a hash of seed, model and messages so replays match."""
        if not model:
            raise ValueError("model must not be empty")
        canonical = json.dumps([knobs.seed, model, list(messages)], sort_keys=True, default=str)
        digest = hashlib.sha256(canonical.encode()).hexdigest()[:24]
        return cls(
            completion_id=f"chatcmpl-fake-{digest}",
            model=model,
            created=int(now),
            tool_name=tool_name or DEFAULT_TOOL_NAME,
            prompt_tokens=sum(len(json.dumps(m, default=str).split()) for m in messages),
            knobs=knobs,
        )


class CompletionBuilder:
    """Pure transformation from a ``CompletionPlan`` to OpenAI wire payloads."""

    def pieces(self, plan: CompletionPlan) -> list[str]:
        """Split the text (or tool arguments) into ``knobs.chunks`` non-empty pieces."""
        source = TOOL_ARGUMENTS if plan.knobs.tool_call else plan.knobs.text
        count = min(plan.knobs.chunks, len(source))
        size, extra = divmod(len(source), count)
        bounds = [i * size + min(i, extra) for i in range(count + 1)]
        return [source[bounds[i] : bounds[i + 1]] for i in range(count)]

    def completion(self, plan: CompletionPlan) -> dict[str, Any]:
        """Return a non-streaming ``chat.completion`` body."""
        message: dict[str, Any] = {"role": "assistant", "content": plan.knobs.text}
        if plan.knobs.tool_call:
            message = {"role": "assistant", "content": None, "tool_calls": [self._tool_call(plan)]}
        body: dict[str, Any] = {
            **self._envelope(plan, "chat.completion"),
            "choices": [{"index": 0, "message": message, "finish_reason": self._finish(plan)}],
        }
        if plan.knobs.usage:
            body["usage"] = self.usage(plan)
        return body

    def chunks(self, plan: CompletionPlan) -> list[dict[str, Any]]:
        """Return every ``chat.completion.chunk`` payload, in order, without ``[DONE]``."""
        deltas = [self._first_delta(plan)]
        deltas += [self._piece_delta(plan, piece) for piece in self.pieces(plan)]
        frames = [self._chunk(plan, delta, None) for delta in deltas]
        frames.append(self._chunk(plan, {}, self._finish(plan)))
        if plan.knobs.usage:
            frames.append({**self._envelope(plan, "chat.completion.chunk"), "choices": []})
            frames[-1]["usage"] = self.usage(plan)
        return frames

    def usage(self, plan: CompletionPlan) -> dict[str, int]:
        """Return deterministic token counts for the plan."""
        completion_tokens = len(self.pieces(plan))
        return {
            "prompt_tokens": plan.prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": plan.prompt_tokens + completion_tokens,
        }

    def _first_delta(self, plan: CompletionPlan) -> dict[str, Any]:
        if not plan.knobs.tool_call:
            return {"role": "assistant", "content": ""}
        call = self._tool_call(plan)
        call["function"]["arguments"] = ""
        return {"role": "assistant", "content": None, "tool_calls": [{"index": 0, **call}]}

    @staticmethod
    def _piece_delta(plan: CompletionPlan, piece: str) -> dict[str, Any]:
        if plan.knobs.tool_call:
            return {"tool_calls": [{"index": 0, "function": {"arguments": piece}}]}
        return {"content": piece}

    def _chunk(
        self, plan: CompletionPlan, delta: dict[str, Any], finish: str | None
    ) -> dict[str, Any]:
        choice = {"index": 0, "delta": delta, "finish_reason": finish}
        return {**self._envelope(plan, "chat.completion.chunk"), "choices": [choice]}

    @staticmethod
    def _envelope(plan: CompletionPlan, obj: str) -> dict[str, Any]:
        return {
            "id": plan.completion_id,
            "object": obj,
            "created": plan.created,
            "model": plan.model,
        }

    @staticmethod
    def _tool_call(plan: CompletionPlan) -> dict[str, Any]:
        call_id = f"call_{plan.completion_id[-12:]}"
        function = {"name": plan.tool_name, "arguments": TOOL_ARGUMENTS}
        return {"id": call_id, "type": "function", "function": function}

    @staticmethod
    def _finish(plan: CompletionPlan) -> str:
        return "tool_calls" if plan.knobs.tool_call else "stop"


class ChunkStreamer:
    """Turns chunk payloads into SSE frames, honouring timing and stream-fault knobs."""

    def __init__(self, builder: CompletionBuilder, clock: Clock, waiter: HangWaiter) -> None:
        self._builder = builder
        self._clock = clock
        self._waiter = waiter

    async def stream(
        self, plan: CompletionPlan, disconnected: DisconnectProbe = never_disconnected
    ) -> AsyncIterator[str]:
        """Yield SSE frames ending with ``data: [DONE]`` unless a fault cuts the stream.

        A hang ends the stream without ``[DONE]`` once the client disconnects or
        ``hang_max_s`` elapses.
        """
        knobs = plan.knobs
        await self._clock.sleep(knobs.ttft_ms / 1000)
        if knobs.hang is HangMode.BEFORE_FIRST_CHUNK:
            await self._hang(knobs, disconnected, 0)
        for index, payload in enumerate(self._builder.chunks(plan)):
            await self._before_frame(knobs, index, disconnected)
            yield self._render(knobs, index, payload)
        yield DONE_FRAME

    async def _before_frame(
        self, knobs: FakeKnobs, index: int, disconnected: DisconnectProbe
    ) -> None:
        if knobs.drop_after_chunks is not None and index >= knobs.drop_after_chunks:
            raise StreamDroppedError(f"fake stream dropped after {index} chunks")
        if index == 0:
            return
        if knobs.hang is HangMode.MID_STREAM and index == 1:
            await self._hang(knobs, disconnected, index)
        await self._clock.sleep(knobs.inter_chunk_ms / 1000)

    async def _hang(self, knobs: FakeKnobs, disconnected: DisconnectProbe, index: int) -> None:
        await self._waiter.wait(knobs.hang_max_s, disconnected)
        raise StreamDroppedError(f"fake stream hung after {index} chunks and was ended")

    @staticmethod
    def _render(knobs: FakeKnobs, index: int, payload: dict[str, Any]) -> str:
        if knobs.malformed_at_chunk == index:
            return MALFORMED_FRAME
        return f"data: {json.dumps(payload, separators=(',', ':'))}\n\n"

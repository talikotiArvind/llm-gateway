"""Unit tests for ``fake_provider.streaming``."""

from __future__ import annotations

import asyncio
import json
import unittest
from unittest.mock import AsyncMock, patch

import pytest
from fake_provider.knobs import FakeKnobs, HangMode
from fake_provider.streaming import (
    DONE_FRAME,
    MALFORMED_FRAME,
    TOOL_ARGUMENTS,
    ChunkStreamer,
    CompletionBuilder,
    CompletionPlan,
    StreamDroppedError,
    SystemClock,
)

from .support import FakeClock, HangCalledError

MESSAGES = [{"role": "user", "content": "hi there"}]


def _plan(**knobs: object) -> CompletionPlan:
    return CompletionPlan.create(
        "fake-model", MESSAGES, None, FakeKnobs.from_overrides(knobs), FakeClock.NOW
    )


@pytest.mark.unit
class CompletionBuilderTest(unittest.TestCase):
    """Pure payload construction."""

    def setUp(self) -> None:
        self.builder = CompletionBuilder()

    def test_plan_is_deterministic_and_validated(self) -> None:
        self.assertEqual(_plan().completion_id, _plan().completion_id)
        self.assertNotEqual(_plan().completion_id, _plan(seed=1).completion_id)
        self.assertEqual(int(FakeClock.NOW), _plan().created)
        with self.assertRaises(ValueError):
            CompletionPlan.create("", MESSAGES, None, FakeKnobs(), 0.0)

    def test_pieces_cover_text(self) -> None:
        plan = _plan(chunks=5, text="abcdefghijk")
        pieces = self.builder.pieces(plan)
        self.assertEqual(5, len(pieces))
        self.assertEqual("abcdefghijk", "".join(pieces))

    def test_more_chunks_than_characters_caps_at_length(self) -> None:
        self.assertEqual(["a", "b"], self.builder.pieces(_plan(chunks=9, text="ab")))

    def test_completion_shape_and_usage_toggle(self) -> None:
        body = self.builder.completion(_plan())
        self.assertEqual("chat.completion", body["object"])
        self.assertEqual("stop", body["choices"][0]["finish_reason"])
        self.assertEqual(FakeKnobs().text, body["choices"][0]["message"]["content"])
        usage = body["usage"]
        self.assertEqual(usage["prompt_tokens"] + usage["completion_tokens"], usage["total_tokens"])
        self.assertNotIn("usage", self.builder.completion(_plan(usage=False)))

    def test_tool_call_completion(self) -> None:
        plan = CompletionPlan.create("m", MESSAGES, "lookup", FakeKnobs(tool_call=True), 0.0)
        choice = self.builder.completion(plan)["choices"][0]
        self.assertEqual("tool_calls", choice["finish_reason"])
        self.assertIsNone(choice["message"]["content"])
        call = choice["message"]["tool_calls"][0]
        self.assertEqual("lookup", call["function"]["name"])
        self.assertEqual(TOOL_ARGUMENTS, call["function"]["arguments"])

    def test_chunks_end_with_finish_then_usage(self) -> None:
        frames = self.builder.chunks(_plan(chunks=3))
        self.assertEqual(1 + 3 + 1 + 1, len(frames))
        self.assertEqual({"role": "assistant", "content": ""}, frames[0]["choices"][0]["delta"])
        self.assertEqual("stop", frames[-2]["choices"][0]["finish_reason"])
        self.assertEqual([], frames[-1]["choices"])
        self.assertIn("usage", frames[-1])
        self.assertEqual(5, len(self.builder.chunks(_plan(chunks=3, usage=False))))

    def test_tool_call_chunks_reassemble_arguments(self) -> None:
        frames = self.builder.chunks(_plan(chunks=4, tool_call=True))
        first = frames[0]["choices"][0]["delta"]["tool_calls"][0]
        self.assertEqual("get_weather", first["function"]["name"])
        fragments = [
            f["choices"][0]["delta"]["tool_calls"][0]["function"]["arguments"] for f in frames[1:5]
        ]
        self.assertEqual(TOOL_ARGUMENTS, "".join(fragments))
        self.assertEqual("tool_calls", frames[5]["choices"][0]["finish_reason"])


@pytest.mark.unit
class ChunkStreamerTest(unittest.IsolatedAsyncioTestCase):
    """SSE framing, timing knobs and stream faults."""

    def setUp(self) -> None:
        self.clock = FakeClock()
        self.streamer = ChunkStreamer(CompletionBuilder(), self.clock)

    async def _collect(self, plan: CompletionPlan) -> list[str]:
        return [frame async for frame in self.streamer.stream(plan)]

    async def test_frames_are_sse_and_end_with_done(self) -> None:
        frames = await self._collect(_plan(chunks=2, ttft_ms=40, inter_chunk_ms=5))
        self.assertEqual(DONE_FRAME, frames[-1])
        for frame in frames[:-1]:
            self.assertTrue(frame.startswith("data: ") and frame.endswith("\n\n"))
            json.loads(frame[len("data: ") :])
        self.assertEqual(0.04, self.clock.sleeps[0])
        self.assertEqual([0.005] * (len(frames) - 2), self.clock.sleeps[1:])

    async def test_drop_after_chunks_cuts_stream_without_done(self) -> None:
        stream = self.streamer.stream(_plan(drop_after_chunks=2))
        received = []
        with self.assertRaises(StreamDroppedError):
            async for frame in stream:
                received.append(frame)
        self.assertEqual(2, len(received))
        self.assertNotIn(DONE_FRAME, received)

    async def test_drop_after_zero_chunks(self) -> None:
        with self.assertRaises(StreamDroppedError):
            await self._collect(_plan(drop_after_chunks=0))

    async def test_malformed_chunk_is_invalid_json(self) -> None:
        frames = await self._collect(_plan(malformed_at_chunk=2))
        self.assertEqual(MALFORMED_FRAME, frames[2])
        with self.assertRaises(json.JSONDecodeError):
            json.loads(frames[2][len("data: ") :])
        self.assertEqual(DONE_FRAME, frames[-1])

    async def test_hang_before_first_chunk(self) -> None:
        received: list[str] = []
        with self.assertRaises(HangCalledError):
            async for frame in self.streamer.stream(_plan(hang=HangMode.BEFORE_FIRST_CHUNK)):
                received.append(frame)
        self.assertEqual([], received)

    async def test_hang_mid_stream(self) -> None:
        received: list[str] = []
        with self.assertRaises(HangCalledError):
            async for frame in self.streamer.stream(_plan(hang=HangMode.MID_STREAM)):
                received.append(frame)
        self.assertEqual(1, len(received))


@pytest.mark.unit
class SystemClockTest(unittest.IsolatedAsyncioTestCase):
    """The real clock delegates to asyncio and never sleeps for zero."""

    async def test_sleep_delegates_only_for_positive_values(self) -> None:
        with patch("fake_provider.streaming.asyncio.sleep", new=AsyncMock()) as fake_sleep:
            await SystemClock().sleep(0)
            await SystemClock().sleep(0.25)
        fake_sleep.assert_awaited_once_with(0.25)

    async def test_hang_waits_until_cancelled(self) -> None:
        with self.assertRaises(TimeoutError):
            await asyncio.wait_for(SystemClock().hang(), timeout=0.01)

    def test_now_is_positive(self) -> None:
        self.assertGreater(SystemClock().now(), 0)

"""Unit tests for the ``fake_provider.app`` HTTP surface via ``httpx.ASGITransport``."""

from __future__ import annotations

import json
import random
import unittest
from typing import Any

import httpx
import pytest
from fake_provider.app import MODEL_IDS, create_app
from fake_provider.streaming import DONE_FRAME, MALFORMED_FRAME, StreamDroppedError

from .support import FakeClock

CHAT_PATH = "/v1/chat/completions"
BODY: dict[str, Any] = {"model": "fake-model", "messages": [{"role": "user", "content": "hi"}]}


class FakeProviderTestCase(unittest.IsolatedAsyncioTestCase):
    """Builds a fresh app with a fake clock per test."""

    def setUp(self) -> None:
        self.clock = FakeClock()
        self.app = create_app(clock=self.clock)

    def _client(self, raise_app_exceptions: bool = True) -> httpx.AsyncClient:
        transport = httpx.ASGITransport(app=self.app, raise_app_exceptions=raise_app_exceptions)
        return httpx.AsyncClient(transport=transport, base_url="http://fake")

    async def _chat(self, knobs: dict[str, str] | None = None, **body: object) -> httpx.Response:
        headers = {f"x-fake-{k.replace('_', '-')}": v for k, v in (knobs or {}).items()}
        async with self._client() as client:
            return await client.post(CHAT_PATH, json={**BODY, **body}, headers=headers)

    @staticmethod
    def _frames(response: httpx.Response) -> list[str]:
        return [f"{block}\n\n" for block in response.text.split("\n\n") if block]


@pytest.mark.unit
class CompletionsTest(FakeProviderTestCase):
    """OpenAI-shaped success responses."""

    async def test_non_stream_completion(self) -> None:
        response = await self._chat()
        self.assertEqual(200, response.status_code)
        body = response.json()
        self.assertEqual("chat.completion", body["object"])
        self.assertEqual("fake-model", body["model"])
        self.assertEqual("assistant", body["choices"][0]["message"]["role"])
        self.assertIn("usage", body)

    async def test_stream_is_sse_ending_with_done_and_usage(self) -> None:
        response = await self._chat(stream=True)
        self.assertTrue(response.headers["content-type"].startswith("text/event-stream"))
        frames = self._frames(response)
        self.assertEqual(DONE_FRAME, frames[-1])
        payloads = [json.loads(f[len("data: ") :]) for f in frames[:-1]]
        self.assertTrue(all(p["object"] == "chat.completion.chunk" for p in payloads))
        self.assertEqual([], payloads[-1]["choices"])
        self.assertIn("usage", payloads[-1])

    async def test_usage_off(self) -> None:
        self.assertNotIn("usage", (await self._chat({"usage": "false"})).json())
        frames = self._frames(await self._chat({"usage": "false"}, stream=True))
        self.assertNotIn('"usage"', "".join(frames))

    async def test_tool_call_uses_declared_tool_name(self) -> None:
        tools = [{"type": "function", "function": {"name": "search_docs"}}]
        body = (await self._chat({"tool_call": "true"}, tools=tools)).json()
        call = body["choices"][0]["message"]["tool_calls"][0]
        self.assertEqual("search_docs", call["function"]["name"])
        self.assertEqual("tool_calls", body["choices"][0]["finish_reason"])
        stream = "".join(self._frames(await self._chat({"tool_call": "1"}, stream=True)))
        self.assertIn('"tool_calls"', stream)

    async def test_latency_and_ttft_are_slept_via_clock(self) -> None:
        await self._chat({"latency_ms": "250", "ttft_ms": "40"})
        self.assertEqual([0.25, 0.04], self.clock.sleeps)

    async def test_list_models(self) -> None:
        async with self._client() as client:
            body = (await client.get("/v1/models")).json()
        self.assertEqual("list", body["object"])
        self.assertEqual(list(MODEL_IDS), [m["id"] for m in body["data"]])


@pytest.mark.unit
class ErrorInjectionTest(FakeProviderTestCase):
    """Seeded error_rate and the supported error statuses."""

    async def test_error_rate_is_seeded_and_reproducible(self) -> None:
        rng = random.Random(7)  # noqa: S311 - reference stream
        expected = [503 if rng.random() < 0.5 else 200 for _ in range(12)]
        knobs = {"error_rate": "0.5", "seed": "7"}
        statuses = [(await self._chat(knobs)).status_code for _ in range(12)]
        self.assertEqual(expected, statuses)
        self.assertIn(200, statuses)
        self.assertIn(503, statuses)

    async def test_global_knob_update_restarts_seeded_stream(self) -> None:
        async with self._client() as client:
            await client.post("/_knobs", json={"error_rate": 0.5, "seed": 3})
            first = [(await client.post(CHAT_PATH, json=BODY)).status_code for _ in range(6)]
            await client.post("/_knobs", json={})
            second = [(await client.post(CHAT_PATH, json=BODY)).status_code for _ in range(6)]
        self.assertEqual(first, second)

    async def test_429_carries_retry_after(self) -> None:
        response = await self._chat({"error_rate": "1", "error_status": "429"})
        self.assertEqual(429, response.status_code)
        self.assertEqual("1", response.headers["retry-after"])
        self.assertEqual("rate_limit_error", response.json()["error"]["type"])
        knobs = {"error_rate": "1", "error_status": "429", "retry_after_s": "2.5"}
        custom = await self._chat(knobs)
        self.assertEqual("2.5", custom.headers["retry-after"])

    async def test_503_retry_after_only_when_set(self) -> None:
        plain = await self._chat({"error_rate": "1", "error_status": "503"})
        self.assertEqual(503, plain.status_code)
        self.assertNotIn("retry-after", plain.headers)
        timed = await self._chat({"error_rate": "1", "error_status": "503", "retry_after_s": "4"})
        self.assertEqual("4", timed.headers["retry-after"])

    async def test_529_is_overloaded_without_retry_after(self) -> None:
        knobs = {"error_rate": "1", "error_status": "529", "retry_after_s": "4"}
        response = await self._chat(knobs)
        self.assertEqual(529, response.status_code)
        self.assertEqual("overloaded_error", response.json()["error"]["type"])
        self.assertNotIn("retry-after", response.headers)


@pytest.mark.unit
class StreamFaultTest(FakeProviderTestCase):
    """Hang, drop and malformed-chunk knobs through the HTTP surface."""

    async def test_hang_before_headers_ends_with_504_at_cap(self) -> None:
        for stream in (False, True):
            with self.subTest(stream=stream):
                self.clock.elapsed = 0.0
                response = await self._chat({"hang": "true", "hang_max_s": "2"}, stream=stream)
                self.assertEqual(504, response.status_code)
                self.assertEqual("server_error", response.json()["error"]["type"])
                self.assertAlmostEqual(2.0, self.clock.elapsed)

    async def test_non_stream_hangs_for_any_hang_mode(self) -> None:
        response = await self._chat({"hang": "mid_stream", "hang_max_s": "1"})
        self.assertEqual(504, response.status_code)
        self.assertAlmostEqual(1.0, self.clock.elapsed)

    async def test_hang_default_cap_is_bounded(self) -> None:
        response = await self._chat({"hang": "true"})
        self.assertEqual(504, response.status_code)
        self.assertAlmostEqual(300.0, self.clock.elapsed)
        self.assertLessEqual(max(self.clock.sleeps), 0.1)

    async def test_mid_stream_hang_ends_and_releases_connection(self) -> None:
        headers = {"x-fake-hang": "mid_stream", "x-fake-hang-max-s": "1"}
        async with self._client(raise_app_exceptions=False) as client:
            response = await client.post(CHAT_PATH, json={**BODY, "stream": True}, headers=headers)
            stats = (await client.get("/admin/stats")).json()
        self.assertEqual(1, len(self._frames(response)))
        self.assertEqual(0, stats["open_connections"])
        self.assertEqual(1, stats["closed_connections"])

    async def test_drop_after_chunks_has_no_done(self) -> None:
        headers = {"x-fake-drop-after-chunks": "3"}
        async with self._client(raise_app_exceptions=False) as client:
            response = await client.post(CHAT_PATH, json={**BODY, "stream": True}, headers=headers)
        frames = self._frames(response)
        self.assertEqual(3, len(frames))
        self.assertNotIn(DONE_FRAME, frames)
        with self.assertRaises(StreamDroppedError):
            await self._chat({"drop_after_chunks": "3"}, stream=True)

    async def test_malformed_chunk(self) -> None:
        frames = self._frames(await self._chat({"malformed_at_chunk": "1"}, stream=True))
        self.assertEqual(MALFORMED_FRAME, frames[1])
        self.assertEqual(DONE_FRAME, frames[-1])


@pytest.mark.unit
class AdminAndValidationTest(FakeProviderTestCase):
    """Global knobs, stats and fail-fast validation."""

    async def test_global_knobs_apply_and_headers_win(self) -> None:
        async with self._client() as client:
            updated = (await client.post("/_knobs", json={"error_rate": 1})).json()
            self.assertEqual(1.0, updated["error_rate"])
            self.assertEqual(503, (await client.post(CHAT_PATH, json=BODY)).status_code)
            ok = await client.post(CHAT_PATH, json=BODY, headers={"x-fake-error-rate": "0"})
            self.assertEqual(200, ok.status_code)
            await client.put("/admin/config", json={"latency_ms": 5})
            self.assertEqual(5, (await client.get("/_knobs")).json()["latency_ms"])
            reset = (await client.delete("/_knobs")).json()
        self.assertEqual(0.0, reset["error_rate"])

    async def test_invalid_knobs_return_400(self) -> None:
        self.assertEqual(400, (await self._chat({"bogus": "1"})).status_code)
        async with self._client() as client:
            response = await client.post("/_knobs", json={"error_status": 418})
        self.assertEqual(400, response.status_code)
        self.assertEqual("invalid_request_error", response.json()["error"]["type"])

    async def test_invalid_body_returns_400(self) -> None:
        async with self._client() as client:
            response = await client.post(CHAT_PATH, json={"model": "fake-model", "messages": []})
        self.assertEqual(400, response.status_code)

    async def test_invalid_knob_is_counted_as_400(self) -> None:
        async with self._client() as client:
            response = await client.post(CHAT_PATH, json=BODY, headers={"x-fake-chunks": "0"})
            stats = (await client.get("/admin/stats")).json()
        self.assertEqual(400, response.status_code)
        self.assertEqual({"400": 1}, stats["by_status"])

    async def test_stats_count_requests_statuses_and_connections(self) -> None:
        await self._chat()
        await self._chat(stream=True)
        await self._chat({"error_rate": "1"})
        async with self._client() as client:
            stats = (await client.get("/admin/stats")).json()
        self.assertEqual(3, stats["requests"])
        self.assertEqual({"200": 2, "503": 1}, stats["by_status"])
        self.assertEqual(0, stats["open_connections"])
        self.assertEqual(1, stats["closed_connections"])

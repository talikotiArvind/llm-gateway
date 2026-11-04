"""Spec-derived tests for ``fake_provider`` (design Part 01 §7, plan T03, plan §4 streaming).

Expected values come from the OpenAI chat-completions wire format and the fake_provider
spec, not from the implementation.
"""

from __future__ import annotations

import json
from typing import Any, ClassVar

import httpx
import pytest
from fake_provider.app import create_app

from .support import FakeClock
from .test_app import BODY, CHAT_PATH, FakeProviderTestCase

DONE = "data: [DONE]\n\n"
OPENAI_ERROR_KEYS = {"message", "type", "param", "code"}


def _payloads(frames: list[str]) -> list[dict[str, Any]]:
    """Parse every non-[DONE] SSE frame as JSON."""
    return [json.loads(f[len("data: ") :]) for f in frames if f != DONE]


def _choice_chunks(payloads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [p for p in payloads if p["choices"]]


class SpecTestCase(FakeProviderTestCase):
    """Adds raw-header requests and stream helpers on top of the shared fixture."""

    async def _post(
        self,
        client: httpx.AsyncClient,
        headers: dict[str, str] | None = None,
        params: dict[str, str] | None = None,
        **body: object,
    ) -> httpx.Response:
        return await client.post(CHAT_PATH, json={**BODY, **body}, headers=headers, params=params)

    async def _stream_frames(self, knobs: dict[str, str] | None = None) -> list[str]:
        headers = {f"x-fake-{k.replace('_', '-')}": v for k, v in (knobs or {}).items()}
        async with self._client(raise_app_exceptions=False) as client:
            response = await self._post(client, headers, stream=True)
        self.assertEqual(200, response.status_code)
        return self._frames(response)


@pytest.mark.unit
class NonStreamShapeTest(SpecTestCase):
    """``chat.completion`` body matches the OpenAI wire format."""

    async def test_envelope_fields(self) -> None:
        body = (await self._chat()).json()
        self.assertIsInstance(body["id"], str)
        self.assertTrue(body["id"].startswith("chatcmpl-"))
        self.assertEqual("chat.completion", body["object"])
        self.assertIsInstance(body["created"], int)
        self.assertEqual(int(FakeClock.NOW), body["created"])

    async def test_model_is_echoed(self) -> None:
        body = (await self._chat(model="fake-model-mini")).json()
        self.assertEqual("fake-model-mini", body["model"])

    async def test_single_choice_with_message_and_stop(self) -> None:
        choices = (await self._chat()).json()["choices"]
        self.assertEqual(1, len(choices))
        self.assertEqual(0, choices[0]["index"])
        self.assertEqual("assistant", choices[0]["message"]["role"])
        self.assertIsInstance(choices[0]["message"]["content"], str)
        self.assertTrue(choices[0]["message"]["content"])
        self.assertEqual("stop", choices[0]["finish_reason"])

    async def test_usage_tokens_are_ints_and_sum(self) -> None:
        usage = (await self._chat()).json()["usage"]
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            self.assertIsInstance(usage[key], int)
            self.assertGreaterEqual(usage[key], 0)
        self.assertEqual(usage["prompt_tokens"] + usage["completion_tokens"], usage["total_tokens"])


@pytest.mark.unit
class StreamShapeTest(SpecTestCase):
    """``chat.completion.chunk`` frames, usage chunk and the ``[DONE]`` sentinel."""

    async def test_every_frame_is_sse_data_and_last_is_done(self) -> None:
        frames = await self._stream_frames()
        for frame in frames:
            self.assertTrue(frame.startswith("data: "), frame)
            self.assertTrue(frame.endswith("\n\n"), frame)
        self.assertEqual(DONE, frames[-1])
        self.assertEqual(1, frames.count(DONE))

    async def test_chunks_share_id_created_model_and_object(self) -> None:
        payloads = _payloads(await self._stream_frames())
        self.assertEqual({"chat.completion.chunk"}, {p["object"] for p in payloads})
        self.assertEqual(1, len({p["id"] for p in payloads}))
        self.assertTrue(payloads[0]["id"].startswith("chatcmpl-"))
        self.assertEqual({int(FakeClock.NOW)}, {p["created"] for p in payloads})
        self.assertEqual({"fake-model"}, {p["model"] for p in payloads})

    async def test_choice_chunks_carry_delta_and_finish_reason(self) -> None:
        chunks = _choice_chunks(_payloads(await self._stream_frames()))
        for chunk in chunks:
            self.assertEqual(1, len(chunk["choices"]))
            choice = chunk["choices"][0]
            self.assertEqual(0, choice["index"])
            self.assertIn("delta", choice)
            self.assertIn("finish_reason", choice)
        self.assertEqual("assistant", chunks[0]["choices"][0]["delta"]["role"])
        finishes = [c["choices"][0]["finish_reason"] for c in chunks]
        self.assertEqual([None] * (len(chunks) - 1) + ["stop"], finishes)

    async def test_streamed_content_equals_non_stream_content(self) -> None:
        chunks = _choice_chunks(_payloads(await self._stream_frames()))
        streamed = "".join(c["choices"][0]["delta"].get("content") or "" for c in chunks)
        full = (await self._chat()).json()["choices"][0]["message"]["content"]
        self.assertEqual(full, streamed)

    async def test_usage_chunk_is_last_before_done_with_empty_choices(self) -> None:
        frames = await self._stream_frames()
        usage_chunk = json.loads(frames[-2][len("data: ") :])
        self.assertEqual([], usage_chunk["choices"])
        usage = usage_chunk["usage"]
        self.assertEqual(usage["prompt_tokens"] + usage["completion_tokens"], usage["total_tokens"])
        others = _payloads(frames[:-2])
        self.assertTrue(all("usage" not in p or p["usage"] is None for p in others))

    async def test_stream_response_is_event_stream(self) -> None:
        async with self._client() as client:
            response = await self._post(client, stream=True)
        self.assertTrue(response.headers["content-type"].startswith("text/event-stream"))


@pytest.mark.unit
class ToolCallDeltaTest(SpecTestCase):
    """Tool-call deltas: one call at index 0, a stable id, arguments split across chunks."""

    TOOLS: ClassVar[list[dict[str, Any]]] = [
        {"type": "function", "function": {"name": "search_docs"}}
    ]

    async def _tool_frames(self) -> list[str]:
        async with self._client() as client:
            response = await self._post(
                client, {"x-fake-tool-call": "true"}, stream=True, tools=self.TOOLS
            )
        return self._frames(response)

    @staticmethod
    def _tool_deltas(frames: list[str]) -> list[dict[str, Any]]:
        deltas: list[dict[str, Any]] = []
        for chunk in _choice_chunks(_payloads(frames)):
            deltas.extend(chunk["choices"][0]["delta"].get("tool_calls") or [])
        return deltas

    async def test_first_delta_opens_call_with_id_type_and_name(self) -> None:
        first = self._tool_deltas(await self._tool_frames())[0]
        self.assertEqual(0, first["index"])
        self.assertIsInstance(first["id"], str)
        self.assertTrue(first["id"])
        self.assertEqual("function", first["type"])
        self.assertEqual("search_docs", first["function"]["name"])

    async def test_all_deltas_keep_index_and_id(self) -> None:
        deltas = self._tool_deltas(await self._tool_frames())
        self.assertGreater(len(deltas), 2)
        self.assertEqual({0}, {d["index"] for d in deltas})
        ids = {d["id"] for d in deltas if "id" in d}
        self.assertEqual(1, len(ids))

    async def test_arguments_split_across_chunks_reassemble_to_json(self) -> None:
        deltas = self._tool_deltas(await self._tool_frames())
        fragments = [d["function"].get("arguments", "") for d in deltas]
        self.assertGreater(len([f for f in fragments if f]), 1)
        self.assertIsInstance(json.loads("".join(fragments)), dict)

    async def test_finish_reason_is_tool_calls(self) -> None:
        chunks = _choice_chunks(_payloads(await self._tool_frames()))
        self.assertEqual("tool_calls", chunks[-1]["choices"][0]["finish_reason"])
        self.assertEqual(DONE, (await self._tool_frames())[-1])

    async def test_call_id_is_stable_across_identical_requests(self) -> None:
        first = self._tool_deltas(await self._tool_frames())[0]["id"]
        second = self._tool_deltas(await self._tool_frames())[0]["id"]
        self.assertEqual(first, second)


@pytest.mark.unit
class DeterminismTest(SpecTestCase):
    """The seed alone determines the error sequence and the content."""

    async def _statuses(self, seed: str, count: int = 20) -> list[int]:
        self.app = create_app(clock=FakeClock())
        knobs = {"x-fake-error-rate": "0.5", "x-fake-seed": seed, "x-fake-error-status": "429"}
        async with self._client() as client:
            return [(await self._post(client, knobs)).status_code for _ in range(count)]

    async def test_same_seed_same_error_sequence_across_fresh_apps(self) -> None:
        first = await self._statuses("11")
        second = await self._statuses("11")
        self.assertEqual(first, second)
        self.assertEqual({200, 429}, set(first))

    async def test_different_seed_gives_different_sequence(self) -> None:
        self.assertNotEqual(await self._statuses("11"), await self._statuses("12"))

    async def test_same_seed_same_body(self) -> None:
        first = (await self._chat({"seed": "5"})).content
        self.app = create_app(clock=FakeClock())
        self.assertEqual(first, (await self._chat({"seed": "5"})).content)


@pytest.mark.unit
class ErrorBodyTest(SpecTestCase):
    """429 / 503 / 529 status, headers and OpenAI error bodies."""

    async def _error(self, status: str, **extra: str) -> httpx.Response:
        return await self._chat({"error_rate": "1", "error_status": status, **extra})

    async def test_503_has_openai_error_body(self) -> None:
        response = await self._error("503")
        self.assertEqual(503, response.status_code)
        self.assertTrue(response.headers["content-type"].startswith("application/json"))
        error = response.json()["error"]
        self.assertLessEqual(OPENAI_ERROR_KEYS, set(error))
        self.assertTrue(error["message"])
        self.assertEqual("server_error", error["type"])

    async def test_529_has_overloaded_error_body(self) -> None:
        response = await self._error("529")
        self.assertEqual(529, response.status_code)
        error = response.json()["error"]
        self.assertLessEqual(OPENAI_ERROR_KEYS, set(error))
        self.assertEqual("overloaded_error", error["type"])
        self.assertTrue(error["message"])

    async def test_429_retry_after_matches_knob(self) -> None:
        response = await self._error("429", retry_after_s="7")
        self.assertEqual(429, response.status_code)
        self.assertEqual(7.0, float(response.headers["retry-after"]))
        self.assertLessEqual(OPENAI_ERROR_KEYS, set(response.json()["error"]))

    async def test_429_retry_after_from_global_knobs(self) -> None:
        patch = {"error_rate": 1, "error_status": 429, "retry_after_s": 3}
        async with self._client() as client:
            self.assertEqual(200, (await client.post("/_knobs", json=patch)).status_code)
            response = await self._post(client)
        self.assertEqual(429, response.status_code)
        self.assertEqual(3.0, float(response.headers["retry-after"]))

    async def test_error_is_returned_for_stream_requests_before_any_chunk(self) -> None:
        response = await self._chat({"error_rate": "1", "error_status": "503"}, stream=True)
        self.assertEqual(503, response.status_code)
        self.assertNotIn("[DONE]", response.text)


@pytest.mark.unit
class StreamFaultSpecTest(SpecTestCase):
    """hang_max_s, drop_after_chunks and malformed_at_chunk through HTTP."""

    async def test_hang_before_first_chunk_ends_at_hang_max_s_without_done(self) -> None:
        frames = await self._stream_frames({"hang": "before_first_chunk", "hang_max_s": "2"})
        self.assertEqual([], frames)
        self.assertAlmostEqual(2.0, self.clock.elapsed)

    async def test_mid_stream_hang_ends_at_hang_max_s_without_done(self) -> None:
        frames = await self._stream_frames({"hang": "mid_stream", "hang_max_s": "1.5"})
        self.assertNotIn(DONE, frames)
        self.assertAlmostEqual(1.5, self.clock.elapsed)

    async def test_drop_after_chunks_sends_exactly_n_valid_chunks(self) -> None:
        frames = await self._stream_frames({"drop_after_chunks": "2"})
        self.assertEqual(2, len(frames))
        self.assertNotIn(DONE, frames)
        self.assertEqual(2, len(_payloads(frames)))

    async def test_drop_after_zero_chunks_sends_nothing(self) -> None:
        self.assertEqual([], await self._stream_frames({"drop_after_chunks": "0"}))

    async def test_malformed_at_chunk_emits_invalid_json_only_there(self) -> None:
        frames = await self._stream_frames({"malformed_at_chunk": "0"})
        with self.assertRaises(json.JSONDecodeError):
            json.loads(frames[0][len("data: ") :])
        for frame in frames[1:-1]:
            json.loads(frame[len("data: ") :])


@pytest.mark.unit
class KnobPrecedenceTest(SpecTestCase):
    """Precedence: header ``x-fake-*`` > query ``fake_*`` > global knobs > defaults."""

    async def test_header_latency_overrides_global(self) -> None:
        async with self._client() as client:
            await client.post("/_knobs", json={"latency_ms": 100})
            await self._post(client, {"x-fake-latency-ms": "7"})
            await self._post(client)
        self.assertEqual(0.007, self.clock.sleeps[0])
        self.assertIn(0.1, self.clock.sleeps[1:])

    async def test_header_error_status_overrides_global(self) -> None:
        async with self._client() as client:
            await client.post("/_knobs", json={"error_rate": 1, "error_status": 429})
            response = await self._post(client, {"x-fake-error-status": "529"})
        self.assertEqual(529, response.status_code)

    async def test_header_names_are_case_insensitive(self) -> None:
        async with self._client() as client:
            response = await self._post(client, {"X-Fake-Error-Rate": "1"})
        self.assertEqual(503, response.status_code)

    async def test_global_knobs_apply_without_header(self) -> None:
        async with self._client() as client:
            await client.post("/admin/config", json={"error_rate": 1, "error_status": 500})
            response = await self._post(client)
        self.assertEqual(500, response.status_code)

    async def test_query_knob_overrides_global_and_header_overrides_query(self) -> None:
        async with self._client() as client:
            await client.put("/admin/config", json={"error_rate": 0})
            by_query = await self._post(client, params={"fake_error_rate": "1"})
            by_header = await self._post(
                client, {"x-fake-error-rate": "0"}, params={"fake_error_rate": "1"}
            )
        self.assertEqual(503, by_query.status_code)
        self.assertEqual(200, by_header.status_code)

    async def test_admin_config_scoped_by_match_model(self) -> None:
        async with self._client() as client:
            put = await client.put(
                "/admin/config", json={"error_rate": 1, "match_model": "fake-model"}
            )
            primary = await self._post(client)
            fallback = await self._post(client, model="fake-model-fallback")
        self.assertEqual(200, put.status_code)
        self.assertEqual(503, primary.status_code)
        self.assertEqual(200, fallback.status_code)


@pytest.mark.unit
class InvalidKnobTest(SpecTestCase):
    """Invalid knob names or values fail fast with an OpenAI 400."""

    INVALID: ClassVar[tuple[tuple[str, str, object], ...]] = (
        ("error_rate", "1.5", 1.5),
        ("error_rate", "-0.1", -0.1),
        ("error_rate", "abc", "abc"),
        ("latency_ms", "-1", -1),
        ("ttft_ms", "soon", "soon"),
        ("inter_chunk_ms", "-5", -5),
        ("hang", "sideways", "sideways"),
        ("hang_max_s", "0", 0),
        ("chunks", "0", 0),
        ("drop_after_chunks", "-1", -1),
        ("malformed_at_chunk", "-2", -2),
        ("retry_after_s", "-1", -1),
        ("error_status", "418", 418),
        ("seed", "x", "x"),
        ("usage", "maybe", "maybe"),
    )

    def _assert_400(self, response: httpx.Response) -> None:
        self.assertEqual(400, response.status_code)
        self.assertEqual("invalid_request_error", response.json()["error"]["type"])

    async def test_invalid_header_values_return_400(self) -> None:
        for name, header_value, _ in self.INVALID:
            with self.subTest(knob=name, value=header_value):
                self._assert_400(await self._chat({name: header_value}))

    async def test_invalid_global_values_return_400_and_leave_store_unchanged(self) -> None:
        async with self._client() as client:
            before = (await client.get("/_knobs")).json()
            for name, _, json_value in self.INVALID:
                with self.subTest(knob=name, value=json_value):
                    self._assert_400(await client.post("/_knobs", json={name: json_value}))
            after = (await client.get("/_knobs")).json()
        self.assertEqual(before, after)

    async def test_unknown_global_knob_returns_400(self) -> None:
        async with self._client() as client:
            self._assert_400(await client.post("/_knobs", json={"not_a_knob": 1}))

    async def test_invalid_header_on_stream_returns_400_not_sse(self) -> None:
        response = await self._chat({"error_rate": "2"}, stream=True)
        self._assert_400(response)

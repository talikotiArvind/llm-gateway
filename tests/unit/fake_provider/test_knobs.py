"""Unit tests for ``fake_provider.knobs``."""

from __future__ import annotations

import random
import unittest

import pytest
from fake_provider.knobs import (
    FakeKnobs,
    HangMode,
    KnobError,
    KnobResolver,
    KnobStore,
    RngPool,
    split_match_model,
)


@pytest.mark.unit
class FakeKnobsTest(unittest.TestCase):
    """Defaults, validation and coercion of a single knob set."""

    def test_defaults(self) -> None:
        knobs = FakeKnobs()
        self.assertEqual(0, knobs.latency_ms)
        self.assertEqual(0.0, knobs.error_rate)
        self.assertEqual(503, knobs.error_status)
        self.assertIs(HangMode.NONE, knobs.hang)
        self.assertTrue(knobs.usage)
        self.assertEqual(0, knobs.seed)

    def test_unknown_knob_is_rejected(self) -> None:
        with self.assertRaisesRegex(KnobError, "unknown knob"):
            FakeKnobs.from_overrides({"latency": 5})

    def test_invalid_values_are_rejected(self) -> None:
        for overrides in ({"error_status": 418}, {"error_rate": 1.5}, {"latency_ms": -1}):
            with self.subTest(overrides=overrides), self.assertRaises(KnobError):
                FakeKnobs.from_overrides(overrides)

    def test_hang_boolean_shorthand(self) -> None:
        cases = {"true": HangMode.BEFORE_HEADERS, "0": HangMode.NONE, True: HangMode.BEFORE_HEADERS}
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertIs(expected, FakeKnobs.from_overrides({"hang": raw}).hang)
        self.assertIs(HangMode.MID_STREAM, FakeKnobs.from_overrides({"hang": "mid_stream"}).hang)

    def test_string_values_are_coerced(self) -> None:
        knobs = FakeKnobs.from_overrides({"latency_ms": "250", "usage": "false"})
        self.assertEqual(250, knobs.latency_ms)
        self.assertFalse(knobs.usage)


@pytest.mark.unit
class KnobStoreAndResolverTest(unittest.TestCase):
    """Global overrides merge with headers; headers win."""

    def test_store_merges_and_resets(self) -> None:
        store = KnobStore()
        store.update({"latency_ms": 10})
        store.update({"error_rate": 0.5})
        self.assertEqual({"error_rate": 0.5, "latency_ms": 10}, store.overrides())
        store.reset()
        self.assertEqual({}, store.overrides())

    def test_invalid_update_leaves_store_unchanged(self) -> None:
        store = KnobStore()
        store.update({"latency_ms": 10})
        with self.assertRaises(KnobError):
            store.update({"error_status": 999})
        self.assertEqual({"latency_ms": 10}, store.overrides())

    def test_headers_override_store(self) -> None:
        store = KnobStore()
        store.update({"latency_ms": 10, "seed": 3})
        headers = {"X-Fake-Latency-Ms": "99", "authorization": "ignored"}
        knobs = KnobResolver(store).resolve(headers)
        self.assertEqual(99, knobs.latency_ms)
        self.assertEqual(3, knobs.seed)

    def test_unknown_header_knob_fails(self) -> None:
        with self.assertRaises(KnobError):
            KnobResolver(KnobStore()).resolve({"x-fake-bogus": "1"})

    def test_precedence_header_over_query_over_store(self) -> None:
        store = KnobStore()
        store.update({"latency_ms": 1, "ttft_ms": 1, "inter_chunk_ms": 1})
        query = {"fake_ttft_ms": "2", "fake_latency_ms": "2", "other": "x"}
        knobs = KnobResolver(store).resolve({"x-fake-latency-ms": "3"}, query)
        self.assertEqual((3, 2, 1), (knobs.latency_ms, knobs.ttft_ms, knobs.inter_chunk_ms))

    def test_model_rule_applies_only_to_matching_model(self) -> None:
        store = KnobStore()
        store.update({"latency_ms": 5})
        store.update({"error_rate": 1.0}, match_model="fake-model")
        store.update({"ttft_ms": 4}, match_model="fake-model")
        resolver = KnobResolver(store)
        scoped = resolver.resolve({}, model="fake-model")
        other = resolver.resolve({}, model="fake-model-fallback")
        self.assertEqual((1.0, 4, 5), (scoped.error_rate, scoped.ttft_ms, scoped.latency_ms))
        self.assertEqual((0.0, 0, 5), (other.error_rate, other.ttft_ms, other.latency_ms))
        store.reset()
        self.assertEqual({}, store.overrides("fake-model"))

    def test_split_match_model(self) -> None:
        self.assertEqual(({"seed": 1}, None), split_match_model({"seed": 1}))
        self.assertEqual(({}, "m"), split_match_model({"match_model": "m"}))
        for bad in ("", "  ", 3):
            with self.subTest(match_model=bad), self.assertRaises(KnobError):
                split_match_model({"match_model": bad})


@pytest.mark.unit
class ErrorCodesKnobTest(unittest.TestCase):
    """``error_codes`` accepts lists or comma-separated strings of supported statuses."""

    def test_parses_comma_separated_string(self) -> None:
        knobs = FakeKnobs.from_overrides({"error_codes": "429, 503"})
        self.assertEqual((429, 503), knobs.error_codes)

    def test_accepts_list(self) -> None:
        self.assertEqual((529,), FakeKnobs.from_overrides({"error_codes": [529]}).error_codes)

    def test_rejects_unsupported_or_empty(self) -> None:
        for bad in ([418], "", []):
            with self.subTest(error_codes=bad), self.assertRaises(KnobError):
                FakeKnobs.from_overrides({"error_codes": bad})


@pytest.mark.unit
class RngPoolTest(unittest.TestCase):
    """Seeded streams are reproducible and restartable."""

    def test_stream_matches_seeded_random_and_restarts(self) -> None:
        pool = RngPool()
        expected = random.Random(42)  # noqa: S311 - reference stream
        first = [pool.for_seed(42).random() for _ in range(3)]
        self.assertEqual([expected.random() for _ in range(3)], first)
        pool.reset()
        self.assertEqual(first, [pool.for_seed(42).random() for _ in range(3)])

    def test_seeds_are_independent(self) -> None:
        pool = RngPool()
        self.assertIsNot(pool.for_seed(1), pool.for_seed(2))
        self.assertIs(pool.for_seed(1), pool.for_seed(1))

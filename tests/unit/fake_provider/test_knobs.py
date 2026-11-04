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

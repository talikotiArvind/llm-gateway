"""Fault-injection knobs for the fake provider: model, global store, per-request resolution."""

from __future__ import annotations

import random
from collections.abc import Mapping
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

HEADER_PREFIX = "x-fake-"
SUPPORTED_ERROR_STATUSES = frozenset({400, 401, 429, 500, 503, 529})
DEFAULT_TEXT = "Hello from the Switchyard fake provider. This reply is deterministic."
MAX_CHUNKS = 1_000
_TRUE_VALUES = frozenset({"true", "1", "yes", "on"})
_FALSE_VALUES = frozenset({"false", "0", "no", "off", ""})


class KnobError(ValueError):
    """Raised when a knob name or value is invalid."""


class HangMode(StrEnum):
    """Where the provider stalls until the client disconnects."""

    NONE = "none"
    BEFORE_HEADERS = "before_headers"
    BEFORE_FIRST_CHUNK = "before_first_chunk"
    MID_STREAM = "mid_stream"


class FakeKnobs(BaseModel):
    """Effective knobs for one request (defaults < global store < x-fake-* headers)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    latency_ms: int = Field(default=0, ge=0)
    ttft_ms: int = Field(default=0, ge=0)
    inter_chunk_ms: int = Field(default=0, ge=0)
    error_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    error_status: int = 503
    retry_after_s: float | None = Field(default=None, ge=0.0)
    hang: HangMode = HangMode.NONE
    drop_after_chunks: int | None = Field(default=None, ge=0)
    malformed_at_chunk: int | None = Field(default=None, ge=0)
    usage: bool = True
    chunks: int = Field(default=8, ge=1, le=MAX_CHUNKS)
    text: str = Field(default=DEFAULT_TEXT, min_length=1)
    tool_call: bool = False
    seed: int = 0

    @field_validator("error_status")
    @classmethod
    def _check_error_status(cls, value: int) -> int:
        if value not in SUPPORTED_ERROR_STATUSES:
            raise ValueError(f"error_status must be one of {sorted(SUPPORTED_ERROR_STATUSES)}")
        return value

    @field_validator("hang", mode="before")
    @classmethod
    def _coerce_hang(cls, value: object) -> object:
        # Boolean shorthand: hang=true means "no first byte" (stall before headers).
        if isinstance(value, bool):
            return HangMode.BEFORE_HEADERS if value else HangMode.NONE
        if isinstance(value, str) and value.lower() in _TRUE_VALUES:
            return HangMode.BEFORE_HEADERS
        if isinstance(value, str) and value.lower() in _FALSE_VALUES:
            return HangMode.NONE
        return value

    @classmethod
    def from_overrides(cls, overrides: Mapping[str, Any]) -> FakeKnobs:
        """Validate ``overrides`` on top of the defaults; raise ``KnobError`` if invalid."""
        unknown = sorted(set(overrides) - set(cls.model_fields))
        if unknown:
            raise KnobError(f"unknown knob(s): {', '.join(unknown)}")
        try:
            return cls.model_validate(dict(overrides))
        except ValidationError as exc:
            raise KnobError(_describe(exc)) from exc


class KnobStore:
    """Process-wide knob overrides set through the admin endpoints."""

    def __init__(self) -> None:
        self._overrides: dict[str, Any] = {}

    def overrides(self) -> dict[str, Any]:
        """Return a copy of the current global overrides."""
        return dict(self._overrides)

    def update(self, patch: Mapping[str, Any]) -> FakeKnobs:
        """Merge ``patch`` into the global overrides after validating the result."""
        merged = {**self._overrides, **patch}
        knobs = FakeKnobs.from_overrides(merged)
        self._overrides = {name: getattr(knobs, name) for name in sorted(merged)}
        return knobs

    def reset(self) -> None:
        """Drop every global override."""
        self._overrides = {}


class KnobResolver:
    """Combines global overrides with ``x-fake-*`` request headers."""

    def __init__(self, store: KnobStore) -> None:
        self._store = store

    def resolve(self, headers: Mapping[str, str]) -> FakeKnobs:
        """Return the effective knobs; headers win over the global store."""
        return FakeKnobs.from_overrides({**self._store.overrides(), **self._from_headers(headers)})

    @staticmethod
    def _from_headers(headers: Mapping[str, str]) -> dict[str, str]:
        found: dict[str, str] = {}
        for name, value in headers.items():
            lowered = name.lower()
            if lowered.startswith(HEADER_PREFIX):
                found[lowered[len(HEADER_PREFIX) :].replace("-", "_")] = value
        return found


class RngPool:
    """One ``random.Random`` per seed, so a request sequence replays identically."""

    def __init__(self) -> None:
        self._by_seed: dict[int, random.Random] = {}

    def for_seed(self, seed: int) -> random.Random:
        """Return the RNG stream for ``seed``, creating it on first use."""
        if seed not in self._by_seed:
            self._by_seed[seed] = random.Random(seed)  # noqa: S311  # nosec B311 - fault injection, not crypto
        return self._by_seed[seed]

    def reset(self) -> None:
        """Restart every seeded stream from the beginning."""
        self._by_seed = {}


def _describe(exc: ValidationError) -> str:
    parts = [f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in exc.errors()]
    return "; ".join(sorted(parts))

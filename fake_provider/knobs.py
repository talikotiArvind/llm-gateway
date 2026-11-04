"""Fault-injection knobs for the fake provider: model, global store, per-request resolution."""

from __future__ import annotations

import random
from collections.abc import Mapping
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

HEADER_PREFIX = "x-fake-"
QUERY_PREFIX = "fake_"
MATCH_MODEL_KEY = "match_model"
SUPPORTED_ERROR_STATUSES = frozenset({400, 401, 429, 500, 503, 529})
DEFAULT_TEXT = "Hello from the Switchyard fake provider. This reply is deterministic."
MAX_CHUNKS = 1_000
DEFAULT_HANG_MAX_S = 300.0  # every hang ends: a real server never cancels a stalled handler
MAX_HANG_S = 3_600.0
_TRUE_VALUES = frozenset({"true", "1", "yes", "on"})
_FALSE_VALUES = frozenset({"false", "0", "no", "off", ""})


class KnobError(ValueError):
    """Raised when a knob name or value is invalid."""


class HangMode(StrEnum):
    """Where the provider stalls until the client disconnects or ``hang_max_s`` elapses."""

    NONE = "none"
    BEFORE_HEADERS = "before_headers"
    BEFORE_FIRST_CHUNK = "before_first_chunk"
    MID_STREAM = "mid_stream"


class FakeKnobs(BaseModel):
    """Effective knobs for one request.

    Precedence (highest first): ``x-fake-*`` header > ``fake_*`` query > global store
    (a ``match_model`` rule over the unscoped overrides) > defaults.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    latency_ms: int = Field(default=0, ge=0)
    ttft_ms: int = Field(default=0, ge=0)
    inter_chunk_ms: int = Field(default=0, ge=0)
    error_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    error_status: int = 503
    error_codes: tuple[int, ...] | None = Field(default=None, min_length=1)
    retry_after_s: float | None = Field(default=None, ge=0.0)
    hang: HangMode = HangMode.NONE
    hang_max_s: float = Field(default=DEFAULT_HANG_MAX_S, gt=0.0, le=MAX_HANG_S)
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

    @field_validator("error_codes", mode="before")
    @classmethod
    def _split_error_codes(cls, value: object) -> object:
        # Header and query values arrive as "429,503".
        if isinstance(value, str):
            return tuple(part.strip() for part in value.split(",") if part.strip())
        return value

    @field_validator("error_codes")
    @classmethod
    def _check_error_codes(cls, value: tuple[int, ...] | None) -> tuple[int, ...] | None:
        if value is not None:
            for code in value:
                cls._check_error_status(code)
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
    """Process-wide knob overrides set through the admin endpoints.

    Holds unscoped overrides plus ``match_model`` rules keyed by exact model id, in
    insertion order. Exact matching means at most one rule applies; a repeat update for
    the same model merges into its existing rule.
    """

    def __init__(self) -> None:
        self._overrides: dict[str, Any] = {}
        self._scoped: dict[str, dict[str, Any]] = {}

    def overrides(self, model: str | None = None) -> dict[str, Any]:
        """Return a copy of the global overrides, with the matching model rule on top."""
        merged = dict(self._overrides)
        if model is not None:
            merged.update(self._scoped.get(model, {}))
        return merged

    def update(self, patch: Mapping[str, Any], match_model: str | None = None) -> FakeKnobs:
        """Merge ``patch`` into the unscoped overrides or the ``match_model`` rule."""
        if match_model is None:
            merged = {**self._overrides, **patch}
            knobs = FakeKnobs.from_overrides(merged)
            self._overrides = self._normalised(knobs, merged)
            return knobs
        rule = {**self._scoped.get(match_model, {}), **patch}
        knobs = FakeKnobs.from_overrides({**self._overrides, **rule})
        self._scoped[match_model] = self._normalised(knobs, rule)
        return knobs

    def reset(self) -> None:
        """Drop every global override and model rule."""
        self._overrides = {}
        self._scoped = {}

    @staticmethod
    def _normalised(knobs: FakeKnobs, names: Mapping[str, Any]) -> dict[str, Any]:
        return {name: getattr(knobs, name) for name in sorted(names)}


class KnobResolver:
    """Combines global overrides with ``fake_*`` query params and ``x-fake-*`` headers."""

    def __init__(self, store: KnobStore) -> None:
        self._store = store

    def resolve(
        self,
        headers: Mapping[str, str],
        query: Mapping[str, str] | None = None,
        model: str | None = None,
    ) -> FakeKnobs:
        """Return the effective knobs: header > query > global (model-scoped) > defaults."""
        layered = {
            **self._store.overrides(model),
            **self._prefixed(query or {}, QUERY_PREFIX),
            **self._prefixed(headers, HEADER_PREFIX),
        }
        return FakeKnobs.from_overrides(layered)

    @staticmethod
    def _prefixed(source: Mapping[str, str], prefix: str) -> dict[str, str]:
        found: dict[str, str] = {}
        for name, value in source.items():
            lowered = name.lower()
            if lowered.startswith(prefix):
                found[lowered[len(prefix) :].replace("-", "_")] = value
        return found


class RngPool:
    """One ``random.Random`` per seed, so a request sequence replays identically.

    Streams are process-global per seed and seeded RNGs are used for fault injection, not
    crypto. Replay is deterministic only for sequential requests: concurrent requests with
    the same seed interleave their draws.
    """

    def __init__(self) -> None:
        self._by_seed: dict[int, random.Random] = {}

    def for_seed(self, seed: int) -> random.Random:
        """Return the RNG stream for ``seed``, creating it on first use."""
        if seed not in self._by_seed:
            self._by_seed[seed] = random.Random(seed)  # noqa: S311  # nosec B311
        return self._by_seed[seed]

    def reset(self) -> None:
        """Restart every seeded stream from the beginning."""
        self._by_seed = {}


def split_match_model(patch: Mapping[str, Any]) -> tuple[dict[str, Any], str | None]:
    """Separate the optional ``match_model`` scope from a global knob patch."""
    knobs = {name: value for name, value in patch.items() if name != MATCH_MODEL_KEY}
    match_model = patch.get(MATCH_MODEL_KEY)
    if match_model is None:
        return knobs, None
    if not isinstance(match_model, str) or not match_model.strip():
        raise KnobError("match_model must be a non-empty string")
    return knobs, match_model


def _describe(exc: ValidationError) -> str:
    parts = [f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in exc.errors()]
    return "; ".join(sorted(parts))

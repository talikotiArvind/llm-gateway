"""Shared fakes for fake_provider tests: a clock that never really sleeps."""

from __future__ import annotations


class HangCalledError(Exception):
    """Raised by ``FakeClock.hang`` so a stall is observable without waiting."""


class FakeClock:
    """Records requested sleeps and turns ``hang`` into an immediate exception."""

    NOW = 1_700_000_000.5

    def __init__(self) -> None:
        self.sleeps: list[float] = []
        self.hangs = 0

    def now(self) -> float:
        """Return a fixed timestamp."""
        return self.NOW

    async def sleep(self, seconds: float) -> None:
        """Record ``seconds`` and return immediately."""
        self.sleeps.append(seconds)

    async def hang(self) -> None:
        """Record the stall and raise instead of waiting forever."""
        self.hangs += 1
        raise HangCalledError

"""Shared fakes for fake_provider tests: a clock that never really sleeps."""

from __future__ import annotations


class FakeClock:
    """Records requested sleeps; each sleep advances the monotonic time instantly."""

    NOW = 1_700_000_000.5

    def __init__(self) -> None:
        self.sleeps: list[float] = []
        self.elapsed = 0.0

    def now(self) -> float:
        """Return a fixed timestamp."""
        return self.NOW

    def monotonic(self) -> float:
        """Return the total time "slept" so far."""
        return self.elapsed

    async def sleep(self, seconds: float) -> None:
        """Record ``seconds``, advance the monotonic time and return immediately."""
        self.sleeps.append(seconds)
        self.elapsed += max(seconds, 0.0)

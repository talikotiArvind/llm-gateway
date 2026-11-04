"""Liveness and readiness endpoints (FR-03)."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from enum import StrEnum
from typing import Literal, Protocol

from fastapi import APIRouter, Response, status
from pydantic import BaseModel, ConfigDict

logger = logging.getLogger(__name__)

# Dependencies reported as not_configured until their probes land (T14: database, redis).
EXPECTED_DEPENDENCIES: tuple[str, ...] = ("database", "redis")


class ProbeStatus(StrEnum):
    """Outcome of a single readiness dependency check."""

    OK = "ok"
    FAILED = "failed"
    NOT_CONFIGURED = "not_configured"


class ReadinessProbe(Protocol):
    """An async dependency check registered with the readiness endpoint."""

    @property
    def name(self) -> str:
        """Dependency name reported in the readiness payload."""
        ...

    async def check(self) -> bool:
        """Return True when the dependency is usable."""
        ...


class LivenessReport(BaseModel):
    """Body of ``GET /healthz``."""

    model_config = ConfigDict(frozen=True)

    status: Literal["ok"] = "ok"


class ReadinessReport(BaseModel):
    """Body of ``GET /readyz``; ``checks`` is ordered by dependency name."""

    model_config = ConfigDict(frozen=True)

    status: Literal["ready", "not_ready"]
    checks: dict[str, ProbeStatus]


class ReadinessChecker:
    """Runs registered probes and reports every expected dependency."""

    def __init__(
        self,
        probes: Sequence[ReadinessProbe] = (),
        expected: Sequence[str] = EXPECTED_DEPENDENCIES,
    ) -> None:
        names = [probe.name for probe in probes]
        if len(names) != len(set(names)):
            raise ValueError(f"duplicate readiness probe names: {sorted(names)}")
        self._probes = tuple(probes)
        self._expected = tuple(expected)

    async def check(self) -> ReadinessReport:
        """Run every probe once and aggregate the results."""
        results = {name: ProbeStatus.NOT_CONFIGURED for name in self._expected}
        for probe in self._probes:
            results[probe.name] = await self._run_probe(probe)
        ready = ProbeStatus.FAILED not in results.values()
        return ReadinessReport(
            status="ready" if ready else "not_ready",
            checks=dict(sorted(results.items())),
        )

    @staticmethod
    async def _run_probe(probe: ReadinessProbe) -> ProbeStatus:
        try:
            healthy = await probe.check()
        except Exception:
            # A probe failure must surface as not_ready, never as a 500 from /readyz.
            logger.exception("readiness probe %s raised", probe.name)
            return ProbeStatus.FAILED
        return ProbeStatus.OK if healthy else ProbeStatus.FAILED


def build_health_router(checker: ReadinessChecker) -> APIRouter:
    """Create the router serving ``/healthz`` and ``/readyz``."""
    router = APIRouter(tags=["health"])

    @router.get("/healthz")
    async def healthz() -> LivenessReport:
        return LivenessReport()

    @router.get("/readyz")
    async def readyz(response: Response) -> ReadinessReport:
        report = await checker.check()
        if report.status != "ready":
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return report

    return router

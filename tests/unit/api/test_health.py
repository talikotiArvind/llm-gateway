"""Unit tests for the health endpoints and ``create_app`` (FR-03)."""

from __future__ import annotations

import asyncio
import os
import unittest
from dataclasses import dataclass
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from switchyard.api.app import create_app
from switchyard.api.health import (
    ProbeStatus,
    ReadinessChecker,
    build_health_router,
)
from switchyard.infrastructure.settings import Settings


@dataclass(frozen=True)
class StubProbe:
    """Readiness probe with a fixed outcome."""

    name: str
    healthy: bool = True
    error: bool = False

    async def check(self) -> bool:
        if self.error:
            raise ConnectionError("unreachable")
        return self.healthy


def _client_for(checker: ReadinessChecker) -> TestClient:
    app = FastAPI()
    app.include_router(build_health_router(checker))
    return TestClient(app)


@pytest.mark.unit
class CreateAppTest(unittest.TestCase):
    """The factory serves health endpoints with injected or env-loaded settings."""

    def setUp(self) -> None:
        self.settings = Settings(secrets_backend="env")
        self.client = TestClient(create_app(self.settings))

    def test_healthz_returns_ok(self) -> None:
        response = self.client.get("/healthz")
        self.assertEqual(200, response.status_code)
        self.assertEqual({"status": "ok"}, response.json())

    def test_readyz_without_probes_reports_not_configured(self) -> None:
        response = self.client.get("/readyz")
        self.assertEqual(200, response.status_code)
        expected_checks = {"database": "not_configured", "redis": "not_configured"}
        self.assertEqual({"status": "ready", "checks": expected_checks}, response.json())

    def test_injected_settings_are_kept_on_state(self) -> None:
        app = create_app(self.settings)
        self.assertIs(self.settings, app.state.settings)

    def test_factory_without_arguments_loads_settings_from_env(self) -> None:
        with patch.dict(os.environ, {"SWITCHYARD_SECRETS_BACKEND": "env"}, clear=True):
            app = create_app()
        self.assertEqual("env", app.state.settings.secrets_backend)


@pytest.mark.unit
class ReadinessCheckerTest(unittest.TestCase):
    """Probe aggregation, ordering and failure handling."""

    def test_healthy_probes_report_ok_sorted_by_name(self) -> None:
        checker = ReadinessChecker([StubProbe("redis"), StubProbe("database")])
        report = asyncio.run(checker.check())
        self.assertEqual("ready", report.status)
        self.assertEqual(["database", "redis"], list(report.checks))
        self.assertEqual({ProbeStatus.OK}, set(report.checks.values()))

    def test_unhealthy_probe_returns_503(self) -> None:
        client = _client_for(ReadinessChecker([StubProbe("database", healthy=False)]))
        response = client.get("/readyz")
        self.assertEqual(503, response.status_code)
        self.assertEqual("not_ready", response.json()["status"])
        self.assertEqual("failed", response.json()["checks"]["database"])
        self.assertEqual("not_configured", response.json()["checks"]["redis"])

    def test_raising_probe_is_reported_failed(self) -> None:
        checker = ReadinessChecker([StubProbe("redis", error=True)])
        with self.assertLogs("switchyard.api.health", level="ERROR"):
            report = asyncio.run(checker.check())
        self.assertEqual("not_ready", report.status)
        self.assertEqual(ProbeStatus.FAILED, report.checks["redis"])

    def test_extra_probe_is_included(self) -> None:
        checker = ReadinessChecker([StubProbe("policy")], expected=())
        report = asyncio.run(checker.check())
        self.assertEqual({"policy": ProbeStatus.OK}, report.checks)

    def test_duplicate_probe_names_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ReadinessChecker([StubProbe("redis"), StubProbe("redis")])

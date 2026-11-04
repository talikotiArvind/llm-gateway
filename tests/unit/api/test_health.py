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
from pydantic import ValidationError

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


@pytest.mark.unit
class HealthHttpContractTest(unittest.TestCase):
    """Status codes, bodies, content type and allowed methods of /healthz and /readyz."""

    def setUp(self) -> None:
        self.client = TestClient(create_app(Settings()))

    def test_healthz_body_is_exactly_status_ok(self) -> None:
        self.assertEqual({"status": "ok"}, self.client.get("/healthz").json())

    def test_healthz_is_json(self) -> None:
        response = self.client.get("/healthz")
        self.assertEqual("application/json", response.headers["content-type"])

    def test_readyz_is_json(self) -> None:
        response = self.client.get("/readyz")
        self.assertEqual("application/json", response.headers["content-type"])

    def test_readyz_without_probes_returns_200(self) -> None:
        self.assertEqual(200, self.client.get("/readyz").status_code)

    def test_non_get_methods_on_health_routes_return_405(self) -> None:
        for path in ("/healthz", "/readyz"):
            for method in ("POST", "PUT", "PATCH", "DELETE"):
                with self.subTest(path=path, method=method):
                    response = self.client.request(method, path)
                    self.assertEqual(405, response.status_code)
                    self.assertIn("GET", response.headers["allow"])

    def test_unknown_path_returns_404(self) -> None:
        self.assertEqual(404, self.client.get("/health").status_code)


@pytest.mark.unit
class LivenessHasNoIoTest(unittest.TestCase):
    """/healthz reports process liveness only and never runs readiness probes (FR-03)."""

    def test_healthz_stays_200_when_dependencies_fail(self) -> None:
        probe = StubProbe("database", error=True)
        client = _client_for(ReadinessChecker([probe]))
        with patch.object(ReadinessChecker, "check") as mock_check:
            response = client.get("/healthz")
        self.assertEqual(200, response.status_code)
        mock_check.assert_not_called()


@pytest.mark.unit
class ReadinessHttpTest(unittest.TestCase):
    """/readyz maps probe outcomes to 200 / 503 with an ordered JSON body."""

    def test_all_probes_healthy_returns_200_ready(self) -> None:
        client = _client_for(ReadinessChecker([StubProbe("database"), StubProbe("redis")]))
        response = client.get("/readyz")
        self.assertEqual(200, response.status_code)
        self.assertEqual(
            {"status": "ready", "checks": {"database": "ok", "redis": "ok"}}, response.json()
        )

    def test_raising_probe_returns_503_not_500(self) -> None:
        client = _client_for(ReadinessChecker([StubProbe("redis", error=True)]))
        with self.assertLogs("switchyard.api.health", level="ERROR"):
            response = client.get("/readyz")
        self.assertEqual(503, response.status_code)
        self.assertEqual("failed", response.json()["checks"]["redis"])

    def test_503_body_is_json(self) -> None:
        client = _client_for(ReadinessChecker([StubProbe("database", healthy=False)]))
        response = client.get("/readyz")
        self.assertEqual("application/json", response.headers["content-type"])

    def test_checks_are_ordered_by_name(self) -> None:
        checker = ReadinessChecker([StubProbe("zeta"), StubProbe("alpha")], expected=())
        response = _client_for(checker).get("/readyz")
        self.assertEqual(["alpha", "zeta"], list(response.json()["checks"]))


@pytest.mark.unit
class CreateAppFactoryTest(unittest.TestCase):
    """``create_app`` builds an independent app on every call."""

    def test_each_call_returns_a_new_app(self) -> None:
        settings = Settings()
        self.assertIsNot(create_app(settings), create_app(settings))

    def test_apps_do_not_share_state(self) -> None:
        first = create_app(Settings())
        second = create_app(Settings(secrets_backend="env"))
        self.assertEqual("aws", first.state.settings.secrets_backend)
        self.assertEqual("env", second.state.settings.secrets_backend)

    def test_repeated_calls_expose_the_same_routes(self) -> None:
        settings = Settings()
        first_paths = sorted(create_app(settings).openapi()["paths"])
        second_paths = sorted(create_app(settings).openapi()["paths"])
        self.assertEqual(["/healthz", "/readyz"], first_paths)
        self.assertEqual(first_paths, second_paths)

    def test_factory_without_arguments_fails_fast_on_invalid_env(self) -> None:
        with (
            patch.dict(os.environ, {"SWITCHYARD_MAX_MESSAGES": "abc"}, clear=True),
            self.assertRaises(ValidationError),
        ):
            create_app()

    def test_factory_without_arguments_rejects_unknown_env(self) -> None:
        with (
            patch.dict(os.environ, {"SWITCHYARD_BOGUS": "1"}, clear=True),
            self.assertRaises(ValidationError),
        ):
            create_app()

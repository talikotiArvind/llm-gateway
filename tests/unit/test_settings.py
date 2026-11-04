"""Unit tests for ``switchyard.infrastructure.settings.Settings``."""

from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from switchyard.infrastructure.settings import Settings


@pytest.mark.unit
class SettingsTest(unittest.TestCase):
    """Settings defaults, env overrides and fail-fast validation (Part 03 section 6)."""

    def _build(self, **env: str) -> Settings:
        with patch.dict(os.environ, env, clear=True):
            return Settings()

    def test_defaults_match_design(self) -> None:
        settings = self._build()
        self.assertEqual(Path("config/models.yaml"), settings.models_path)
        self.assertEqual(1_048_576, settings.max_body_bytes)
        self.assertEqual(256, settings.max_messages)
        self.assertEqual(65_536, settings.max_tool_payload_bytes)
        self.assertEqual("model", settings.max_tokens_cap)
        self.assertEqual("http://otel-collector:4317/", str(settings.otel_exporter_otlp_endpoint))
        self.assertEqual("us-east-1", settings.aws_region)
        self.assertEqual("aws", settings.secrets_backend)
        self.assertEqual(600, settings.default_rpm)
        self.assertEqual(200_000, settings.default_tpm)
        self.assertEqual(20, settings.default_concurrency)

    def test_env_overrides_with_prefix(self) -> None:
        settings = self._build(
            SWITCHYARD_MAX_BODY_BYTES="2048",
            SWITCHYARD_SECRETS_BACKEND="env",
            SWITCHYARD_AWS_REGION="eu-west-1",
        )
        self.assertEqual(2048, settings.max_body_bytes)
        self.assertEqual("env", settings.secrets_backend)
        self.assertEqual("eu-west-1", settings.aws_region)

    def test_unprefixed_env_is_ignored(self) -> None:
        self.assertEqual(1_048_576, self._build(MAX_BODY_BYTES="5").max_body_bytes)

    def test_non_integer_limit_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            self._build(SWITCHYARD_MAX_BODY_BYTES="abc")

    def test_non_positive_limit_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            self._build(SWITCHYARD_DEFAULT_RPM="0")

    def test_unknown_secrets_backend_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            self._build(SWITCHYARD_SECRETS_BACKEND="vault")

    def test_unknown_field_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            Settings(not_a_field=1)  # type: ignore[call-arg]

    def test_settings_are_immutable(self) -> None:
        settings = self._build()
        with self.assertRaises(ValidationError):
            settings.max_messages = 1  # type: ignore[misc]

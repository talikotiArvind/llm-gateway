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

    def test_unknown_prefixed_env_var_rejected(self) -> None:
        with self.assertRaises(ValidationError) as ctx:
            self._build(SWITCHYARD_DEFAULT_RMP="50")
        self.assertIn("SWITCHYARD_DEFAULT_RMP", str(ctx.exception))

    def test_unknown_env_vars_listed_sorted(self) -> None:
        with self.assertRaises(ValidationError) as ctx:
            self._build(SWITCHYARD_ZETA="1", SWITCHYARD_ALPHA="1", SWITCHYARD_AWS_REGION="x")
        self.assertIn("SWITCHYARD_ALPHA, SWITCHYARD_ZETA", str(ctx.exception))

    def test_unknown_env_var_check_is_case_insensitive(self) -> None:
        with self.assertRaises(ValidationError):
            self._build(switchyard_bogus="1")

    def test_known_env_var_in_lower_case_accepted(self) -> None:
        self.assertEqual(7, self._build(switchyard_default_rpm="7").default_rpm)

    def test_reserved_provider_key_env_vars_allowed(self) -> None:
        settings = self._build(
            SWITCHYARD_PROVIDER_KEY_OPENAI="sk-test", SWITCHYARD_SECRETS_BACKEND="env"
        )
        self.assertEqual("env", settings.secrets_backend)

    def test_unknown_env_var_rejected_for_kwargs_construction(self) -> None:
        with (
            patch.dict(os.environ, {"SWITCHYARD_BOGUS": "1"}, clear=True),
            self.assertRaises(ValidationError),
        ):
            Settings(default_rpm=5)

    def test_settings_are_immutable(self) -> None:
        settings = self._build()
        with self.assertRaises(ValidationError):
            settings.max_messages = 1  # type: ignore[misc]

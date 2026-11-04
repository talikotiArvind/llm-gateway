"""Unit tests for ``switchyard.infrastructure.settings.Settings``."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
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


INT_FIELDS: tuple[str, ...] = (
    "MAX_BODY_BYTES",
    "MAX_MESSAGES",
    "MAX_TOOL_PAYLOAD_BYTES",
    "DEFAULT_RPM",
    "DEFAULT_TPM",
    "DEFAULT_CONCURRENCY",
)


def _build_from_env(**env: str) -> Settings:
    with patch.dict(os.environ, env, clear=True):
        return Settings()


@pytest.mark.unit
class SettingsTypeValidationTest(unittest.TestCase):
    """Every field rejects values of the wrong type (Part 03 section 6, fail fast)."""

    def test_every_int_field_rejects_non_integer_text(self) -> None:
        for field in INT_FIELDS:
            with self.subTest(field=field), self.assertRaises(ValidationError):
                _build_from_env(**{f"SWITCHYARD_{field}": "abc"})

    def test_every_int_field_rejects_fractional_value(self) -> None:
        for field in INT_FIELDS:
            with self.subTest(field=field), self.assertRaises(ValidationError):
                _build_from_env(**{f"SWITCHYARD_{field}": "1.5"})

    def test_every_int_field_rejects_negative_value(self) -> None:
        for field in INT_FIELDS:
            with self.subTest(field=field), self.assertRaises(ValidationError):
                _build_from_env(**{f"SWITCHYARD_{field}": "-1"})

    def test_every_int_field_accepts_integer_override(self) -> None:
        for field in INT_FIELDS:
            with self.subTest(field=field):
                settings = _build_from_env(**{f"SWITCHYARD_{field}": "42"})
                self.assertEqual(42, getattr(settings, field.lower()))

    def test_max_tokens_cap_rejects_other_modes(self) -> None:
        with self.assertRaises(ValidationError):
            _build_from_env(SWITCHYARD_MAX_TOKENS_CAP="none")

    def test_max_tokens_cap_accepts_model(self) -> None:
        settings = _build_from_env(SWITCHYARD_MAX_TOKENS_CAP="model")
        self.assertEqual("model", settings.max_tokens_cap)

    def test_secrets_backend_accepts_aws_and_env(self) -> None:
        for backend in ("aws", "env"):
            with self.subTest(backend=backend):
                settings = _build_from_env(SWITCHYARD_SECRETS_BACKEND=backend)
                self.assertEqual(backend, settings.secrets_backend)

    def test_otel_endpoint_rejects_non_url(self) -> None:
        with self.assertRaises(ValidationError):
            _build_from_env(SWITCHYARD_OTEL_EXPORTER_OTLP_ENDPOINT="not a url")

    def test_otel_endpoint_accepts_url_override(self) -> None:
        settings = _build_from_env(SWITCHYARD_OTEL_EXPORTER_OTLP_ENDPOINT="http://collector:4318")
        self.assertEqual("collector", settings.otel_exporter_otlp_endpoint.host)
        self.assertEqual(4318, settings.otel_exporter_otlp_endpoint.port)

    def test_models_path_override_is_a_path(self) -> None:
        settings = _build_from_env(SWITCHYARD_MODELS_PATH="custom/models.yaml")
        self.assertEqual(Path("custom/models.yaml"), settings.models_path)

    def test_models_path_rejects_non_path_value(self) -> None:
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(ValidationError):
            Settings(models_path=123)  # type: ignore[arg-type]

    def test_aws_region_rejects_non_string_value(self) -> None:
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(ValidationError):
            Settings(aws_region=5)  # type: ignore[arg-type]

    def test_aws_region_env_override(self) -> None:
        self.assertEqual(
            "ap-south-1", _build_from_env(SWITCHYARD_AWS_REGION="ap-south-1").aws_region
        )


@pytest.mark.unit
class SettingsUnknownEnvCaseTest(unittest.TestCase):
    """Unknown ``SWITCHYARD_*`` names are matched case-insensitively on every platform."""

    _ENVIRON_LOOKUP = "switchyard.infrastructure.settings.os"

    def _build_with_raw_environ(self, environ: dict[str, str]) -> Settings:
        # Windows upper-cases os.environ keys, so mixed-case names are injected where the
        # module looks them up to keep the case-insensitivity check meaningful everywhere.
        with (
            patch.dict(os.environ, {}, clear=True),
            patch(self._ENVIRON_LOOKUP, SimpleNamespace(environ=environ)),
        ):
            return Settings()

    def test_mixed_case_unknown_var_rejected(self) -> None:
        with self.assertRaises(ValidationError) as ctx:
            self._build_with_raw_environ({"SwitchYard_Bogus": "1"})
        self.assertIn("SwitchYard_Bogus", str(ctx.exception))

    def test_lower_case_typo_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            self._build_with_raw_environ({"switchyard_default_rmp": "1"})

    def test_mixed_case_known_var_not_rejected(self) -> None:
        settings = self._build_with_raw_environ({"Switchyard_Max_Messages": "9"})
        self.assertIsInstance(settings, Settings)

    def test_mixed_case_provider_key_var_not_rejected(self) -> None:
        settings = self._build_with_raw_environ({"switchyard_provider_key_gemini": "k"})
        self.assertIsInstance(settings, Settings)

    def test_bare_prefix_var_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            self._build_with_raw_environ({"SWITCHYARD_": "1"})

    def test_vars_without_exact_prefix_ignored(self) -> None:
        settings = self._build_with_raw_environ({"SWITCHYARDX_BOGUS": "1", "OTHER": "2"})
        self.assertIsInstance(settings, Settings)


@pytest.mark.unit
class SettingsProviderKeyCarveOutTest(unittest.TestCase):
    """``SWITCHYARD_PROVIDER_KEY_<PROVIDER>`` belongs to the env secrets backend, not Settings."""

    def test_every_provider_key_var_allowed(self) -> None:
        settings = _build_from_env(
            SWITCHYARD_PROVIDER_KEY_OPENAI="a",
            SWITCHYARD_PROVIDER_KEY_ANTHROPIC="b",
            SWITCHYARD_PROVIDER_KEY_GEMINI="c",
        )
        self.assertEqual("aws", settings.secrets_backend)

    def test_provider_key_value_not_captured_by_settings(self) -> None:
        settings = _build_from_env(SWITCHYARD_PROVIDER_KEY_OPENAI="sk-secret-value")
        self.assertNotIn("sk-secret-value", repr(settings))
        self.assertNotIn("sk-secret-value", str(settings.model_dump()))

    def test_carve_out_does_not_hide_lookalike_unknown_var(self) -> None:
        with self.assertRaises(ValidationError) as ctx:
            _build_from_env(SWITCHYARD_PROVIDER_KEY_OPENAI="a", SWITCHYARD_PROVIDER_KEYS="b")
        self.assertIn("SWITCHYARD_PROVIDER_KEYS", str(ctx.exception))
        self.assertNotIn("SWITCHYARD_PROVIDER_KEY_OPENAI", str(ctx.exception))


@pytest.mark.unit
class SettingsNoDotEnvTest(unittest.TestCase):
    """No ``.env`` file is read (Part 03 section 6, FR-70, NFR-14)."""

    def setUp(self) -> None:
        self._cwd = Path.cwd()
        self._tmp = tempfile.TemporaryDirectory()
        os.chdir(self._tmp.name)

    def tearDown(self) -> None:
        os.chdir(self._cwd)
        self._tmp.cleanup()

    def _write_dotenv(self, content: str) -> None:
        Path(self._tmp.name, ".env").write_text(content, encoding="utf-8")

    def test_dotenv_values_are_not_applied(self) -> None:
        self._write_dotenv("SWITCHYARD_MAX_MESSAGES=7\nSWITCHYARD_SECRETS_BACKEND=env\n")
        settings = _build_from_env()
        self.assertEqual(256, settings.max_messages)
        self.assertEqual("aws", settings.secrets_backend)

    def test_dotenv_unknown_var_does_not_reach_validation(self) -> None:
        self._write_dotenv("SWITCHYARD_BOGUS=1\n")
        self.assertEqual(1_048_576, _build_from_env().max_body_bytes)

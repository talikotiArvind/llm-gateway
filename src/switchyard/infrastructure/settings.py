"""Process configuration loaded from ``SWITCHYARD_*`` environment variables."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from pydantic import AnyUrl, Field, PositiveInt, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_MAX_BODY_BYTES = 1_048_576  # OQ-05: 1 MiB, larger bodies get 413
DEFAULT_MAX_MESSAGES = 256
DEFAULT_MAX_TOOL_PAYLOAD_BYTES = 65_536  # OQ-05: 64 KiB
DEFAULT_RPM = 600
DEFAULT_TPM = 200_000
DEFAULT_CONCURRENCY = 20
ENV_PREFIX = "SWITCHYARD_"
# Read directly by other components, not by Settings: the "env" secrets backend.
RESERVED_ENV_PREFIXES = ("SWITCHYARD_PROVIDER_KEY_",)


class Settings(BaseSettings):
    """Typed gateway settings; invalid or unknown values fail at construction.

    Unknown ``SWITCHYARD_*`` environment variables are rejected too (``extra="forbid"`` only
    covers init kwargs), so a typo such as ``SWITCHYARD_DEFAULT_RMP`` cannot silently fall back
    to a default. ``RESERVED_ENV_PREFIXES`` are exempt.

    Only fields that need no I/O live here for now. Database/Redis fields are added
    by T14 and API-key HMAC fields by T21.
    """

    # No env_file: production config comes only from the process environment.
    model_config = SettingsConfigDict(
        env_prefix=ENV_PREFIX,
        extra="forbid",
        frozen=True,
    )

    models_path: Path = Path("config/models.yaml")
    max_body_bytes: PositiveInt = DEFAULT_MAX_BODY_BYTES
    max_messages: PositiveInt = DEFAULT_MAX_MESSAGES
    max_tool_payload_bytes: PositiveInt = DEFAULT_MAX_TOOL_PAYLOAD_BYTES
    # "model" caps max_tokens at the selected model's max_output_tokens (OQ-05).
    max_tokens_cap: Literal["model"] = "model"
    otel_exporter_otlp_endpoint: AnyUrl = AnyUrl("http://otel-collector:4317")
    aws_region: str = Field(default="us-east-1", min_length=1)
    # "env" is test/dev only: provider keys come from SWITCHYARD_PROVIDER_KEY_<PROVIDER>.
    secrets_backend: Literal["aws", "env"] = "aws"
    default_rpm: PositiveInt = DEFAULT_RPM
    default_tpm: PositiveInt = DEFAULT_TPM
    default_concurrency: PositiveInt = DEFAULT_CONCURRENCY

    @model_validator(mode="before")
    @classmethod
    def _reject_unknown_env(cls, data: object) -> object:
        unknown = sorted(name for name in os.environ if cls._is_unknown_env(name))
        if unknown:
            raise ValueError(f"unknown {ENV_PREFIX}* environment variable(s): {', '.join(unknown)}")
        return data

    @classmethod
    def _is_unknown_env(cls, name: str) -> bool:
        upper = name.upper()
        if not upper.startswith(ENV_PREFIX) or upper.startswith(RESERVED_ENV_PREFIXES):
            return False
        return upper[len(ENV_PREFIX) :].lower() not in cls.model_fields

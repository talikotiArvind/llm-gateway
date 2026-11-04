"""Shared pytest fixtures for all test suites."""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

SETTINGS_ENV_PREFIX = "SWITCHYARD_"


@pytest.fixture(autouse=True)
def clean_switchyard_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Remove every ``SWITCHYARD_*`` variable so tests never see the host config."""
    for name in sorted(os.environ):
        if name.startswith(SETTINGS_ENV_PREFIX):
            monkeypatch.delenv(name, raising=False)
    yield

"""FastAPI application factory for the gateway."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import FastAPI

from switchyard.api.health import ReadinessChecker, build_health_router

if TYPE_CHECKING:
    from switchyard.infrastructure.settings import Settings


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the gateway app; ``uvicorn --factory`` calls this with no arguments.

    M0 scope: health endpoints only. Lifespan wiring (DB, Redis, workers) lands with T14.
    """
    resolved = settings if settings is not None else _load_settings()
    app = FastAPI(title="Switchyard", version="0.1.0")
    app.state.settings = resolved
    app.include_router(build_health_router(ReadinessChecker()))
    return app


def _load_settings() -> Settings:
    # Lazy import: Settings is only needed at runtime when uvicorn passes no settings.
    from switchyard.infrastructure.settings import Settings

    return Settings()

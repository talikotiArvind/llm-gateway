# syntax=docker/dockerfile:1.7
# Switchyard gateway image: uv builder stage + slim non-root runtime.

FROM python:3.12-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never
WORKDIR /app
# Dependencies first so source edits do not invalidate the dependency layer.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.12-slim AS runtime
ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
RUN groupadd --system --gid 10001 switchyard \
    && useradd --system --uid 10001 --gid switchyard --no-create-home switchyard
WORKDIR /app
COPY --from=builder --chown=switchyard:switchyard /app/.venv /app/.venv
USER switchyard
EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=3s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=2)"]
CMD ["uvicorn", "switchyard.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080"]

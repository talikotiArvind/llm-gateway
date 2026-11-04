# Fake OpenAI-shaped provider. Build context is this directory: `docker build fake_provider/`.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN pip install "fastapi==0.162.0" "pydantic==2.14.2" "uvicorn[standard]==0.54.0" \
    && useradd --create-home --uid 10001 fake

COPY --chown=fake:fake . /app/fake_provider

USER fake
EXPOSE 9000

HEALTHCHECK --interval=10s --timeout=3s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:9000/v1/models')"

CMD ["uvicorn", "fake_provider.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "9000"]

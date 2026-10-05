# syntax=docker/dockerfile:1.7
#
# Production image for the FastAPI backend.
#
#   builder  resolves the locked dependencies into /app/.venv with uv
#   runtime  copies only that venv and the source onto a clean slim image
#            and runs as an unprivileged user
#
# The fastembed model is not baked in: it downloads on first use into
# FASTEMBED_CACHE_PATH, which docker-compose.yml backs with a volume so the
# download happens once per machine rather than once per container.

ARG PYTHON_VERSION=3.12

FROM ghcr.io/astral-sh/uv:0.12.23 AS uv

FROM python:${PYTHON_VERSION}-slim AS builder
COPY --from=uv /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app

# Dependencies in their own layer, so an app-code change doesn't bust the
# (slow) dependency-install cache. --extra local-embeddings pulls in the
# key-free ONNX embedding provider, which is the documented default.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    uv sync --frozen --no-install-project --no-dev --extra local-embeddings

COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --extra local-embeddings


FROM python:${PYTHON_VERSION}-slim AS runtime

LABEL org.opencontainers.image.title="jarvis-backend" \
      org.opencontainers.image.description="FastAPI backend: semantic job matching and ATS-scored LaTeX resume tailoring" \
      org.opencontainers.image.source="https://github.com/thakurabhishek7283/chase"

RUN useradd --system --uid 10001 --create-home --home-dir /home/app app \
    && mkdir -p /app/data \
    && chown app:app /app/data

WORKDIR /app
COPY --from=builder --chown=app:app /app /app

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    JARVIS_DATA_DIR=/app/data \
    FASTEMBED_CACHE_PATH=/app/data/fastembed \
    JARVIS_FAILURE_DUMP_DIR=/app/data/failure_dumps

USER app
EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=5 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=4)"]

ENTRYPOINT ["/app/entrypoint.sh"]
# --proxy-headers: behind the frontend's nginx, take the client address from
# X-Forwarded-For — but only from peers in FORWARDED_ALLOW_IPS (uvicorn reads
# that variable itself; it defaults to 127.0.0.1). WEB_CONCURRENCY, also read
# by uvicorn, sets the worker count; see the README before raising it.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]

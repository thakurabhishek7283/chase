FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app

# Dependencies in their own layer so an app-code change doesn't bust the
# (slow) dependency-install cache. --extra local-embeddings pulls in the
# key-free ONNX embedding provider, which is the documented default.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev --extra local-embeddings

COPY . .
RUN uv sync --frozen --no-dev --extra local-embeddings

ENV PATH="/app/.venv/bin:${PATH}"

EXPOSE 8000
ENTRYPOINT ["sh", "entrypoint.sh"]

FROM ghcr.io/astral-sh/uv:0.11.13 AS uv

FROM python:3.12-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_PROGRESS=1 \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /workspace/services/reflex-cloud
COPY --from=uv /uv /usr/local/bin/uv
COPY --from=reflex_core / /workspace/packages/reflex-core
COPY --from=provider_minimax / /workspace/plugins/provider-minimax
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev --extra postgres --no-editable

FROM python:3.12-slim

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY --from=template_pack / /app/template-packs/builtin

RUN useradd --create-home --uid 10001 reflex && mkdir -p /app/data && chown -R reflex:reflex /app
USER reflex

EXPOSE 8787
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8787/health/ready', timeout=3)" || exit 1
CMD ["uvicorn", "reflex_cloud.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8787", "--no-proxy-headers"]

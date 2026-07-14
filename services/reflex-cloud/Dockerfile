FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY --from=reflex_core / /opt/reflex-core
COPY --from=provider_minimax / /opt/reflex-provider-minimax
COPY --from=template_pack / /app/template-packs/builtin
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir /opt/reflex-core /opt/reflex-provider-minimax '.[postgres]'

RUN useradd --create-home --uid 10001 reflex && mkdir -p /app/data && chown -R reflex:reflex /app
USER reflex

EXPOSE 8787
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8787/health/ready', timeout=3)" || exit 1
CMD ["uvicorn", "reflex_cloud.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8787", "--proxy-headers", "--forwarded-allow-ips", "*"]

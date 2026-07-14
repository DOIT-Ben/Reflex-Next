FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY packages/reflex-core /opt/reflex-core
COPY plugins/provider-minimax /opt/reflex-provider-minimax
COPY template-packs/builtin /app/template-packs/builtin
COPY services/reflex-cloud/pyproject.toml services/reflex-cloud/README.md ./
COPY services/reflex-cloud/src ./src
RUN pip install --no-cache-dir /opt/reflex-core /opt/reflex-provider-minimax '.[postgres]'

RUN useradd --create-home --uid 10001 reflex && mkdir -p /app/data && chown -R reflex:reflex /app
USER reflex

EXPOSE 8787
CMD ["uvicorn", "reflex_cloud.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8787"]

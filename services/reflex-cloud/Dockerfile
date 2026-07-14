FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir '.[postgres]'

RUN useradd --create-home --uid 10001 reflex && mkdir -p /app/data && chown -R reflex:reflex /app
USER reflex

EXPOSE 8787
CMD ["uvicorn", "reflex_cloud.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8787"]

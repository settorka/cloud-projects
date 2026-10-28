FROM python:3.12.12-slim AS base
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
COPY pyproject.toml uv.lock ./
RUN pip install --no-cache-dir uv==0.13.5 && uv sync --frozen --no-dev --no-install-project
COPY src ./src
COPY migrations ./migrations
RUN uv sync --frozen --no-dev --no-editable
FROM base AS runtime
RUN useradd --uid 10001 --create-home maritime
USER maritime
ENV PATH="/app/.venv/bin:$PATH"
ENTRYPOINT ["python", "-m", "v1.bootstrap"]
CMD ["api"]

FROM base AS test
RUN uv sync --frozen
COPY tests ./tests
COPY tools ./tools
COPY .env.example ./.env.example
COPY .dockerignore ./.dockerignore
COPY Dockerfile ./Dockerfile
COPY deploy/v2/compose.yaml ./deploy/v2/compose.yaml
COPY deploy/v2/otel-collector.yaml ./deploy/v2/otel-collector.yaml
ENV PATH="/app/.venv/bin:$PATH"
CMD ["pytest", "-q"]

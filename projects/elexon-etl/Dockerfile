FROM python:3.13-slim@sha256:2d44738ebf4ce5f63b9d9ea871e9c7cfdc0426f7b0c97cac915fd88ded1d86bb
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY pyproject.toml uv.lock ./
# uv is a build tool only; the application runs as an unprivileged user.
RUN pip install --no-cache-dir uv==0.13.5 \
    && uv sync --frozen --no-dev --no-install-project --no-cache \
    && useradd --create-home --uid 10001 pipeline \
    && mkdir /app/data && chown pipeline:pipeline /app/data
COPY src ./src
RUN uv sync --frozen --no-dev --no-cache
ENV PATH="/app/.venv/bin:$PATH"
USER pipeline
ENTRYPOINT ["elexon-etl"]

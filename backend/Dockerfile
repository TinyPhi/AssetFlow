# SPDX-FileCopyrightText: 2026 TinyPhi <conduct@tinyphi.com>
# SPDX-License-Identifier: AGPL-3.0-only
# Multi-stage secure build for AssetFlow Backend (§B13.1)

FROM ghcr.io/astral-sh/uv:0.5.21 AS uv-installer
FROM python:3.12-slim AS runtime

# Install libpq and runtime utilities
RUN apt-get update && apt-get upgrade -y && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Copy uv binary from official image
COPY --from=uv-installer /uv /uvx /bin/

# Non-root user
ARG UID=10001
ARG GID=10001
RUN groupadd -g ${GID} assetflow && \
    useradd -u ${UID} -g assetflow -m -s /bin/bash assetflow

WORKDIR /app

# Copy dependency specifications and lockfile
COPY pyproject.toml uv.lock ./

# Install dependencies into system environment or virtualenv
RUN uv sync --frozen --no-dev --no-install-project

# Copy application source and database migration files
COPY app ./app
COPY migrations ./migrations
COPY alembic.ini ./

# Ensure permissions
RUN chown -R assetflow:assetflow /app

USER assetflow

EXPOSE 8080

HEALTHCHECK --interval=10s --timeout=5s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:8080/healthz || exit 1

ENTRYPOINT ["uv", "run", "--no-sync", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]

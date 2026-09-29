# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
# Image for scripts/bootstrap_zitadel.py (docs/operations/zitadel.md). Build context: the
# repository root (compose: context "..", dockerfile "deploy/bootstrap/Dockerfile").
# Dependencies come from the script's inline metadata (PEP 723), the single list of pins.
FROM python:3.12.14-slim-bookworm

COPY --from=ghcr.io/astral-sh/uv:0.12.20 /uv /usr/local/bin/uv

WORKDIR /app
COPY scripts/bootstrap_zitadel.py /app/bootstrap_zitadel.py
RUN uv pip install --system --no-cache --requirements /app/bootstrap_zitadel.py

# Runs as root only to read the first-instance key from the Zitadel bootstrap volume and
# delete it; files written into the checkout are given to the checkout's owner.
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 ASSETFLOW_ROOT=/workspace
ENTRYPOINT ["python", "/app/bootstrap_zitadel.py"]
CMD ["apply"]

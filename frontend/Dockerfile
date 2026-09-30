# SPDX-FileCopyrightText: 2026 TinyPhi <conduct@tinyphi.com>
# SPDX-License-Identifier: AGPL-3.0-only
# Multi-stage secure build for AssetFlow Frontend Web Shell (§B13.1)

FROM node:22-alpine AS builder

WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm ci

COPY . .
RUN npm run build

FROM nginxinc/nginx-unprivileged:alpine-slim AS runtime

# Copy build artifacts to non-root nginx html directory
COPY --from=builder --chown=101:101 /app/dist /usr/share/nginx/html
# The nginx configuration (deploy/nginx/default.conf) is mounted by compose; it lies outside this build context.

USER 101

EXPOSE 8080

HEALTHCHECK --interval=10s --timeout=5s --start-period=5s --retries=3 \
  CMD wget --no-verbose --tries=1 --spider http://localhost:8080/ || exit 1

CMD ["nginx", "-g", "daemon off;"]

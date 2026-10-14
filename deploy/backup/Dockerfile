# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
# pgBackRest backup service container (§B13.5, M1.6-T9).

FROM alpine:3.20

RUN apk add --no-cache \
    bash \
    curl \
    gettext \
    jq \
    pgbackrest \
    postgresql16-client \
    tzdata \
    && rm -rf /var/cache/apk/*

ARG UID=10001
ARG GID=10001

RUN addgroup -g ${GID} assetflow && \
    adduser -u ${UID} -G assetflow -s /bin/bash -D assetflow && \
    mkdir -p /etc/pgbackrest /var/log/pgbackrest /var/lib/pgbackrest /var/spool/pgbackrest /backup && \
    chown -R assetflow:assetflow /etc/pgbackrest /var/log/pgbackrest /var/lib/pgbackrest /var/spool/pgbackrest /backup

COPY backup-daemon.sh /usr/local/bin/backup-daemon.sh
RUN chmod 755 /usr/local/bin/backup-daemon.sh

USER assetflow

ENTRYPOINT ["/usr/local/bin/backup-daemon.sh"]

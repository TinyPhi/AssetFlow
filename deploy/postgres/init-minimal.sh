#!/bin/sh
# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
# Database roles and permissions for the minimal profile (§B10, §B13.1, ADR-0019).
#
# Runs as the one-shot `db-roles` service on every `make up-minimal`, so an existing database is
# brought to the current standard too, not only a new one. Idempotent: roles are created when
# missing, passwords are re-applied from the secrets files, and logins with the legacy
# `assetflow_<kind>_user` names are renamed to `assetflow_<kind>_login`.

set -eu

# Connect over the network as the bootstrap user; the password comes from a file, never the env.
if [ -n "${PGPASSWORD_FILE:-}" ]; then
    PGPASSWORD=$(cat "$PGPASSWORD_FILE")
    export PGPASSWORD
fi

API_PASSWORD=$(cat /run/secrets/database/api/password)
WORKER_PASSWORD=$(cat /run/secrets/database/worker/password)
MIGRATOR_PASSWORD=$(cat /run/secrets/database/migrator/password)

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    -- Group roles (NOLOGIN) per 0000_roles.py and master plan §B10
    DO \$\$
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'assetflow_api') THEN
            CREATE ROLE assetflow_api NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOREPLICATION;
        END IF;
        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'assetflow_worker') THEN
            CREATE ROLE assetflow_worker NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOREPLICATION;
        END IF;
        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'assetflow_migrator') THEN
            CREATE ROLE assetflow_migrator NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOREPLICATION;
        END IF;
        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'assetflow_readonly') THEN
            CREATE ROLE assetflow_readonly NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOREPLICATION;
        END IF;
        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'assetflow_resolver') THEN
            CREATE ROLE assetflow_resolver NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOREPLICATION;
        END IF;
    END
    \$\$;

    -- Resolver setup and schema privileges for migrator
    GRANT assetflow_resolver TO assetflow_migrator WITH INHERIT FALSE, SET TRUE;
    GRANT USAGE, CREATE ON SCHEMA public TO assetflow_migrator;
    GRANT CREATE ON DATABASE "$POSTGRES_DB" TO assetflow_migrator;

    -- Legacy login names (assetflow_<kind>_user, before ADR-0019): rename when the new name is free,
    -- otherwise disable the old login so only one credential per process kind can connect.
    DO \$\$
    DECLARE
        kind text;
    BEGIN
        FOREACH kind IN ARRAY ARRAY['api', 'worker', 'migrator'] LOOP
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'assetflow_' || kind || '_user') THEN
                IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'assetflow_' || kind || '_login') THEN
                    EXECUTE format('ALTER ROLE %I RENAME TO %I',
                                   'assetflow_' || kind || '_user', 'assetflow_' || kind || '_login');
                ELSE
                    EXECUTE format('ALTER ROLE %I NOLOGIN', 'assetflow_' || kind || '_user');
                END IF;
            END IF;
        END LOOP;
    END
    \$\$;

    -- Login users assigned to group roles
    DO \$\$
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'assetflow_api_login') THEN
            CREATE ROLE assetflow_api_login WITH LOGIN PASSWORD '$API_PASSWORD';
        ELSE
            ALTER ROLE assetflow_api_login WITH PASSWORD '$API_PASSWORD';
        END IF;
        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'assetflow_worker_login') THEN
            CREATE ROLE assetflow_worker_login WITH LOGIN PASSWORD '$WORKER_PASSWORD';
        ELSE
            ALTER ROLE assetflow_worker_login WITH PASSWORD '$WORKER_PASSWORD';
        END IF;
        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'assetflow_migrator_login') THEN
            CREATE ROLE assetflow_migrator_login WITH LOGIN PASSWORD '$MIGRATOR_PASSWORD';
        ELSE
            ALTER ROLE assetflow_migrator_login WITH PASSWORD '$MIGRATOR_PASSWORD';
        END IF;
    END
    \$\$;

    GRANT assetflow_api TO assetflow_api_login;
    GRANT assetflow_worker TO assetflow_worker_login;
    GRANT assetflow_migrator TO assetflow_migrator_login;

    -- Connect privileges
    GRANT CONNECT ON DATABASE "$POSTGRES_DB" TO assetflow_api_login;
    GRANT CONNECT ON DATABASE "$POSTGRES_DB" TO assetflow_worker_login;
    GRANT CONNECT ON DATABASE "$POSTGRES_DB" TO assetflow_migrator_login;
EOSQL

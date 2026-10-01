#!/bin/sh
# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
# Database roles and permissions bootstrap for the minimal profile (§B10, §B13.1).

set -eu

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

    -- Login users assigned to group roles
    DO \$\$
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'assetflow_api_user') THEN
            CREATE ROLE assetflow_api_user WITH LOGIN PASSWORD '$API_PASSWORD';
        ELSE
            ALTER ROLE assetflow_api_user WITH PASSWORD '$API_PASSWORD';
        END IF;
        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'assetflow_worker_user') THEN
            CREATE ROLE assetflow_worker_user WITH LOGIN PASSWORD '$WORKER_PASSWORD';
        ELSE
            ALTER ROLE assetflow_worker_user WITH PASSWORD '$WORKER_PASSWORD';
        END IF;
        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'assetflow_migrator_user') THEN
            CREATE ROLE assetflow_migrator_user WITH LOGIN PASSWORD '$MIGRATOR_PASSWORD';
        ELSE
            ALTER ROLE assetflow_migrator_user WITH PASSWORD '$MIGRATOR_PASSWORD';
        END IF;
    END
    \$\$;

    GRANT assetflow_api TO assetflow_api_user;
    GRANT assetflow_worker TO assetflow_worker_user;
    GRANT assetflow_migrator TO assetflow_migrator_user;

    -- Connect privileges
    GRANT CONNECT ON DATABASE "$POSTGRES_DB" TO assetflow_api_user;
    GRANT CONNECT ON DATABASE "$POSTGRES_DB" TO assetflow_worker_user;
    GRANT CONNECT ON DATABASE "$POSTGRES_DB" TO assetflow_migrator_user;
EOSQL

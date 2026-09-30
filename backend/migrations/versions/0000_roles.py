# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Database group roles (§B10, §B11, §C4.8, glossary "Database roles").

Revision ID: 0000_roles
Revises:
Create Date: 2026-09-30 00:00:00.000000

Creates the NOLOGIN group roles every AssetFlow login user belongs to:

  assetflow_api        the API processes (reads and writes tenant data under RLS)
  assetflow_worker     the worker processes (§B9.3)
  assetflow_migrator   runs migrations and owns the schema objects
  assetflow_readonly   read-only reporting and support access (still under RLS)
  assetflow_resolver   owns platform.resolve_organization() only; never granted to a login user

None of them is a superuser, has BYPASSRLS, or may create databases or roles. The API, worker and
read-only roles cannot create objects in the public schema.

Login users are NOT created here: the operator (or the bootstrap) creates one LOGIN user per process
kind with a password stored in the secrets provider and grants it exactly one group role, e.g.

  CREATE ROLE assetflow_api_login LOGIN PASSWORD '<from OpenBao>' IN ROLE assetflow_api;

Roles are cluster-wide, so this revision is idempotent: a role that already exists is kept, but its
attributes are verified and the migration fails if one is a superuser, has BYPASSRLS, can create
databases or roles, or (for the group roles) can log in. Creating the roles the first time needs a
user with CREATEROLE (the PostgreSQL bootstrap user); later runs by the migrator need no such right.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0000_roles"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

GROUP_ROLES = (
    "assetflow_api",
    "assetflow_worker",
    "assetflow_migrator",
    "assetflow_readonly",
    "assetflow_resolver",
)
APP_ROLES = ("assetflow_api", "assetflow_worker", "assetflow_readonly")


def _ensure_role_sql(role: str) -> str:
    # role is one of the fixed GROUP_ROLES names above, never input.
    if role not in GROUP_ROLES:
        raise ValueError(f"unknown role {role}")
    return f"""
DO $roles$
DECLARE
    r pg_catalog.pg_roles%ROWTYPE;
BEGIN
    SELECT * INTO r FROM pg_catalog.pg_roles WHERE rolname = '{role}';
    IF NOT FOUND THEN
        CREATE ROLE {role} NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOREPLICATION;
    ELSIF r.rolsuper OR r.rolbypassrls OR r.rolcreatedb OR r.rolcreaterole OR r.rolreplication
          OR r.rolcanlogin THEN
        RAISE EXCEPTION 'role {role} exists with unsafe attributes; fix it by hand before migrating'
            USING DETAIL = 'superuser, bypassrls, createdb, createrole, replication or login is set';
    END IF;
END
$roles$
"""  # noqa: S608 - role is a fixed constant


def upgrade() -> None:
    for role in GROUP_ROLES:
        op.execute(_ensure_role_sql(role))

    # The migrator must be able to hand platform.resolve_organization() to assetflow_resolver (0001),
    # which needs SET on that role. The membership must NOT inherit: RLS policies apply to every role
    # that has the privileges of their target role, so an inheriting migrator would read all
    # organizations through the resolver's policy. PostgreSQL 16+ (INHERIT/SET grant options).
    op.execute("""
DO $grant$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_catalog.pg_auth_members m
        WHERE m.roleid = 'assetflow_resolver'::regrole AND m.inherit_option
    ) THEN
        RAISE EXCEPTION 'a role inherits assetflow_resolver; revoke that membership before migrating';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_catalog.pg_auth_members m
        WHERE m.roleid = 'assetflow_resolver'::regrole
          AND m.member = 'assetflow_migrator'::regrole
          AND m.set_option
    ) THEN
        GRANT assetflow_resolver TO assetflow_migrator WITH INHERIT FALSE, SET TRUE;
    END IF;
END
$grant$
""")

    # Schema rights in this database. PostgreSQL 15+ already refuses CREATE on public to PUBLIC; the
    # revoke keeps that true on clusters upgraded from older versions.
    op.execute("""
DO $schema$
BEGIN
    IF pg_catalog.has_schema_privilege('public', 'public', 'CREATE') THEN
        REVOKE CREATE ON SCHEMA public FROM PUBLIC;
    END IF;
    IF NOT pg_catalog.has_schema_privilege('assetflow_migrator', 'public', 'CREATE') THEN
        GRANT USAGE, CREATE ON SCHEMA public TO assetflow_migrator;
    END IF;
END
$schema$
""")
    op.execute(
        "GRANT USAGE ON SCHEMA public TO " + ", ".join(APP_ROLES) + ", assetflow_resolver",
    )
    for role in APP_ROLES:
        op.execute(f"""
DO $check$
BEGIN
    IF pg_catalog.has_schema_privilege('{role}', 'public', 'CREATE') THEN
        RAISE EXCEPTION 'role {role} can create objects in schema public; revoke it before migrating';
    END IF;
END
$check$
""")


def downgrade() -> None:
    op.execute(
        "REVOKE ALL ON SCHEMA public FROM " + ", ".join(GROUP_ROLES),
    )
    for role in reversed(GROUP_ROLES):
        # DROP ROLE fails while the role still owns objects or holds rights in any database of the
        # cluster, so a role in use by another AssetFlow database is never removed silently.
        op.execute(f"DROP ROLE IF EXISTS {role}")

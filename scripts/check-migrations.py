#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Migration lint: multi-tenant database safety rules (master plan §B10, §C4.8, §C5.4, D6).

Migrations are Alembic files that run raw SQL (decision D6). The SQL is taken from the string
arguments of `op.execute(...)` / `sa.text(...)` calls; `.sql` files are read as they are.

Every table created by a migration is a tenant table unless marked otherwise, and must have:
  1. an `organization_id ... NOT NULL` column;
  2. `ALTER TABLE ... ENABLE ROW LEVEL SECURITY` and `... FORCE ROW LEVEL SECURITY`;
  3. four policies, one each `FOR SELECT`, `FOR INSERT`, `FOR UPDATE`, `FOR DELETE`, each comparing
     `organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid`
     (USING for SELECT/UPDATE/DELETE, WITH CHECK for INSERT/UPDATE), so an unset context matches nothing;
  4. an index (or primary key / unique constraint) whose first column is `organization_id`.
Views must be created `WITH (security_invoker = true)`; materialized views are refused (D6).
`SECURITY DEFINER` functions must `SET search_path = pg_catalog, pg_temp` and have
`REVOKE ... ON FUNCTION <name> ... FROM PUBLIC` in the same migration (§B5 organizations row).

Exceptions:
  * Platform table (the `organizations` table itself): put the marker comment
    `-- check-migrations: platform-table` inside its CREATE TABLE statement. Rules 2 and 3 still apply,
    with `id` in place of `organization_id`; rules 1 and 4 are waived.
  * Worker claim policies (§B9.3): on `outbox` and `maintenance_schedules` only, extra policies
    `FOR SELECT` or `FOR UPDATE` granted `TO assetflow_worker` (and no other role) may omit the
    organization comparison. The four organization policies are still required.
  * Organization resolver (§B5.2): on a platform table only, one extra policy `FOR SELECT` granted
    `TO assetflow_resolver` (and no other role) may omit the organization comparison; it lets the
    SECURITY DEFINER sign-in resolver read (id, idp_organization_id, status) before any context is set.

Usage:
    check-migrations.py            lint backend/migrations/versions/*.py and *.sql
    check-migrations.py PATH...    lint these files or directories
"""

from __future__ import annotations

import ast
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DIR = REPO_ROOT / "backend" / "migrations" / "versions"
PLATFORM_MARKER = "check-migrations: platform-table"
WORKER_ROLE = "assetflow_worker"
WORKER_CLAIM_TABLES = {"outbox", "maintenance_schedules"}
RESOLVER_ROLE = "assetflow_resolver"
POLICY_COMMANDS = ("SELECT", "INSERT", "UPDATE", "DELETE")

IDENT = r'(?:"[^"]+"|[A-Za-z_][A-Za-z0-9_$]*)'
QNAME = rf"{IDENT}(?:\s*\.\s*{IDENT})?"
ORG_CONTEXT = (
    r"NULLIF\s*\(\s*current_setting\s*\(\s*'app\.organization_id'\s*,\s*true\s*\)\s*,\s*''\s*\)\s*::\s*uuid"
)


def bare(name: str) -> str:
    """Normalize `schema."Table"` to `table` (lowercase, unquoted, schema dropped)."""
    last = re.split(r"\s*\.\s*", name.strip())[-1]
    return last.strip('"').lower()


def full(name: str) -> str:
    return ".".join(p.strip('"').lower() for p in re.split(r"\s*\.\s*", name.strip()))


# ---------------------------------------------------------------- SQL extraction


def _call_name(func: ast.expr) -> str:
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return ""


def _string_value(node: ast.expr) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts = [
            v.value if isinstance(v, ast.Constant) and isinstance(v.value, str) else "__expr__"
            for v in node.values
        ]
        return "".join(parts)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _string_value(node.left), _string_value(node.right)
        if left is not None and right is not None:
            return left + right
    return None


def sql_from_python(source: str, problems: list[str], label: str) -> str:
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        problems.append(f"{label}: cannot parse migration: {exc}")
        return ""
    chunks: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _call_name(node.func)
        if name in {"create_table", "create_view"}:
            problems.append(
                f"{label}:{node.lineno}: op.{name}() is not allowed; write raw SQL with op.execute() (D6)"
            )
        if name in {"execute", "text"} and node.args:
            value = _string_value(node.args[0])
            if value is not None:
                chunks.append(value)
    return ";\n".join(chunks)


def split_statements(sql: str) -> list[str]:
    """Split on `;` outside quotes, dollar-quoted bodies and comments. Comments are kept."""
    statements: list[str] = []
    buf: list[str] = []
    i, n = 0, len(sql)
    while i < n:
        ch = sql[i]
        if sql.startswith("--", i):
            end = sql.find("\n", i)
            end = n if end == -1 else end
            buf.append(sql[i:end])
            i = end
            continue
        if sql.startswith("/*", i):
            end = sql.find("*/", i + 2)
            end = n if end == -1 else end + 2
            buf.append(sql[i:end])
            i = end
            continue
        if ch == "'":
            j = i + 1
            while j < n:
                if sql[j] == "'" and j + 1 < n and sql[j + 1] == "'":
                    j += 2
                    continue
                if sql[j] == "'":
                    break
                j += 1
            buf.append(sql[i : j + 1])
            i = j + 1
            continue
        if ch == "$":
            m = re.match(r"\$([A-Za-z_][A-Za-z0-9_]*)?\$", sql[i:])
            if m:
                tag = m.group(0)
                end = sql.find(tag, i + len(tag))
                end = n if end == -1 else end + len(tag)
                buf.append(sql[i:end])
                i = end
                continue
        if ch == ";":
            statements.append("".join(buf).strip())
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    tail = "".join(buf).strip()
    if tail:
        statements.append(tail)
    return [s for s in statements if s]


def strip_comments(stmt: str) -> str:
    stmt = re.sub(r"--[^\n]*", " ", stmt)
    return re.sub(r"/\*.*?\*/", " ", stmt, flags=re.DOTALL)


def paren_body(text: str, open_index: int) -> str:
    depth = 0
    for j in range(open_index, len(text)):
        if text[j] == "(":
            depth += 1
        elif text[j] == ")":
            depth -= 1
            if depth == 0:
                return text[open_index + 1 : j]
    return text[open_index + 1 :]


# ---------------------------------------------------------------- lint


@dataclass
class Policy:
    name: str
    command: str
    roles: list[str]
    using: str
    check: str


@dataclass
class Table:
    name: str
    body: str
    platform: bool
    enable_rls: bool = False
    force_rls: bool = False
    has_org_index: bool = False
    policies: list[Policy] = field(default_factory=list)


def policy_clause(stmt: str, keyword: str) -> str:
    m = re.search(rf"\b{keyword}\s*\(", stmt, re.IGNORECASE)
    return paren_body(stmt, m.end() - 1) if m else ""


def lint_sql(sql: str, label: str) -> list[str]:
    problems: list[str] = []
    tables: dict[str, Table] = {}
    definer_functions: list[str] = []
    revoked: set[str] = set()

    raw_statements = split_statements(sql)
    for raw in raw_statements:
        stmt = strip_comments(raw).strip()
        flat = re.sub(r"\s+", " ", stmt)

        m = re.match(
            rf"CREATE\s+(?:UNLOGGED\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?({QNAME})\s*(\(|PARTITION\s+OF)",
            stmt,
            re.IGNORECASE,
        )
        if m:
            if m.group(2).upper().startswith("PARTITION"):
                continue  # partitions inherit columns and are reached through the parent
            name = bare(m.group(1))
            body = paren_body(stmt, m.start(2))
            tables[name] = Table(name=name, body=body, platform=PLATFORM_MARKER in raw)
            if re.search(r"\b(?:PRIMARY\s+KEY|UNIQUE)\s*\(\s*organization_id\b", body, re.IGNORECASE):
                tables[name].has_org_index = True
            continue

        m = re.match(
            rf"ALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?(?:ONLY\s+)?({QNAME})\s+(ENABLE|FORCE)\s+ROW\s+LEVEL\s+SECURITY\b",
            stmt,
            re.IGNORECASE,
        )
        if m:
            table = tables.get(bare(m.group(1)))
            if table:
                if m.group(2).upper() == "ENABLE":
                    table.enable_rls = True
                else:
                    table.force_rls = True
            continue

        m = re.match(
            rf"CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:CONCURRENTLY\s+)?(?:IF\s+NOT\s+EXISTS\s+)?(?:{QNAME}\s+)?ON\s+"
            rf"(?:ONLY\s+)?({QNAME})\s*(?:USING\s+\w+\s*)?\(\s*\"?organization_id\"?\b",
            stmt,
            re.IGNORECASE,
        )
        if m:
            table = tables.get(bare(m.group(1)))
            if table:
                table.has_org_index = True
            continue

        m = re.match(rf"CREATE\s+POLICY\s+({IDENT})\s+ON\s+({QNAME})\b(.*)$", stmt, re.IGNORECASE | re.DOTALL)
        if m:
            rest = m.group(3)
            cmd = re.search(r"\bFOR\s+(ALL|SELECT|INSERT|UPDATE|DELETE)\b", rest, re.IGNORECASE)
            roles_m = re.search(
                r"\bTO\s+(.+?)(?:\bUSING\b|\bWITH\s+CHECK\b|$)", rest, re.IGNORECASE | re.DOTALL
            )
            roles = (
                [r.strip().strip('"').lower() for r in roles_m.group(1).split(",")] if roles_m else ["public"]
            )
            policy = Policy(
                name=m.group(1).strip('"'),
                command=cmd.group(1).upper() if cmd else "ALL",
                roles=roles,
                using=policy_clause(rest, "USING"),
                check=policy_clause(rest, r"WITH\s+CHECK"),
            )
            table = tables.get(bare(m.group(2)))
            if table:
                table.policies.append(policy)
            else:
                problems.append(
                    f"{label}: policy '{policy.name}' on '{bare(m.group(2))}' is not in the migration that "
                    "creates the table; re-check the table's four policies by hand"
                )
            continue

        if re.match(r"CREATE\s+(?:OR\s+REPLACE\s+)?MATERIALIZED\s+VIEW\b", stmt, re.IGNORECASE):
            problems.append(f"{label}: materialized views are not allowed on tenant data (D6): {flat[:80]}")
            continue

        m = re.match(
            rf"CREATE\s+(?:OR\s+REPLACE\s+)?(?:TEMP(?:ORARY)?\s+)?(?:RECURSIVE\s+)?VIEW\s+({QNAME})(.*?)\bAS\b",
            stmt,
            re.IGNORECASE | re.DOTALL,
        )
        if m:
            options = m.group(2)
            if not re.search(
                r"\bsecurity_invoker\s*(?:=\s*(?:true|on|1|'true'|'on')\b|[,)])", options, re.IGNORECASE
            ):
                problems.append(
                    f"{label}: view '{full(m.group(1))}' must be created WITH (security_invoker = true)"
                )
            continue

        if re.match(r"ALTER\s+VIEW\b", stmt, re.IGNORECASE) and re.search(
            r"security_invoker\s*=\s*(?:false|off|0)", stmt, re.IGNORECASE
        ):
            problems.append(f"{label}: security_invoker must never be turned off: {flat[:80]}")
            continue

        m = re.match(rf"CREATE\s+(?:OR\s+REPLACE\s+)?FUNCTION\s+({QNAME})\s*\(", stmt, re.IGNORECASE)
        if m:
            fname = full(m.group(1))
            # Look only at the function header and options, not inside the dollar-quoted body.
            header = re.sub(r"\$([A-Za-z_][A-Za-z0-9_]*)?\$.*?\$\1\$", " ", stmt, flags=re.DOTALL)
            if re.search(r"\bSECURITY\s+DEFINER\b", header, re.IGNORECASE):
                definer_functions.append(fname)
                sp = re.search(
                    r"\bSET\s+search_path\s*(?:=|TO)\s*([^\n]+?)(?=\s+(?:AS|LANGUAGE|SECURITY|STABLE|IMMUTABLE|VOLATILE|RETURNS|SET|STRICT|PARALLEL|COST)\b|$)",
                    header,
                    re.IGNORECASE,
                )
                paths = [p.strip().strip("'\"").lower() for p in sp.group(1).split(",")] if sp else []
                if paths != ["pg_catalog", "pg_temp"]:
                    problems.append(
                        f"{label}: SECURITY DEFINER function '{fname}' must "
                        "SET search_path = pg_catalog, pg_temp"
                        + (f" (found: {', '.join(paths)})" if paths else " (not set)")
                    )
            continue

        m = re.match(
            rf"REVOKE\s+(?:ALL(?:\s+PRIVILEGES)?|EXECUTE)\s+ON\s+(?:FUNCTION|ROUTINE)\s+({QNAME})\b.*\bFROM\s+(?:[^;]*,\s*)?PUBLIC\b",
            stmt,
            re.IGNORECASE | re.DOTALL,
        )
        if m:
            revoked.add(full(m.group(1)))
            revoked.add(bare(m.group(1)))

    for fname in definer_functions:
        if fname not in revoked and fname.split(".")[-1] not in revoked:
            problems.append(
                f"{label}: SECURITY DEFINER function '{fname}' needs "
                "REVOKE EXECUTE ON FUNCTION ... FROM PUBLIC"
            )

    for table in tables.values():
        problems.extend(lint_table(table, label))
    return problems


def lint_table(table: Table, label: str) -> list[str]:
    problems: list[str] = []
    t = table.name
    column = "id" if table.platform else "organization_id"
    if not table.platform:
        if not re.search(r"\borganization_id\s+uuid\b[^,]*\bNOT\s+NULL\b", table.body, re.IGNORECASE):
            problems.append(f"{label}: table '{t}' needs an 'organization_id uuid NOT NULL' column")
        if not table.has_org_index:
            problems.append(f"{label}: table '{t}' needs an index whose first column is organization_id")
    if not table.enable_rls:
        problems.append(f"{label}: table '{t}' missing ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
    if not table.force_rls:
        problems.append(f"{label}: table '{t}' missing ALTER TABLE {t} FORCE ROW LEVEL SECURITY")

    compare = re.compile(rf"(?<![A-Za-z0-9_\"]){column}\"?\s*=\s*{ORG_CONTEXT}", re.IGNORECASE)
    covered: set[str] = set()
    resolver_policies = 0
    for p in table.policies:
        uses_org = bool(compare.search(p.using) or compare.search(p.check))
        is_worker_claim = (
            t in WORKER_CLAIM_TABLES and p.roles == [WORKER_ROLE] and p.command in {"SELECT", "UPDATE"}
        )
        if p.command == "ALL":
            problems.append(
                f"{label}: policy '{p.name}' on '{t}' must be FOR SELECT/INSERT/UPDATE/DELETE, not ALL"
            )
            continue
        is_resolver = table.platform and p.roles == [RESOLVER_ROLE] and p.command == "SELECT"
        if not uses_org:
            if is_worker_claim:
                continue  # §B9.3 worker claim-policy exception
            if is_resolver and resolver_policies == 0:
                resolver_policies += 1
                continue  # §B5.2 organization resolver exception (one policy, platform table only)
            problems.append(
                f"{label}: policy '{p.name}' on '{t}' must compare {column} = "
                "NULLIF(current_setting('app.organization_id', true), '')::uuid"
            )
            continue
        needs_using = p.command in {"SELECT", "UPDATE", "DELETE"}
        needs_check = p.command in {"INSERT", "UPDATE"}
        if needs_using and not compare.search(p.using):
            problems.append(
                f"{label}: policy '{p.name}' on '{t}' ({p.command}) needs the organization check in USING"
            )
            continue
        if needs_check and not compare.search(p.check):
            problems.append(
                f"{label}: policy '{p.name}' on '{t}' ({p.command}) "
                "needs the organization check in WITH CHECK"
            )
            continue
        covered.add(p.command)
    missing = [c for c in POLICY_COMMANDS if c not in covered]
    if missing:
        problems.append(f"{label}: table '{t}' missing organization policies FOR {', '.join(missing)}")
    return problems


def lint_file(path: Path) -> list[str]:
    try:
        label = path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        label = path.as_posix()
    source = path.read_text(encoding="utf-8", errors="replace")
    problems: list[str] = []
    sql = sql_from_python(source, problems, label) if path.suffix == ".py" else source
    problems.extend(lint_sql(sql, label))
    return problems


def collect(paths: list[Path]) -> list[Path]:
    files: list[Path] = []
    for p in paths:
        if p.is_dir():
            files.extend(
                sorted(f for f in p.iterdir() if f.suffix in {".py", ".sql"} and f.name != "__init__.py")
            )
        elif p.is_file():
            files.append(p)
        else:
            sys.stderr.write(f"Not found: {p}\n")
            sys.exit(2)
    return files


def main(argv: list[str]) -> int:
    if argv:
        files = collect([Path(a).resolve() for a in argv])
    elif DEFAULT_DIR.is_dir():
        files = collect([DEFAULT_DIR])
    else:
        print(
            f"No migrations yet ({DEFAULT_DIR.relative_to(REPO_ROOT).as_posix()} does not exist). "
            "Check passed."
        )
        return 0

    all_problems: list[str] = []
    for f in files:
        all_problems.extend(lint_file(f))

    if all_problems:
        sys.stderr.write(f"Migration safety checks failed with {len(all_problems)} violation(s):\n")
        for p in all_problems:
            sys.stderr.write(f"  {p}\n")
        return 1
    print(f"Migration safety checks passed ({len(files)} file(s)).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

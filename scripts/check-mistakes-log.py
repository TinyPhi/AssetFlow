#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Mistake learning log: kinds of mistakes in one file, their traces in another, linked both ways.

- ``Mistake_Learn.md`` (loaded in every AI session through CLAUDE.md): one row per **active kind**
  of mistake: the rule, the learning comment (why it happens), the check, and links to its traces.
  At most MAX_ACTIVE kinds and MAX_LINES lines, because long always-loaded files make the model
  skip rules.
- ``Mistake_Traces.md`` (never auto-loaded, grows without limit): every **trace**, one occurrence
  each, in id order: where, what the agent was doing, root cause, fix, the proof that nothing else
  broke, an optional reviewer comment, and a link back to its kind. Retired kinds (dormant, or
  enforced by a CI check) move to its "Retired kinds" table with their learning comment.

A repeat is a new trace on the **same kind**; a retired kind comes back to Mistake_Learn.md.
Kind ids are M-NNN and never reused. Trace ids are T-<date>-<4 hex>, so agents working in parallel on
different branches never collide; both files use git's union merge (.gitattributes), so traces and rows
changed on two branches merge without a conflict, and this check catches anything a merge doubled
(run `sync` to rebuild the generated tables). When the traces file passes MAX_TRACE_LINES lines,
`archive` moves traces of retired kinds older than a year to Mistake_Traces_archive/<year>.md.

Commands (run from the repository root):

    check                                    validate both files (default; part of `make lint`)
    find WORDS...                            kinds similar to a description, active or retired
    new --area A --rule R --check C --why W TRACE   add a kind and its first trace
    seen M-NNN TRACE                         add a trace to an existing kind
    retire M-NNN --dormant | --enforced-by PATH
    report                                   what the agent gets wrong, for the owner's review
    archive                                  move old traces of retired kinds to the yearly archive
    sync                                     regenerate the generated tables and links

    TRACE = --where W --trigger T --cause C [--fix F] [--verified V] [--comment X] [--date D]

Standard library only.
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import secrets
import sys
from dataclasses import dataclass, field
from itertools import combinations
from pathlib import Path

ROOT = Path.cwd()
LEARN_FILE = "Mistake_Learn.md"
TRACES_FILE = "Mistake_Traces.md"

MAX_ACTIVE = 20
MAX_LINES = 50
MAX_TRACE_LINES = 2000
ARCHIVE_DIR = "Mistake_Traces_archive"
ESCALATE_AT = 3
DUPLICATE_SIMILARITY = 0.6
AREAS = ("commits", "secrets", "logging", "auth", "tests", "prs-and-ci", "reporting")
STATUSES = ("active", "dormant", "enforced")
PENDING = "pending"
TRACE_LABELS = {
    "where": "Where",
    "trigger": "Trigger",
    "cause": "Root cause",
    "fix": "Fix",
    "verified": "Verified by",
    "comment": "Comment",
}
REQUIRED_TRACE_FIELDS = ("where", "trigger", "cause", "fix", "verified")

_KIND_ID = re.compile(r"M-\d{3}")
_TRACE_ID = re.compile(r"T-\d{8}-[0-9a-f]{4}")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_WORD = re.compile(r"[a-z0-9]+")
_CELL_SPLIT = re.compile(r"(?<!\\)\|")
_TRACE_HEAD = re.compile(r'^### <a id="t-[0-9a-f-]+"></a>(T-\d{8}-[0-9a-f]{4}) · (\S+) · \[(M-\d{3})\]')
_TRACE_FIELD = re.compile(r"^- \*\*([\w ]+):\*\* ?(.*)$")
_STOPWORDS = frozenset(
    {
        "a", "an", "and", "as", "at", "be", "by", "do", "each", "every", "for", "from", "in", "into",
        "is", "it", "its", "never", "no", "not", "of", "on", "one", "only", "or", "own", "the", "to",
        "with", "without", "this", "that",
    }
)  # fmt: skip

LEARN_HEADER = "| ID | Area | Rule: do this, not that | Learning: why it happens | Check | Traces |"
LEARN_RULE = "| --- | --- | --- | --- | --- | --- |"
RETIRED_HEADER = "| ID | Status | Area | Rule | Learning: why it happens | Check | Enforced by | Traces |"
RETIRED_RULE = "| --- | --- | --- | --- | --- | --- | --- | --- |"


# ---------------------------------------------------------------- text helpers


def stem(word: str) -> str:
    """Crude English stem so "logged", "logs" and "logging" all match "log"."""
    for suffix in ("ing", "ed", "s"):
        if len(word) > len(suffix) + 2 and word.endswith(suffix):
            word = word[: -len(suffix)]
            if len(word) > 2 and word[-1] == word[-2]:
                word = word[:-1]
            break
    return word


def words(text: str) -> frozenset[str]:
    """Significant stemmed lower-case words of ``text`` (stop words dropped)."""
    return frozenset(stem(w) for w in _WORD.findall(text.lower()) if w not in _STOPWORDS and len(w) > 1)


def similarity(a: str, b: str) -> float:
    """Jaccard similarity of the significant words of two texts."""
    wa, wb = words(a), words(b)
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)


def cells(line: str) -> list[str]:
    """Cells of a Markdown table row; ``\\|`` stays inside a cell."""
    inner = line.strip().removeprefix("|")
    if inner.endswith("|") and not inner.endswith("\\|"):
        inner = inner[:-1]
    return [c.strip().replace("\\|", "|") for c in _CELL_SPLIT.split(inner)]


def esc(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ").strip()


def _anchor_free(cell: str) -> str:
    """An id cell without its leading HTML anchor."""
    return re.sub(r"^<a id=\"[^\"]*\"></a>", "", cell)


def table_rows(text: str, section: str) -> list[tuple[int, list[str]]]:
    """(line number, cells) of the data rows of the table under ``## <section>``."""
    rows: list[tuple[int, list[str]]] = []
    current = ""
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if line.startswith("## "):
            current = line[3:].strip().lower()
            continue
        if current != section.lower() or not line.startswith("|") or set(line) <= set("|- "):
            continue
        row = cells(line)
        if row[0] != "ID":
            rows.append((number, row))
    return rows


def replace_section(text: str, section: str, body: str) -> str:
    """Replace everything under ``## <section>`` up to the next ``## `` heading."""
    head = f"## {section}"
    start = text.index(head)
    end = text.find("\n## ", start + len(head))
    tail = text[end + 1 :] if end != -1 else ""
    return text[:start] + f"{head}\n\n{body}" + ("\n" + tail if tail else "")


# ---------------------------------------------------------------- model


@dataclass
class Trace:
    ident: str
    date: str
    kind: str
    where: str = ""
    trigger: str = ""
    cause: str = ""
    fix: str = PENDING
    verified: str = PENDING
    comment: str = ""
    source: str = TRACES_FILE

    @property
    def open(self) -> bool:
        return self.fix.lower().startswith(PENDING) or self.verified.lower().startswith(PENDING)


@dataclass
class Kind:
    ident: str
    area: str
    rule: str
    why: str
    check: str
    status: str = "active"
    enforced_by: str = "-"
    listed: list[str] = field(default_factory=list)


class Log:
    """Both files, loaded from a repository root."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.learn_path = root / LEARN_FILE
        self.traces_path = root / TRACES_FILE
        self.learn_text = self.learn_path.read_text(encoding="utf-8")
        self.traces_text = self.traces_path.read_text(encoding="utf-8")
        self.problems: list[str] = []
        self.id_clashes: list[str] = []
        self.kinds: dict[str, Kind] = {}
        self.traces: dict[str, Trace] = {}
        self._parse()

    def _parse(self) -> None:
        for number, row in table_rows(self.learn_text, "Active"):
            row[0] = _anchor_free(row[0])
            if len(row) != 6 or not _KIND_ID.fullmatch(row[0]):
                self.problems.append(f"{LEARN_FILE} line {number}: expected 6 cells starting with M-NNN")
                continue
            self._add(Kind(row[0], row[1], row[2], row[3], row[4], "active", "-", _TRACE_ID.findall(row[5])))
        for number, row in table_rows(self.traces_text, "Retired kinds"):
            if len(row) != 8 or not _KIND_ID.fullmatch(row[0]):
                self.problems.append(f"{TRACES_FILE} line {number}: expected 8 cells starting with M-NNN")
                continue
            self._add(Kind(row[0], row[2], row[3], row[4], row[5], row[1], row[6], _TRACE_ID.findall(row[7])))
        self.archive_texts: dict[str, str] = {}
        archive = self.root / ARCHIVE_DIR
        if archive.is_dir():
            for path in sorted(archive.glob("*.md")):
                self.archive_texts[f"{ARCHIVE_DIR}/{path.name}"] = path.read_text(encoding="utf-8")
        for source, text in [(TRACES_FILE, self.traces_text), *self.archive_texts.items()]:
            self._parse_traces(source, text)

    def _parse_traces(self, source: str, text: str) -> None:
        current: Trace | None = None
        for raw in text.splitlines():
            head = _TRACE_HEAD.match(raw)
            if head:
                ident, date, kind = head.groups()
                if ident in self.traces:
                    self.problems.append(f"{source}: trace id {ident} used twice (run `sync` after a merge)")
                current = Trace(ident, date, kind, source=source)
                self.traces[ident] = current
                continue
            if raw.startswith("#"):
                current = None
                continue
            match = _TRACE_FIELD.match(raw)
            if current is not None and match:
                for name, label in TRACE_LABELS.items():
                    if label == match.group(1).strip():
                        setattr(current, name, match.group(2).strip())

    def _add(self, kind: Kind) -> None:
        existing = self.kinds.get(kind.ident)
        if existing is not None and existing.rule != kind.rule:
            # Two branches each created a new kind with the same next id: never merge them silently.
            self.id_clashes.append(
                f"{kind.ident} is used by two different kinds ('{existing.rule}' and '{kind.rule}'); "
                f"give one of them the next free id by hand, then run `sync`"
            )
            self.problems.append(self.id_clashes[-1])
        elif existing is not None:
            self.problems.append(f"kind {kind.ident} appears more than once (run `sync` after a merge)")
        self.kinds[kind.ident] = kind

    def traces_of(self, kind_id: str) -> list[Trace]:
        return sorted((t for t in self.traces.values() if t.kind == kind_id), key=lambda t: (t.date, t.ident))

    def next_kind_id(self) -> str:
        return f"M-{max((int(i[2:]) for i in self.kinds), default=0) + 1:03d}"

    def new_trace_id(self, date: str) -> str:
        """Date plus 4 random hex digits, sortable by date. Unique within this log only: two branches
        can draw the same id, which `sync` reports after a merge."""
        while True:
            ident = f"T-{date.replace('-', '')}-{secrets.token_hex(2)}"
            if ident not in self.traces:
                return ident

    def relink(self) -> None:
        for kind in self.kinds.values():
            kind.listed = [t.ident for t in self.traces_of(kind.ident)]

    def _links(self, kind_id: str, from_file: str) -> str:
        """Markdown links to the traces of a kind, relative to ``from_file``."""
        out = []
        for trace in self.traces_of(kind_id):
            anchor = f"#{trace.ident.lower()}"
            target = anchor if trace.source == from_file else f"{trace.source}{anchor}"
            out.append(f"[{trace.ident}]({target})")
        return ", ".join(out)

    def _blocks(self, source: str) -> str:
        """The trace blocks that live in ``source``."""
        up = "../" if source.startswith(ARCHIVE_DIR) else ""
        blocks = []
        for t in sorted(
            (t for t in self.traces.values() if t.source == source), key=lambda t: (t.date, t.ident)
        ):
            kind = self.kinds.get(t.kind)
            active = kind is not None and kind.status == "active"
            target = f"{up}{LEARN_FILE}#{t.kind.lower()}" if active else f"{up}{TRACES_FILE}#retired-kinds"
            if not up and not active:
                target = "#retired-kinds"
            lines = [f'### <a id="{t.ident.lower()}"></a>{t.ident} · {t.date} · [{t.kind}]({target})', ""]
            for name, label in TRACE_LABELS.items():
                value = getattr(t, name)
                if value or name != "comment":
                    lines.append(f"- **{label}:** {value}")
            blocks.append("\n".join(lines))
        return "\n\n".join(blocks) + "\n" if blocks else "(none)\n"

    def write(self) -> None:
        """Regenerate both tables and every trace block from the model."""
        self.relink()
        active = sorted((k for k in self.kinds.values() if k.status == "active"), key=lambda k: k.ident)
        retired = sorted((k for k in self.kinds.values() if k.status != "active"), key=lambda k: k.ident)
        learn = [LEARN_HEADER, LEARN_RULE]
        for k in active:
            links = self._links(k.ident, LEARN_FILE) or "-"
            learn.append(
                f'| <a id="{k.ident.lower()}"></a>{k.ident} | {k.area} | {esc(k.rule)} | {esc(k.why)} | '
                f"{esc(k.check)} | {links} |"
            )
        self.learn_text = replace_section(self.learn_text, "Active", "\n".join(learn) + "\n")
        table = [RETIRED_HEADER, RETIRED_RULE]
        for k in retired:
            links = self._links(k.ident, TRACES_FILE) or "-"
            table.append(
                f"| {k.ident} | {k.status} | {k.area} | {esc(k.rule)} | {esc(k.why)} | {esc(k.check)} | "
                f"{esc(k.enforced_by)} | {links} |"
            )
        text = replace_section(self.traces_text, "Retired kinds", "\n".join(table) + "\n")
        self.traces_text = replace_section(text, "Traces", self._blocks(TRACES_FILE))
        for source in sorted({t.source for t in self.traces.values()} - {TRACES_FILE}):
            year = source.rsplit("/", 1)[-1].removesuffix(".md")
            base = self.archive_texts.get(source) or f"# Mistake traces {year} (archive)\n\n## Traces\n"
            self.archive_texts[source] = replace_section(base, "Traces", self._blocks(source))
            (self.root / source).parent.mkdir(exist_ok=True)
            (self.root / source).write_text(self.archive_texts[source], encoding="utf-8", newline="\n")
        self.learn_path.write_text(self.learn_text, encoding="utf-8", newline="\n")
        self.traces_path.write_text(self.traces_text, encoding="utf-8", newline="\n")


# ---------------------------------------------------------------- check


def _runs_in_ci(root: Path, rel: str) -> bool:
    if "/tests/" in f"/{rel}" or Path(rel).name.startswith("test_"):
        return True
    makefile = root / "Makefile"
    return makefile.exists() and rel in makefile.read_text(encoding="utf-8")


def find_problems(log: Log) -> list[str]:
    problems = list(log.problems)
    active = [k for k in log.kinds.values() if k.status == "active"]

    lines = len(log.learn_text.splitlines())
    if lines > MAX_LINES:
        problems.append(f"{LEARN_FILE}: {lines} lines (max {MAX_LINES}); retire quiet or enforced kinds")
    if len(active) > MAX_ACTIVE:
        quiet = sorted(active, key=lambda k: max((t.date for t in log.traces_of(k.ident)), default=""))[:3]
        problems.append(
            f"{LEARN_FILE}: {len(active)} active kinds (max {MAX_ACTIVE}); retire the quietest "
            f"({', '.join(k.ident for k in quiet)}) or add tooling checks"
        )

    trace_lines = len(log.traces_text.splitlines())
    if trace_lines > MAX_TRACE_LINES:
        problems.append(f"{TRACES_FILE}: {trace_lines} lines (max {MAX_TRACE_LINES}); run `archive`")

    for kind in log.kinds.values():
        actual = [t.ident for t in log.traces_of(kind.ident)]
        if kind.status not in STATUSES:
            problems.append(f"{kind.ident}: status must be one of {', '.join(STATUSES)}")
        if kind.area not in AREAS:
            problems.append(f"{kind.ident}: unknown area '{kind.area}' (use one of: {', '.join(AREAS)})")
        for name in ("rule", "why", "check"):
            if not getattr(kind, name):
                problems.append(f"{kind.ident}: empty {name}")
        if not actual:
            problems.append(f"{kind.ident}: no trace in {TRACES_FILE}")
        if kind.listed != actual:
            problems.append(
                f"{kind.ident}: links {kind.listed} do not match its traces {actual} (run `sync`)"
            )
        if kind.status == "active" and len(actual) >= ESCALATE_AT:
            problems.append(
                f"{kind.ident}: {len(actual)} traces while active; the written rule is not sticking. "
                f"Add a check that fails on it, then `retire {kind.ident} --enforced-by <path>`"
            )
        if kind.status == "enforced":
            if kind.enforced_by in ("", "-") or not (log.root / kind.enforced_by).exists():
                problems.append(f"{kind.ident}: enforced, but 'Enforced by' is not an existing file")
            elif not _runs_in_ci(log.root, kind.enforced_by):
                problems.append(
                    f"{kind.ident}: '{kind.enforced_by}' is neither a test nor run by the Makefile, so "
                    "nothing guarantees it runs"
                )

    for trace in log.traces.values():
        where = f"{TRACES_FILE} {trace.ident}"
        if trace.kind not in log.kinds:
            problems.append(f"{where}: links to unknown kind {trace.kind}")
        if not _DATE.fullmatch(trace.date):
            problems.append(f"{where}: date must be YYYY-MM-DD")
        for name in REQUIRED_TRACE_FIELDS:
            if not getattr(trace, name):
                problems.append(f"{where}: empty {TRACE_LABELS[name]}")

    for a, b in combinations(active, 2):
        score = similarity(a.rule, b.rule)
        if score >= DUPLICATE_SIMILARITY:
            problems.append(f"{a.ident} and {b.ident}: rules are {score:.0%} alike; merge the kinds")
        if a.check == b.check:
            problems.append(f"{a.ident} and {b.ident}: same check; merge the kinds")
    return problems


# ---------------------------------------------------------------- commands


def find_similar(log: Log, query: str, limit: int = 5) -> list[tuple[float, Kind]]:
    """Kinds (any status) ranked by overlap of ``query`` with their rule, learning and trace causes."""
    qwords = words(query)
    if not qwords:
        return []
    ranked = []
    for k in log.kinds.values():
        body = " ".join([k.rule, k.why, *(t.trigger + " " + t.cause for t in log.traces_of(k.ident))])
        score = (2 * len(qwords & words(k.rule)) + len(qwords & words(body))) / (3 * len(qwords))
        if score > 0:
            ranked.append((score, k))
    ranked.sort(key=lambda item: (-item[0], item[1].ident))
    return ranked[:limit]


def _new_trace(log: Log, kind_id: str, args: argparse.Namespace) -> Trace:
    date = args.date or dt.datetime.now(tz=dt.UTC).date().isoformat()
    trace = Trace(
        log.new_trace_id(date),
        date,
        kind_id,
        args.where,
        args.trigger,
        args.cause,
        args.fix,
        args.verified,
        args.comment,
    )
    log.traces[trace.ident] = trace
    return trace


def cmd_new(log: Log, args: argparse.Namespace) -> int:
    if args.area not in AREAS:
        print(f"unknown area '{args.area}' (use one of: {', '.join(AREAS)})", file=sys.stderr)
        return 2
    similar = [k for _, k in find_similar(log, args.rule) if similarity(args.rule, k.rule) >= 0.4]
    if similar and not args.force:
        print("Similar kinds exist; add a trace to one of them with `seen` instead:", file=sys.stderr)
        for k in similar:
            print(f"  {k.ident} [{k.status}] {k.rule}", file=sys.stderr)
        print("Use --force only if none of these is the same kind of mistake.", file=sys.stderr)
        return 1
    kind = Kind(log.next_kind_id(), args.area, args.rule, args.why, args.check)
    log.kinds[kind.ident] = kind
    trace = _new_trace(log, kind.ident, args)
    log.write()
    print(f"Added {kind.ident} with its first trace {trace.ident}.")
    return 0


def cmd_seen(log: Log, args: argparse.Namespace) -> int:
    kind = log.kinds.get(args.id)
    if kind is None:
        print(f"no such kind {args.id}", file=sys.stderr)
        return 2
    trace = _new_trace(log, kind.ident, args)
    note = ""
    if kind.status != "active":
        note = f" {kind.ident} was {kind.status} and is active again."
        if kind.status == "enforced":
            note += f" Its check {kind.enforced_by} did not catch this: fix the check too."
        kind.status, kind.enforced_by = "active", "-"
    log.write()
    count = len(log.traces_of(kind.ident))
    if count >= ESCALATE_AT:
        note += f" {count} traces: add a tooling check and retire it as enforced."
    print(f"Recorded {trace.ident} on {kind.ident} ({count} traces).{note}")
    return 0


def cmd_retire(log: Log, args: argparse.Namespace) -> int:
    kind = log.kinds.get(args.id)
    if kind is None:
        print(f"no such kind {args.id}", file=sys.stderr)
        return 2
    if args.enforced_by:
        if not (log.root / args.enforced_by).exists():
            print(f"{args.enforced_by} does not exist", file=sys.stderr)
            return 2
        kind.status, kind.enforced_by = "enforced", args.enforced_by
    else:
        kind.status, kind.enforced_by = "dormant", "-"
    log.write()
    print(f"{kind.ident} is {kind.status}; it moved to {TRACES_FILE} 'Retired kinds' with its traces.")
    return 0


def cmd_archive(log: Log, today: dt.date | None = None) -> int:
    """Move traces of retired kinds that are older than a year to Mistake_Traces_archive/<year>.md."""
    today = today or dt.datetime.now(tz=dt.UTC).date()
    cutoff = (today - dt.timedelta(days=365)).isoformat()
    moved = 0
    for trace in log.traces.values():
        kind = log.kinds.get(trace.kind)
        if trace.source == TRACES_FILE and kind and kind.status != "active" and trace.date < cutoff:
            trace.source = f"{ARCHIVE_DIR}/{trace.date[:4]}.md"
            moved += 1
    log.write()
    print(f"Archived {moved} trace(s) of retired kinds older than {cutoff}.")
    return 0


def report(log: Log) -> str:
    kinds = sorted(log.kinds.values(), key=lambda k: k.ident)
    traces = sorted(log.traces.values(), key=lambda t: t.ident)
    out = [
        f"Kinds: {len(kinds)} ("
        + ", ".join(f"{s} {sum(k.status == s for k in kinds)}" for s in STATUSES)
        + ")",
        f"Traces: {len(traces)}; open fixes: {sum(t.open for t in traces)}",
        "By area:",
    ]
    for area in AREAS:
        n = sum(1 for t in traces if t.kind in log.kinds and log.kinds[t.kind].area == area)
        if n:
            out.append(f"  {area:<11} {n}")
    out.append("Repeated (the rule did not stop it):")
    repeats = [k for k in kinds if len(log.traces_of(k.ident)) > 1]
    for k in repeats:
        out.append(f"  {k.ident} x{len(log.traces_of(k.ident))}  {k.rule}")
    if not repeats:
        out.append("  none")
    out.append("Open (fix or verification pending):")
    opened = [t for t in traces if t.open]
    for t in opened:
        out.append(f"  {t.ident} {t.date} {t.kind}  {t.where}")
    if not opened:
        out.append("  none")
    return "\n".join(out)


def _trace_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--where", required=True, help="PR, commit, plan or file")
    p.add_argument("--trigger", required=True, help="what the agent was doing")
    p.add_argument("--cause", required=True, help="why it went wrong")
    p.add_argument("--fix", default=PENDING)
    p.add_argument("--verified", default=PENDING, help="command and result proving nothing else broke")
    p.add_argument("--comment", default="", help="reviewer's note on this trace")
    p.add_argument("--date", default="")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="check-mistakes-log.py", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("check")
    sub.add_parser("find").add_argument("words", nargs="+")
    p_new = sub.add_parser("new")
    for name in ("--area", "--rule", "--check", "--why"):
        p_new.add_argument(name, required=True)
    p_new.add_argument("--force", action="store_true")
    _trace_args(p_new)
    p_seen = sub.add_parser("seen")
    p_seen.add_argument("id")
    _trace_args(p_seen)
    p_retire = sub.add_parser("retire")
    p_retire.add_argument("id")
    group = p_retire.add_mutually_exclusive_group(required=True)
    group.add_argument("--dormant", action="store_true")
    group.add_argument("--enforced-by", default="")
    sub.add_parser("report")
    sub.add_parser("sync")
    sub.add_parser("archive")
    args = parser.parse_args(argv or ["check"])

    log = Log(ROOT)
    if args.command == "find":
        matches = find_similar(log, " ".join(args.words))
        if not matches:
            print("No similar kind. Add one with `new`.")
        for score, k in matches:
            print(f"  {k.ident} [{k.status}, {len(log.traces_of(k.ident))} traces] ({score:.0%})  {k.rule}")
        return 0
    if args.command == "new":
        return cmd_new(log, args)
    if args.command == "seen":
        return cmd_seen(log, args)
    if args.command == "retire":
        return cmd_retire(log, args)
    if args.command == "report":
        print(report(log))
        return 0
    if args.command == "archive":
        return cmd_archive(log)
    if args.command == "sync":
        if log.id_clashes:
            for clash in log.id_clashes:
                print(clash, file=sys.stderr)
            return 1
        log.write()
        print("Regenerated the tables and the links between kinds and traces.")
        return 0
    problems = find_problems(log)
    if problems:
        print(f"Mistake log: {len(problems)} problem(s):", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        return 1
    active = sum(k.status == "active" for k in log.kinds.values())
    print(
        f"Mistake log check passed ({active}/{MAX_ACTIVE} active kinds, {len(log.traces)} traces, "
        f"{len(log.learn_text.splitlines())}/{MAX_LINES} lines loaded per session)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

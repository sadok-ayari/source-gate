#!/usr/bin/env python3
"""evidence-ledger — a pre-flight gate for any document that makes claims.

Every paragraph, list item and table row in a brief is treated as a claim.
A claim passes only when it cites at least one declared source. The gate is
deliberately dumb and deterministic: no model, no heuristics on meaning.
That is the point -- the check has to be reproducible by a reviewer.

Usage:
    ledger.py check BRIEF [--sources sources.json] [--max-age-months 24] [--json]
    ledger.py check BRIEF --sources sources.json --quiet

Exit codes: 0 pass, 1 blocking findings, 2 usage or input error.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from dataclasses import dataclass, field

CITATION = re.compile(r"\[(S[0-9A-Za-z][0-9A-Za-z._-]*(?:\s*,\s*S[0-9A-Za-z][0-9A-Za-z._-]*)*)\]")
FENCE = re.compile(r"^\s*(```|~~~)")
HEADING = re.compile(r"^\s{0,3}#{1,6}\s")
BLOCKQUOTE = re.compile(r"^\s*>\s?")
LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$")
TABLE_RULE = re.compile(r"^\s*\|[\s:|-]+\|\s*$")

BLOCKING = "BLOCKING"
WARNING = "WARNING"


@dataclass
class Unit:
    """One claim unit: the smallest block a reviewer would sign off on."""

    line: int
    text: str
    kind: str
    tokens: list[str] = field(default_factory=list)


@dataclass
class Finding:
    code: str
    severity: str
    line: int
    message: str


def load_sources(path: str | None) -> dict[str, dict]:
    if not path:
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
    except FileNotFoundError:
        raise SystemExit(f"error: sources file not found: {path}")
    except json.JSONDecodeError as exc:
        raise SystemExit(f"error: sources file is not valid JSON: {exc}")
    if isinstance(raw, dict) and "sources" in raw:
        raw = raw["sources"]
    if not isinstance(raw, dict):
        raise SystemExit("error: sources must be an object of id -> source record")
    return {str(k).upper(): v if isinstance(v, dict) else {} for k, v in raw.items()}


def parse_units(path: str) -> list[Unit]:
    """Split a markdown brief into claim units, ignoring fenced code and headings."""
    try:
        with open(path, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except FileNotFoundError:
        raise SystemExit(f"error: brief not found: {path}")

    units: list[Unit] = []
    in_fence = False
    buffer: list[str] = []
    buffer_start = 0

    def flush(kind: str = "paragraph") -> None:
        nonlocal buffer, buffer_start
        if not buffer:
            return
        text = " ".join(buffer).strip()
        buffer = []
        if not text:
            return
        units.append(Unit(line=buffer_start, text=text, kind=kind,
                          tokens=normalise(CITATION.findall(text))))

    for index, raw in enumerate(lines):
        number = index + 1
        if FENCE.match(raw):
            in_fence = not in_fence
            flush()
            continue
        if in_fence:
            continue
        stripped = raw.strip()
        if not stripped:
            flush()
            continue
        if HEADING.match(raw):
            flush()
            continue
        if BLOCKQUOTE.match(raw):
            flush()
            units.append(Unit(line=number, text=stripped.lstrip("> ").strip(),
                              kind="quote", tokens=normalise(CITATION.findall(stripped))))
            continue
        if TABLE_RULE.match(raw):
            continue
        if TABLE_ROW.match(raw):
            following = lines[index + 1] if index + 1 < len(lines) else ""
            if TABLE_RULE.match(following):
                flush()
                continue  # header row, not a claim
            flush()
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            text = " | ".join(c for c in cells if c)
            units.append(Unit(line=number, text=text, kind="table-row",
                              tokens=normalise(CITATION.findall(text))))
            continue
        if LIST_ITEM.match(raw):
            flush()
            buffer = [LIST_ITEM.sub("", raw).strip()]
            buffer_start = number
            flush(kind="list-item")
            continue
        if not buffer:
            buffer_start = number
        buffer.append(stripped)
    flush()
    return units


def normalise(matches: list[str]) -> list[str]:
    tokens: list[str] = []
    for match in matches:
        for token in match.split(","):
            token = token.strip().upper()
            if token and token not in tokens:
                tokens.append(token)
    return tokens


def parse_date(value: object) -> dt.date | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("/", "-")
    for fmt in ("%Y-%m-%d", "%Y-%m", "%Y"):
        try:
            parsed = dt.datetime.strptime(text, fmt).date()
            if fmt == "%Y-%m":
                parsed = parsed.replace(day=1)
            return parsed
        except ValueError:
            continue
    return None


def check(units: list[Unit], sources: dict[str, dict], max_age_months: int) -> list[Finding]:
    findings: list[Finding] = []
    today = dt.date.today()
    cutoff = today - dt.timedelta(days=int(max_age_months * 30.44))
    cited: set[str] = set()

    for unit in units:
        label = unit.text[:70] + ("..." if len(unit.text) > 70 else "")
        if not unit.tokens:
            findings.append(Finding(
                "UNCITED", BLOCKING, unit.line,
                f"{unit.kind} makes a claim with no source token: \"{label}\""))
            continue
        for token in unit.tokens:
            if token not in sources:
                findings.append(Finding(
                    "UNKNOWN_SOURCE", BLOCKING, unit.line,
                    f"cites {token}, which is not declared in the sources file"))
                continue
            cited.add(token)
            record = sources[token]
            if not str(record.get("url", "")).strip():
                findings.append(Finding(
                    "NO_URL", BLOCKING, unit.line,
                    f"{token} is cited but has no url in the sources file"))
            date = parse_date(record.get("date"))
            if date is None:
                findings.append(Finding(
                    "NO_DATE", BLOCKING, unit.line,
                    f"{token} is cited but has no usable date (YYYY-MM-DD)"))
            elif date < cutoff:
                findings.append(Finding(
                    "STALE", WARNING, unit.line,
                    f"{token} is dated {date.isoformat()}, older than {max_age_months} months"))

    for token in sorted(set(sources) - cited):
        findings.append(Finding(
            "ORPHAN_SOURCE", WARNING, 0,
            f"{token} is declared but never cited"))
    return findings


def render(finding: Finding) -> str:
    where = f"L{finding.line}" if finding.line else "--"
    return f"{where:>6}  {finding.code:<14} {finding.message}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pre-flight gate for sourced claims in a brief.")
    sub = parser.add_subparsers(dest="command", required=True)
    cmd = sub.add_parser("check", help="check a markdown brief against its sources")
    cmd.add_argument("brief")
    cmd.add_argument("--sources", default=None, help="JSON file of declared sources")
    cmd.add_argument("--max-age-months", type=int, default=24, help="staleness threshold (default 24)")
    cmd.add_argument("--json", action="store_true", help="machine-readable output")
    cmd.add_argument("--quiet", action="store_true", help="print the summary only")
    args = parser.parse_args(argv)

    units = parse_units(args.brief)
    sources = load_sources(args.sources)
    findings = check(units, sources, args.max_age_months)

    blocking = [f for f in findings if f.severity == BLOCKING]
    warnings = [f for f in findings if f.severity == WARNING]

    if args.json:
        print(json.dumps({
            "brief": args.brief,
            "claims": len(units),
            "sources": len(sources),
            "blocking": len(blocking),
            "warnings": len(warnings),
            "findings": [f.__dict__ for f in findings],
            "result": "PASS" if not blocking else "FAIL",
        }, indent=2))
    elif not args.quiet:
        print(f"evidence-ledger  ·  {args.brief}")
        print(f"{len(units)} claims  ·  {len(sources)} sources declared\n")
        for finding in findings:
            print(render(finding))
        if findings:
            print()

    if not args.json:
        status = "PASS" if not blocking else "FAIL"
        print(f"{status}: {len(blocking)} blocking, {len(warnings)} warning"
              f"{'' if len(warnings) == 1 else 's'}")
    return 0 if not blocking else 1


if __name__ == "__main__":
    sys.exit(main())

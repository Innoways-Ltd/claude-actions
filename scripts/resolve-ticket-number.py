#!/usr/bin/env python3
"""Resolve a project-internal ticket number for an issue.

Two-level fallback (matches plan §15 locked decision):
  1. title  — apply ticket_number.title_regex to the issue title, take group 1
  2. github — fall back to the GitHub issue number

The order is configurable via TICKET_SOURCE_ORDER (space-separated env var
emitted by load-project-config.py), so a project that wants github-first can
swap them. Unknown source names are skipped with a warning rather than
fatal — projects may add custom sources later.

The result is sanitized to branch-safe characters (alphanumerics, '.', '_',
'-'); anything else is replaced with '_' so the value flows safely into
branch names and commit messages without further escaping.

Usage:
    resolve-ticket-number.py

Required env:
    ISSUE_TITLE          GitHub issue title (already resolved by workflow)
    ISSUE_NUMBER         GitHub issue number (numeric)
    TICKET_SOURCE_ORDER  space-separated, e.g. "title github"
    TICKET_TITLE_REGEX   Python regex with one capturing group

Output (stdout): a single line with the resolved ticket number.
Workflow consumer should pipe that line into $GITHUB_ENV as TICKET_NUM=...
"""
from __future__ import annotations

import os
import re
import sys


def _sanitize(s: str) -> str:
    """Keep only branch-safe characters; replace the rest with '_'."""
    return re.sub(r"[^A-Za-z0-9._-]", "_", s)


def resolve(title: str, github_num: str, source_order: list[str], regex: str) -> str:
    """Return the first successful resolution, or github_num as final fallback."""
    try:
        compiled = re.compile(regex)
    except re.error as exc:
        sys.stderr.write(f"ERROR: TICKET_TITLE_REGEX invalid: {exc}\n")
        sys.exit(3)

    for source in source_order:
        if source == "title":
            m = compiled.search(title)
            if m and m.lastindex and m.group(1):
                return _sanitize(m.group(1))
            sys.stderr.write(
                f"note: title regex did not match; falling through\n"
            )
        elif source == "github":
            if github_num:
                return _sanitize(github_num)
            sys.stderr.write("note: github source empty; falling through\n")
        else:
            sys.stderr.write(f"warning: unknown ticket source '{source}', skipping\n")

    # Last-resort fallback: github_num even if it wasn't in source_order.
    # Better than empty output, which would break branch templating.
    if github_num:
        sys.stderr.write(
            "warning: no configured source matched; using github_num as last-resort\n"
        )
        return _sanitize(github_num)

    sys.stderr.write("ERROR: could not resolve ticket number from any source\n")
    sys.exit(4)


def main() -> int:
    title = os.environ.get("ISSUE_TITLE", "")
    github_num = os.environ.get("ISSUE_NUMBER", "")
    source_order = os.environ.get("TICKET_SOURCE_ORDER", "title github").split()
    regex = os.environ.get("TICKET_TITLE_REGEX", r"^\[?(\d+)\]?")

    result = resolve(title, github_num, source_order, regex)
    print(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())

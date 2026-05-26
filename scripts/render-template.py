#!/usr/bin/env python3
"""Render a Python str.format template using selected env vars.

Tiny helper so the workflow doesn't have to embed multi-line Python inside a
bash block inside YAML (the indentation of the inline form trips up YAML
parsers, see prior workflow patch that broke the YAML).

Reads the template from the first command-line arg or, if absent, the
env var TEMPLATE. Looks up these placeholders from the environment:

    {ticket_num}   $TICKET_NUM
    {title}        $ISSUE_TITLE
    {github_num}   $ISSUE_NUMBER
    {repo}         $REPO_FULL
    {run_url}      $RUN_URL
    {sub}          $SUB
    {base}         $BASE_BRANCH

Missing placeholders fail with a clear message (exit 3) — matches the same
fail-fast behavior as resolve-branch-name.py.

The default template (when neither arg nor TEMPLATE is provided) is
"Fix #{ticket_num}: {title}". Keeping the default here, not in the calling
bash, avoids a real bug: bash's `${var:-default}` expansion splits the
default at the FIRST `}`, so a default like `Fix #{ticket_num}: {title}`
gets mangled before Python even sees it (the trailing `}` ends up doubled
and Python raises "Single '}' encountered in format string").

Usage:
    render-template.py "Fix #{ticket_num}: {title}"
    TEMPLATE="..." render-template.py
    render-template.py                    # uses default "Fix #{ticket_num}: {title}"
"""
from __future__ import annotations

import os
import sys


DEFAULT_TEMPLATE = "Fix #{ticket_num}: {title}"


def main() -> int:
    if len(sys.argv) >= 2:
        template = sys.argv[1]
    else:
        template = os.environ.get("TEMPLATE") or DEFAULT_TEMPLATE

    vars = {
        "ticket_num": os.environ.get("TICKET_NUM", ""),
        "title": os.environ.get("ISSUE_TITLE", ""),
        "github_num": os.environ.get("ISSUE_NUMBER", ""),
        "repo": os.environ.get("REPO_FULL", ""),
        "run_url": os.environ.get("RUN_URL", ""),
        "sub": os.environ.get("SUB", ""),
        "base": os.environ.get("BASE_BRANCH", ""),
    }
    try:
        print(template.format(**vars))
    except KeyError as exc:
        sys.stderr.write(
            f"ERROR: template references unknown placeholder {exc} "
            f"(known: {sorted(vars)})\n"
        )
        return 3
    except ValueError as exc:
        # Lone `{` or `}` in the template (not part of a placeholder, not
        # escaped as `{{` or `}}`). Surface the actual template so it's
        # debuggable instead of just "Single '}' encountered in format string".
        sys.stderr.write(
            f"ERROR: template malformed: {exc}\n"
            f"       template = {template!r}\n"
        )
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())

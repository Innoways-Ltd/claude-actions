#!/usr/bin/env python3
"""Render a feature-branch name from a template (merge_request mode only).

The template supports these placeholders (per plan §15):
    {base}            base branch name, e.g. 'dev_schemea'
    {ticket_num}      resolved by resolve-ticket-number.py
    {github_num}      raw GitHub issue number
    {title}           full issue title (sanitized)
    {title_clean}     title with leading ticket prefix removed
    {sub}             subproject name (for multi-sub repos)
    {timestamp}       Unix epoch seconds (collision suffix)

Branch names are sanitized to git-safe characters; runs of disallowed chars
collapse to a single '_'. We don't truncate — extremely long titles produce
extremely long branches, but git accepts them and `glab mr` displays them
fine. Callers worried about length can use a shorter pattern.

Collision handling (env: BRANCH_ON_COLLISION):
    append_timestamp  default — if the rendered name already exists on origin,
                      retry with `{name}-{timestamp}` so the run never aborts
                      on a name clash
    fail              exit non-zero if the rendered name already exists
                      (good for projects where branch names are PR-style and
                      must match a tracker exactly)

Usage:
    resolve-branch-name.py

Required env:
    BRANCH_PATTERN          template string
    BASE_BRANCH             e.g. dev_schemea
    TICKET_NUM              resolved by resolve-ticket-number.py
    ISSUE_NUMBER            raw GitHub issue number
    ISSUE_TITLE             raw GitHub issue title
    SUB                     subproject name (may be empty)
    BRANCH_ON_COLLISION     append_timestamp | fail

Optional env (for the collision check; skipped if blank):
    COLLISION_CHECK_PATH    path to a local git clone whose 'origin' should be
                            queried for the rendered branch name. If empty,
                            no collision check is performed (caller may do it
                            themselves). NOTE: do NOT name this GIT_DIR — that
                            is a reserved git env var that subprocess inherits.

Output (stdout): one line, the final branch name.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import time


def _sanitize_branch(s: str) -> str:
    """Replace disallowed chars with '_' and collapse runs.

    Git refnames forbid: ASCII control, space, ~, ^, :, ?, *, [, \\, .., @{, //,
    leading -, trailing /, .lock. We err on the side of strict: keep only
    [A-Za-z0-9._/-] (slashes intentionally allowed — they're how
    namespaced refs work), then collapse runs of '_' and strip leading/trailing
    separators.
    """
    cleaned = re.sub(r"[^A-Za-z0-9._/-]", "_", s)
    cleaned = re.sub(r"_+", "_", cleaned).strip("_-/")
    # Avoid '..' which git rejects
    cleaned = cleaned.replace("..", "_")
    return cleaned or "branch"


def _strip_ticket_prefix(title: str, ticket_num: str) -> str:
    """Remove a leading "[<ticket>] " or "<ticket> - " so {title_clean} is the descriptive part."""
    if not ticket_num:
        return title
    patterns = [
        rf"^\[{re.escape(ticket_num)}\]\s*",
        rf"^{re.escape(ticket_num)}\s*[-:]\s*",
        rf"^{re.escape(ticket_num)}\s+",
    ]
    for p in patterns:
        title = re.sub(p, "", title, count=1)
    return title


def _remote_branch_exists(workspace: str, branch: str) -> bool:
    """True if origin/<branch> exists on the remote; False on git error.

    A git failure shouldn't make the workflow fail — better to risk picking
    an existing branch name (which `git push` itself will reject) than to
    abort the entire run because a network blip prevented `ls-remote`.
    """
    try:
        out = subprocess.run(
            ["git", "ls-remote", "--heads", "origin", branch],
            cwd=workspace,
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
        return out.returncode == 0 and bool(out.stdout.strip())
    except (OSError, subprocess.SubprocessError) as exc:
        sys.stderr.write(f"warning: ls-remote failed ({exc}); skipping collision check\n")
        return False


def render(pattern: str, vars: dict[str, str]) -> str:
    """str.format with explicit error on missing variables.

    KeyError out of str.format is mostly unhelpful; we want a clear message
    listing the unknown placeholder so the workflow operator can fix the
    template quickly.
    """
    try:
        return pattern.format(**vars)
    except KeyError as exc:
        sys.stderr.write(
            f"ERROR: BRANCH_PATTERN references unknown placeholder {exc} "
            f"(known: {sorted(vars)})\n"
        )
        sys.exit(3)


def main() -> int:
    pattern = os.environ.get("BRANCH_PATTERN", "{base}_{ticket_num}")
    base = os.environ.get("BASE_BRANCH", "dev")
    ticket_num = os.environ.get("TICKET_NUM", "")
    github_num = os.environ.get("ISSUE_NUMBER", "")
    title = os.environ.get("ISSUE_TITLE", "")
    sub = os.environ.get("SUB", "")
    collision = os.environ.get("BRANCH_ON_COLLISION", "append_timestamp")
    workspace = os.environ.get("COLLISION_CHECK_PATH", "")

    title_clean = _strip_ticket_prefix(title, ticket_num)
    vars = {
        "base": base,
        "ticket_num": ticket_num,
        "github_num": github_num,
        "title": title,
        "title_clean": title_clean,
        "sub": sub,
        "timestamp": str(int(time.time())),
    }

    candidate = _sanitize_branch(render(pattern, vars))

    if workspace and _remote_branch_exists(workspace, candidate):
        if collision == "fail":
            sys.stderr.write(
                f"ERROR: branch '{candidate}' already exists on origin and on_collision=fail\n"
            )
            sys.exit(5)
        # append_timestamp: retry with -<timestamp> suffix
        retry = _sanitize_branch(f"{candidate}-{vars['timestamp']}")
        sys.stderr.write(
            f"note: branch '{candidate}' exists; appending timestamp -> '{retry}'\n"
        )
        candidate = retry

    print(candidate)
    return 0


if __name__ == "__main__":
    sys.exit(main())

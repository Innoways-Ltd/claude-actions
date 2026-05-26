"""Tests for scripts/render-template.py.

The script renders a Python str.format template using a fixed set of env
placeholders. Critical contract:

  - When neither arg nor TEMPLATE is provided, fall back to the default
    `Fix #{ticket_num}: {title}` (this is what fixes the historical bash
    brace-mangling bug — see the docstring in render-template.py).
  - Missing placeholders or malformed templates exit non-zero with a clear
    message; the workflow surfaces stderr so a future operator can debug.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "scripts" / "render-template.py"


def _run(env: dict[str, str], args: list[str] | None = None) -> subprocess.CompletedProcess[str]:
    full_env = {**os.environ, **env}
    # Drop keys the test asked to clear (set to "" + tracked separately would be
    # surprising — clearer to let tests pass None via the helper).
    return subprocess.run(
        [sys.executable, str(SCRIPT), *(args or [])],
        env=full_env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_default_template_when_no_input() -> None:
    """No arg + no TEMPLATE env → use DEFAULT_TEMPLATE = 'Fix #{ticket_num}: {title}'."""
    # Make sure TEMPLATE is not inherited from the parent env.
    env = {
        k: "" for k in ("TEMPLATE",)
    }
    env.update(
        {
            "TICKET_NUM": "42",
            "ISSUE_TITLE": "Cannot login",
        }
    )
    r = _run(env)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "Fix #42: Cannot login"


def test_empty_template_env_falls_back_to_default() -> None:
    """TEMPLATE='' (set but empty) → use default. This is what the bash fix relies on:
    the workflow now does `TEMPLATE="$MR_TITLE_TEMPLATE" python3 ...`, and when the
    caller didn't provide mr_title_template, the env var is empty (not unset)."""
    env = {
        "TEMPLATE": "",
        "TICKET_NUM": "7",
        "ISSUE_TITLE": "Bug",
    }
    r = _run(env)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "Fix #7: Bug"


def test_template_env_used_when_no_arg() -> None:
    env = {
        "TEMPLATE": "[{ticket_num}] {title}",
        "TICKET_NUM": "001",
        "ISSUE_TITLE": "Add column",
    }
    r = _run(env)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "[001] Add column"


def test_cli_arg_overrides_env() -> None:
    env = {
        "TEMPLATE": "wrong",
        "TICKET_NUM": "5",
        "ISSUE_TITLE": "x",
    }
    r = _run(env, args=["#{ticket_num}: {title}"])
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "#5: x"


def test_all_placeholders_resolve() -> None:
    env = {
        "TEMPLATE": "{repo}#{github_num} ({sub}/{base}) -> {ticket_num}: {title} | {run_url}",
        "TICKET_NUM": "100",
        "ISSUE_TITLE": "Title here",
        "ISSUE_NUMBER": "12",
        "REPO_FULL": "Innoways-Ltd/foo",
        "RUN_URL": "https://example.com/run/1",
        "SUB": "api",
        "BASE_BRANCH": "dev_schemea",
    }
    r = _run(env)
    assert r.returncode == 0, r.stderr
    assert (
        r.stdout.strip()
        == "Innoways-Ltd/foo#12 (api/dev_schemea) -> 100: Title here | https://example.com/run/1"
    )


def test_unknown_placeholder_fails() -> None:
    env = {
        "TEMPLATE": "Hello {nope}",
        "TICKET_NUM": "1",
    }
    r = _run(env)
    assert r.returncode == 3
    assert "unknown placeholder" in r.stderr
    assert "'nope'" in r.stderr


def test_malformed_template_lone_close_brace_fails_with_clear_message() -> None:
    """Regression test for the original bash bug: a template like
    'Fix #{ticket_num}: {title}: {title}}' has a lone '}' at the end which
    Python's str.format() rejects. The error message must mention the offending
    template so an operator can debug without re-running."""
    env = {
        "TEMPLATE": "Fix #{ticket_num}: {title}: {title}}",
        "TICKET_NUM": "42",
        "ISSUE_TITLE": "foo",
    }
    r = _run(env)
    assert r.returncode == 3
    assert "malformed" in r.stderr
    # Showing the actual template in stderr is critical for debugging — without
    # it the operator just sees "Single '}'" with no clue which value broke.
    assert "Fix #{ticket_num}" in r.stderr


def test_malformed_template_lone_open_brace_fails() -> None:
    """A lone '{' (not closed) is also a format-string error."""
    env = {
        "TEMPLATE": "Fix #{ticket_num: {title}",  # closing brace missing on ticket_num
        "TICKET_NUM": "1",
        "ISSUE_TITLE": "x",
    }
    r = _run(env)
    assert r.returncode == 3
    assert "malformed" in r.stderr


def test_escaped_braces_in_template_work() -> None:
    """Python's `{{` and `}}` are literal braces; a caller can use them if they
    really need a brace in the output (e.g. a JSON-like MR title)."""
    env = {
        "TEMPLATE": "{{{ticket_num}}}",  # literal '{', then placeholder, then literal '}'
        "TICKET_NUM": "42",
    }
    r = _run(env)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "{42}"

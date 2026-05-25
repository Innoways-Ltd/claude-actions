"""Tests for scripts/build-prompt.py.

The script reads /tmp/claude-job/issue.json (hardcoded path) and emits a
markdown prompt to stdout. Each test sets up a fake issue.json, writes the
required env vars, runs the script via subprocess, and asserts on stdout.

The hardcoded /tmp/claude-job/issue.json path is shared across the runner,
so tests back up + restore any existing fixture they overwrite. Same
pattern as casemanagement-issue/tests/test_build_bug_prompt.py.
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
from typing import Iterator

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "build-prompt.py"

# Shared baseline env. Per-test overrides go on top.
BASE_ENV = {
    "WORKSPACE_ROOT": "/tmp/fake-workspace",
    "SUBPROJECTS": "CaseManagement-NodeJs casemanagement-react",
    "SUBPROJECT_DESCRIPTIONS": (
        "- `CaseManagement-NodeJs/` — Koa backend\n"
        "- `casemanagement-react/`  — React frontend"
    ),
    "PROJECT_OVERVIEW": "Two siblings on dev.",
    "REPO_FULL": "Innoways-Ltd/casemanagement-issue",
    "ISSUE_NUMBER": "42",
    "TARGET": "casemanagement-react",
    "TARGET_BRANCH": "dev",
}


@pytest.fixture
def install_issue_json(tmp_path: pathlib.Path) -> Iterator[None]:
    """Write a synthetic issue.json to /tmp/claude-job, restore prior state on exit.

    Body intentionally contains a feature-style `### Acceptance criteria`
    block so feature-mode tests can assert it's extracted. Bug-mode tests
    just ignore it (the section never appears in bug output).
    """
    issue_path = pathlib.Path("/tmp/claude-job/issue.json")
    issue_path.parent.mkdir(parents=True, exist_ok=True)
    backup = issue_path.read_text() if issue_path.exists() else None
    issue_path.write_text(
        json.dumps(
            {
                "title": "TEST: matter close fails on portal",
                "body": (
                    "### Target Project\n\n"
                    "casemanagement-react\n\n"
                    "### Steps to reproduce\n\n1. Open a closed matter\n2. Click reopen\n\n"
                    "### Expected\n\nMatter reopens.\n\n"
                    "### Actual\n\nButton greys out, nothing happens.\n\n"
                    "### Acceptance criteria\n\n"
                    "- Closed matter can be reopened\n"
                    "- Reopening reflects in audit log\n\n"
                    "@claude please address this issue."
                ),
                "comments": [
                    {
                        "author": {"login": "tester"},
                        "createdAt": "2026-05-24T10:00:00Z",
                        "body": "Bumping — still broken.",
                    }
                ],
            }
        )
    )
    yield
    if backup is not None:
        issue_path.write_text(backup)
    else:
        issue_path.unlink(missing_ok=True)


@pytest.fixture
def fake_workspace(tmp_path: pathlib.Path) -> str:
    """Create a tmp workspace with a docs/ subdir for DOCS_PATH tests."""
    ws = tmp_path / "ws"
    docs = ws / "docs"
    docs.mkdir(parents=True)
    (docs / "README.md").write_text("# README\n\nHigh-level overview.\n")
    (docs / "00-architecture.md").write_text("# Architecture overview\n\nSystem context.\n")
    (docs / "01-module-a.md").write_text("# Module A\n\nDetails.\n")
    return str(ws)


def _run(mode: str, env_overrides: dict[str, str]) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, **BASE_ENV, **env_overrides}
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--mode", mode],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


# ────────────────────────────────────────────────────────────────────────────
# Bug mode
# ────────────────────────────────────────────────────────────────────────────

def test_bug_mode_basic_structure(install_issue_json: None) -> None:
    """Bug header, Target Project, sensitive-paths warning, and Summary table."""
    r = _run("bug", {})
    assert r.returncode == 0, r.stderr
    out = r.stdout
    assert "# Tester issue: TEST: matter close fails on portal" in out
    assert "Source: Innoways-Ltd/casemanagement-issue#42" in out
    assert "Target Project: casemanagement-react" in out
    assert "smallest correct change" in out
    assert "## Summary" in out
    assert "| 平台 / Platform | 文件路径 / File | 改动内容 / Change | 影响范围 / Impact |" in out
    # Sensitive-path list mentions key blocked paths verbatim.
    assert "secrets/**" in out
    assert "*/auth/**" in out


def test_bug_mode_with_docs(install_issue_json: None, fake_workspace: str) -> None:
    """docs/ index appears when DOCS_PATH is set."""
    r = _run(
        "bug",
        {
            "WORKSPACE_ROOT": fake_workspace,
            "DOCS_PATH": "docs",
            "DOCS_INLINE": "",
        },
    )
    assert r.returncode == 0, r.stderr
    out = r.stdout
    assert "## docs/ index" in out
    assert "- `docs/README.md`" in out
    assert "- `docs/00-architecture.md`" in out
    # No inlined content because DOCS_INLINE is empty.
    assert "### Inlined:" not in out


def test_bug_mode_without_docs(install_issue_json: None) -> None:
    """No docs/ section when DOCS_PATH is unset."""
    r = _run("bug", {})
    assert r.returncode == 0, r.stderr
    assert "## docs/ index" not in r.stdout
    # Instruction 1 falls back to "Read the relevant code first" when no docs.
    assert "Read the relevant code first" in r.stdout


def test_bug_mode_inlined_docs(install_issue_json: None, fake_workspace: str) -> None:
    """Inlined doc content appears in a code fence."""
    r = _run(
        "bug",
        {
            "WORKSPACE_ROOT": fake_workspace,
            "DOCS_PATH": "docs",
            "DOCS_INLINE": "00-architecture.md",
        },
    )
    assert r.returncode == 0, r.stderr
    out = r.stdout
    assert "### Inlined: `docs/00-architecture.md`" in out
    assert "#### `docs/00-architecture.md`" in out
    assert "# Architecture overview" in out
    # Use `````markdown` fence so nested triple-backticks don't break parsing.
    assert "````markdown" in out


# ────────────────────────────────────────────────────────────────────────────
# Feature mode
# ────────────────────────────────────────────────────────────────────────────

def test_feature_mode_acceptance_criteria_extracted(install_issue_json: None) -> None:
    """`### Acceptance criteria` from body is extracted into its own section."""
    r = _run("feature", {})
    assert r.returncode == 0, r.stderr
    out = r.stdout
    assert "# Feature request: TEST: matter close fails on portal" in out
    assert "## Acceptance criteria (must be satisfied)" in out
    assert "Closed matter can be reopened" in out
    assert "Reopening reflects in audit log" in out


def test_feature_mode_no_criteria_in_body(install_issue_json: None) -> None:
    """When the body has no `### Acceptance criteria`, the fallback notice appears."""
    # Overwrite issue.json (the fixture restores the original on teardown).
    issue_path = pathlib.Path("/tmp/claude-job/issue.json")
    issue_path.write_text(
        json.dumps(
            {
                "title": "Feature: add X",
                "body": "### What\n\nFoo.\n\n### Why\n\nBar.",
                "comments": [],
            }
        )
    )
    r = _run("feature", {})
    assert r.returncode == 0, r.stderr
    out = r.stdout
    assert "No `### Acceptance criteria` block found" in out


def test_feature_mode_allows_new_files_instruction(install_issue_json: None) -> None:
    """Feature instructions explicitly permit small abstractions, unlike bug mode."""
    r = _run("feature", {})
    assert r.returncode == 0, r.stderr
    assert "allowed to introduce new files" in r.stdout
    # The "Acceptance criteria covered" subsection sentinel for the Summary table.
    assert "Acceptance criteria covered" in r.stdout


# ────────────────────────────────────────────────────────────────────────────
# Wiki mode
# ────────────────────────────────────────────────────────────────────────────

def test_wiki_mode_basic_structure(install_issue_json: None) -> None:
    """Wiki header + read-only workspace framing + Answer template."""
    r = _run("wiki", {})
    assert r.returncode == 0, r.stderr
    out = r.stdout
    assert "# Wiki question: TEST: matter close fails on portal" in out
    assert "## Workspace (read-only references)" in out
    assert "## Answer" in out
    assert "## Question" in out
    # No Summary table (wiki mode uses Answer instead).
    assert "## Summary" not in out
    # Target Project is suppressed in wiki mode.
    assert "Target Project:" not in out


def test_wiki_mode_gitnexus_section_present(install_issue_json: None) -> None:
    """GitNexus MCP section appears when GITNEXUS_REPOS is non-empty (default)."""
    r = _run("wiki", {})
    assert r.returncode == 0, r.stderr
    out = r.stdout
    assert "## Code intelligence (GitNexus MCP — preferred)" in out
    assert "mcp__gitnexus__query" in out
    # SUBPROJECTS values become the listed repos by default.
    assert '`repo: "CaseManagement-NodeJs"`' in out
    assert '`repo: "casemanagement-react"`' in out
    assert "Fallback policy" in out


def test_wiki_mode_no_gitnexus_when_disabled(install_issue_json: None) -> None:
    """A single space in GITNEXUS_REPOS disables the entire section."""
    r = _run("wiki", {"GITNEXUS_REPOS": " "})
    assert r.returncode == 0, r.stderr
    out = r.stdout
    assert "## Code intelligence" not in out
    assert "mcp__gitnexus__query" not in out


def test_wiki_mode_jargon_ban_in_instructions(install_issue_json: None) -> None:
    """Instructions §3 includes the banned-without-explanation jargon list."""
    r = _run("wiki", {})
    assert r.returncode == 0, r.stderr
    out = r.stdout
    assert "Banned without explanation" in out
    assert '"controller"' in out
    assert '"middleware"' in out
    # Audience callout explicit so Claude doesn't drift into engineer-speak.
    assert "tester / business user / project" in out


# ────────────────────────────────────────────────────────────────────────────
# Failure modes
# ────────────────────────────────────────────────────────────────────────────

def test_missing_required_env_fails(install_issue_json: None) -> None:
    """Bug mode with WORKSPACE_ROOT empty exits non-zero with a clear message."""
    r = _run("bug", {"WORKSPACE_ROOT": ""})
    assert r.returncode == 2
    assert "missing required env var WORKSPACE_ROOT" in r.stderr


def test_invalid_mode_arg_fails(install_issue_json: None) -> None:
    """argparse rejects an unknown --mode value."""
    env = {**os.environ, **BASE_ENV}
    r = subprocess.run(
        [sys.executable, str(SCRIPT), "--mode", "yolo"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode != 0
    # argparse default error message includes the offending value.
    assert "yolo" in r.stderr or "invalid choice" in r.stderr


def test_missing_issue_json_fails() -> None:
    """If /tmp/claude-job/issue.json is absent, the script exits 1."""
    issue_path = pathlib.Path("/tmp/claude-job/issue.json")
    backup = issue_path.read_text() if issue_path.exists() else None
    issue_path.unlink(missing_ok=True)
    try:
        env = {**os.environ, **BASE_ENV}
        r = subprocess.run(
            [sys.executable, str(SCRIPT), "--mode", "bug"],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert r.returncode == 1
        assert "Missing /tmp/claude-job/issue.json" in r.stderr
    finally:
        if backup is not None:
            issue_path.parent.mkdir(parents=True, exist_ok=True)
            issue_path.write_text(backup)

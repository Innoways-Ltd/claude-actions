"""Tests for scripts/resolve-branch-name.py.

Covers:
  - membership pattern: {base}_{ticket_num} → dev_schemea_001
  - template with {sub}
  - sanitization of unsafe characters
  - title_clean strips bracketed/dashed/space-only ticket prefix
  - unknown placeholder → fatal exit
  - collision check via a local fake-remote git repo (append_timestamp vs fail)
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "scripts" / "resolve-branch-name.py"


def run(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    full_env = {**os.environ, **env}
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True,
        text=True,
        env=full_env,
        check=False,
    )


def test_membership_pattern() -> None:
    result = run(
        {
            "BRANCH_PATTERN": "{base}_{ticket_num}",
            "BASE_BRANCH": "dev_schemea",
            "TICKET_NUM": "001",
            "ISSUE_NUMBER": "7",
            "ISSUE_TITLE": "[001] foo",
            "SUB": "",
            "BRANCH_ON_COLLISION": "append_timestamp",
            "COLLISION_CHECK_PATH": "",  # skip collision check
        }
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "dev_schemea_001"


def test_pattern_with_sub() -> None:
    result = run(
        {
            "BRANCH_PATTERN": "claude/issue-{ticket_num}-{sub}",
            "BASE_BRANCH": "dev",
            "TICKET_NUM": "42",
            "ISSUE_NUMBER": "42",
            "ISSUE_TITLE": "Bug",
            "SUB": "membership-api",
            "BRANCH_ON_COLLISION": "append_timestamp",
            "COLLISION_CHECK_PATH": "",
        }
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "claude/issue-42-membership-api"


def test_sanitization_of_unsafe_chars() -> None:
    # A title-derived placeholder with spaces should not produce a branch
    # name with spaces. The whole sequence collapses to underscores.
    result = run(
        {
            "BRANCH_PATTERN": "{base}/{title}",
            "BASE_BRANCH": "dev",
            "TICKET_NUM": "1",
            "ISSUE_NUMBER": "1",
            "ISSUE_TITLE": "Some Bug: with !weird? chars",
            "SUB": "",
            "BRANCH_ON_COLLISION": "append_timestamp",
            "COLLISION_CHECK_PATH": "",
        }
    )
    assert result.returncode == 0, result.stderr
    name = result.stdout.strip()
    # No spaces, no ! ? :
    assert " " not in name
    assert "!" not in name
    assert "?" not in name
    assert ":" not in name
    assert name.startswith("dev/")


def test_title_clean_strips_bracketed_prefix() -> None:
    result = run(
        {
            "BRANCH_PATTERN": "{title_clean}",
            "BASE_BRANCH": "dev",
            "TICKET_NUM": "001",
            "ISSUE_NUMBER": "5",
            "ISSUE_TITLE": "[001] Cannot close case",
            "SUB": "",
            "BRANCH_ON_COLLISION": "append_timestamp",
            "COLLISION_CHECK_PATH": "",
        }
    )
    assert result.returncode == 0, result.stderr
    # 'Cannot close case' minus the "[001] " prefix, sanitized
    assert result.stdout.strip() == "Cannot_close_case"


def test_title_clean_strips_dashed_prefix() -> None:
    result = run(
        {
            "BRANCH_PATTERN": "{title_clean}",
            "BASE_BRANCH": "dev",
            "TICKET_NUM": "42",
            "ISSUE_NUMBER": "42",
            "ISSUE_TITLE": "42 - Data loading issue",
            "SUB": "",
            "BRANCH_ON_COLLISION": "append_timestamp",
            "COLLISION_CHECK_PATH": "",
        }
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "Data_loading_issue"


def test_unknown_placeholder_fails() -> None:
    result = run(
        {
            "BRANCH_PATTERN": "{base}_{not_a_real_var}",
            "BASE_BRANCH": "dev",
            "TICKET_NUM": "1",
            "ISSUE_NUMBER": "1",
            "ISSUE_TITLE": "Bug",
            "SUB": "",
            "BRANCH_ON_COLLISION": "append_timestamp",
            "COLLISION_CHECK_PATH": "",
        }
    )
    assert result.returncode == 3
    assert "unknown placeholder" in result.stderr


def _make_fake_remote_with_branch(tmp_path: Path, branch: str) -> Path:
    """Create a bare 'remote' + a local clone where `ls-remote heads` returns branch."""
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", "-q", str(remote)], check=True)

    seed = tmp_path / "seed"
    subprocess.run(["git", "init", "-q", str(seed)], check=True)
    subprocess.run(["git", "-C", str(seed), "config", "user.email", "t@example.com"], check=True)
    subprocess.run(["git", "-C", str(seed), "config", "user.name", "T"], check=True)
    (seed / "f.txt").write_text("seed")
    subprocess.run(["git", "-C", str(seed), "add", "f.txt"], check=True)
    subprocess.run(["git", "-C", str(seed), "commit", "-q", "-m", "init"], check=True)
    subprocess.run(["git", "-C", str(seed), "branch", "-m", branch], check=True)
    subprocess.run(["git", "-C", str(seed), "remote", "add", "origin", str(remote)], check=True)
    subprocess.run(["git", "-C", str(seed), "push", "-q", "-u", "origin", branch], check=True)

    workspace = tmp_path / "workspace"
    subprocess.run(["git", "clone", "-q", str(remote), str(workspace)], check=True)
    return workspace


def test_collision_append_timestamp(tmp_path: Path) -> None:
    workspace = _make_fake_remote_with_branch(tmp_path, "dev_schemea_001")
    result = run(
        {
            "BRANCH_PATTERN": "{base}_{ticket_num}",
            "BASE_BRANCH": "dev_schemea",
            "TICKET_NUM": "001",
            "ISSUE_NUMBER": "5",
            "ISSUE_TITLE": "[001] foo",
            "SUB": "",
            "BRANCH_ON_COLLISION": "append_timestamp",
            "COLLISION_CHECK_PATH": str(workspace),
        }
    )
    assert result.returncode == 0, result.stderr
    name = result.stdout.strip()
    assert name.startswith("dev_schemea_001-")
    assert "appending timestamp" in result.stderr


def test_collision_fail(tmp_path: Path) -> None:
    workspace = _make_fake_remote_with_branch(tmp_path, "dev_schemea_001")
    result = run(
        {
            "BRANCH_PATTERN": "{base}_{ticket_num}",
            "BASE_BRANCH": "dev_schemea",
            "TICKET_NUM": "001",
            "ISSUE_NUMBER": "5",
            "ISSUE_TITLE": "[001] foo",
            "SUB": "",
            "BRANCH_ON_COLLISION": "fail",
            "COLLISION_CHECK_PATH": str(workspace),
        }
    )
    assert result.returncode == 5
    assert "already exists" in result.stderr


def test_collision_check_skipped_when_no_git_dir() -> None:
    # When GIT_DIR is empty, no ls-remote is attempted — the name is returned
    # as-is. This is the explicit escape hatch for workflow steps that want
    # to do their own collision handling.
    result = run(
        {
            "BRANCH_PATTERN": "{base}_{ticket_num}",
            "BASE_BRANCH": "dev_schemea",
            "TICKET_NUM": "001",
            "ISSUE_NUMBER": "5",
            "ISSUE_TITLE": "[001] foo",
            "SUB": "",
            "BRANCH_ON_COLLISION": "fail",
            "COLLISION_CHECK_PATH": "",
        }
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "dev_schemea_001"

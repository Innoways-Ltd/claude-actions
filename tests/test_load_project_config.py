"""Tests for scripts/load-project-config.py.

Verifies:
  - missing config file → embedded defaults
  - valid config merges into defaults
  - malformed YAML / unknown enum / bad regex → non-zero exit
  - shell-safe quoting of values
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "scripts" / "load-project-config.py"


def run(path: str, *args: str) -> subprocess.CompletedProcess[str]:
    """Invoke the script and capture stdout/stderr/returncode."""
    return subprocess.run(
        [sys.executable, str(SCRIPT), path, *args],
        capture_output=True,
        text=True,
        check=False,
    )


def parse_env(stdout: str) -> dict[str, str]:
    """Parse KEY=VALUE lines (handles shlex.quoted values) into a dict."""
    import shlex

    out: dict[str, str] = {}
    for raw in stdout.splitlines():
        if "=" not in raw:
            continue
        k, _, v = raw.partition("=")
        tokens = shlex.split(v) if v else [""]
        out[k] = tokens[0] if tokens else ""
    return out


def test_missing_file_uses_defaults(tmp_path: Path) -> None:
    result = run(str(tmp_path / "does-not-exist.yml"))
    assert result.returncode == 0, result.stderr
    env = parse_env(result.stdout)
    assert env["TERMINAL_ACTION"] == "direct_push"
    assert env["ON_CONFLICT"] == "fail"
    assert env["BASE_BRANCH"] == "dev"
    assert env["SUCCESS_LABEL"] == "pushed"
    assert env["BRANCH_PATTERN"] == "{base}_{ticket_num}"


def test_default_base_branch_override(tmp_path: Path) -> None:
    result = run(
        str(tmp_path / "missing.yml"),
        "--default-base-branch",
        "dev_schemea",
    )
    assert result.returncode == 0, result.stderr
    env = parse_env(result.stdout)
    assert env["BASE_BRANCH"] == "dev_schemea"


def test_casemanagement_config(tmp_path: Path) -> None:
    cfg = tmp_path / "project-config.yml"
    cfg.write_text(
        """
git:
  base_branch: dev
  terminal:
    action: direct_push
    on_conflict: fail
ticket_number:
  title_regex: '^\\[?(\\d+)\\]?'
notification:
  success_label: pushed
"""
    )
    result = run(str(cfg))
    assert result.returncode == 0, result.stderr
    env = parse_env(result.stdout)
    assert env["TERMINAL_ACTION"] == "direct_push"
    assert env["ON_CONFLICT"] == "fail"
    assert env["BASE_BRANCH"] == "dev"


def test_membership_config(tmp_path: Path) -> None:
    cfg = tmp_path / "project-config.yml"
    cfg.write_text(
        """
git:
  base_branch: dev_schemea
  terminal:
    action: merge_request
    branch:
      pattern: '{base}_{ticket_num}'
      on_collision: append_timestamp
    mr:
      title_template: 'Fix #{ticket_num}: {title}'
      remove_source_branch: true
notification:
  success_label: mr-opened
"""
    )
    result = run(str(cfg))
    assert result.returncode == 0, result.stderr
    env = parse_env(result.stdout)
    assert env["TERMINAL_ACTION"] == "merge_request"
    assert env["BASE_BRANCH"] == "dev_schemea"
    assert env["BRANCH_PATTERN"] == "{base}_{ticket_num}"
    assert env["MR_TITLE_TEMPLATE"] == "Fix #{ticket_num}: {title}"
    assert env["MR_REMOVE_SOURCE_BRANCH"] == "true"
    assert env["SUCCESS_LABEL"] == "mr-opened"


def test_malformed_yaml_fails(tmp_path: Path) -> None:
    cfg = tmp_path / "broken.yml"
    cfg.write_text("git:\n  base_branch: dev\n   bad-indent:\n")
    result = run(str(cfg))
    assert result.returncode != 0
    assert "failed to parse YAML" in result.stderr


def test_invalid_terminal_action_fails(tmp_path: Path) -> None:
    cfg = tmp_path / "bad.yml"
    cfg.write_text("git:\n  terminal:\n    action: yolo\n")
    result = run(str(cfg))
    assert result.returncode == 3
    assert "git.terminal.action='yolo'" in result.stderr


def test_invalid_on_conflict_fails(tmp_path: Path) -> None:
    cfg = tmp_path / "bad.yml"
    cfg.write_text("git:\n  terminal:\n    action: direct_push\n    on_conflict: surrender\n")
    result = run(str(cfg))
    assert result.returncode == 3
    assert "on_conflict='surrender'" in result.stderr


def test_invalid_regex_fails(tmp_path: Path) -> None:
    cfg = tmp_path / "bad.yml"
    cfg.write_text("ticket_number:\n  title_regex: '['\n")
    result = run(str(cfg))
    assert result.returncode == 3
    assert "title_regex is not a valid regex" in result.stderr


def test_top_level_not_mapping_fails(tmp_path: Path) -> None:
    cfg = tmp_path / "bad.yml"
    cfg.write_text("- just\n- a\n- list\n")
    result = run(str(cfg))
    assert result.returncode == 3
    assert "must be a mapping" in result.stderr


def test_commit_body_template_roundtrip(tmp_path: Path) -> None:
    cfg = tmp_path / "project-config.yml"
    cfg.write_text(
        """
commit:
  body_template: |
    Line 1
    Line 2 with #{ticket_num}
    Line 3
"""
    )
    result = run(str(cfg))
    assert result.returncode == 0, result.stderr
    env = parse_env(result.stdout)
    decoded = json.loads(env["COMMIT_BODY_TEMPLATE_JSON"])
    assert "Line 1" in decoded
    assert "Line 2 with #{ticket_num}" in decoded
    assert "Line 3" in decoded

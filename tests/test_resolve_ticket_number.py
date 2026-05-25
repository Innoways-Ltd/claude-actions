"""Tests for scripts/resolve-ticket-number.py.

Covers the title-formats table in plan §15 and edge cases:
  - bracketed numbers [001]
  - bare number prefix "001 - ..."
  - bracketed with text after "[42] foo"
  - no match → GitHub fallback
  - non-anchored regex via env override
  - unknown source name (skipped, not fatal)
  - sanitization of unsafe chars
  - empty GitHub number when title also fails → fatal exit
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "scripts" / "resolve-ticket-number.py"


def run(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    full_env = {**os.environ, **env}
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True,
        text=True,
        env=full_env,
        check=False,
    )


def test_bracketed_number_title() -> None:
    result = run(
        {
            "ISSUE_TITLE": "[001] Cannot close case",
            "ISSUE_NUMBER": "42",
            "TICKET_SOURCE_ORDER": "title github",
            "TICKET_TITLE_REGEX": r"^\[?(\d+)\]?",
        }
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "001"


def test_bare_number_prefix() -> None:
    result = run(
        {
            "ISSUE_TITLE": "001 - Data loading failed",
            "ISSUE_NUMBER": "7",
            "TICKET_SOURCE_ORDER": "title github",
            "TICKET_TITLE_REGEX": r"^\[?(\d+)\]?",
        }
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "001"


def test_two_digit_bracketed() -> None:
    result = run(
        {
            "ISSUE_TITLE": "[42] Bug in login flow",
            "ISSUE_NUMBER": "99",
            "TICKET_SOURCE_ORDER": "title github",
            "TICKET_TITLE_REGEX": r"^\[?(\d+)\]?",
        }
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "42"


def test_no_title_match_falls_back_to_github() -> None:
    result = run(
        {
            "ISSUE_TITLE": "修复登录问题",
            "ISSUE_NUMBER": "7",
            "TICKET_SOURCE_ORDER": "title github",
            "TICKET_TITLE_REGEX": r"^\[?(\d+)\]?",
        }
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "7"


def test_number_in_middle_does_not_match_default() -> None:
    # Default regex is anchored at start, so middle numbers are ignored —
    # this is intentional per plan §15 ("avoid误抓正文/title 中间数字").
    result = run(
        {
            "ISSUE_TITLE": "Bug 123 in module",
            "ISSUE_NUMBER": "8",
            "TICKET_SOURCE_ORDER": "title github",
            "TICKET_TITLE_REGEX": r"^\[?(\d+)\]?",
        }
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "8"  # GitHub fallback


def test_relaxed_regex_via_env() -> None:
    # A caller that explicitly wants to match anywhere in the title can pass
    # their own pattern; this is the escape hatch advertised in plan §15.
    result = run(
        {
            "ISSUE_TITLE": "Bug 123 in module",
            "ISSUE_NUMBER": "8",
            "TICKET_SOURCE_ORDER": "title github",
            "TICKET_TITLE_REGEX": r"\b(\d+)\b",
        }
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "123"


def test_github_first_source_order() -> None:
    # A project that wants GH-first can flip the order; title becomes the
    # secondary source even if it would have matched.
    result = run(
        {
            "ISSUE_TITLE": "[999] would have matched",
            "ISSUE_NUMBER": "5",
            "TICKET_SOURCE_ORDER": "github title",
            "TICKET_TITLE_REGEX": r"^\[?(\d+)\]?",
        }
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "5"


def test_unknown_source_is_skipped() -> None:
    result = run(
        {
            "ISSUE_TITLE": "[001] foo",
            "ISSUE_NUMBER": "5",
            "TICKET_SOURCE_ORDER": "linear title github",  # 'linear' unknown
            "TICKET_TITLE_REGEX": r"^\[?(\d+)\]?",
        }
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "001"
    assert "unknown ticket source 'linear'" in result.stderr


def test_sanitization_strips_unsafe_chars() -> None:
    # A regex that captures something containing a slash should get sanitized,
    # otherwise downstream `git checkout -b` would interpret the slash as a
    # path separator.
    result = run(
        {
            "ISSUE_TITLE": "[001/v2] foo",
            "ISSUE_NUMBER": "5",
            "TICKET_SOURCE_ORDER": "title github",
            "TICKET_TITLE_REGEX": r"^\[(\S+)\]",
        }
    )
    assert result.returncode == 0, result.stderr
    # Slash → underscore. The leading "001" digits are preserved.
    assert result.stdout.strip() == "001_v2"


def test_no_match_and_no_github_fails() -> None:
    result = run(
        {
            "ISSUE_TITLE": "no number anywhere",
            "ISSUE_NUMBER": "",
            "TICKET_SOURCE_ORDER": "title github",
            "TICKET_TITLE_REGEX": r"^\[?(\d+)\]?",
        }
    )
    assert result.returncode == 4
    assert "could not resolve ticket number" in result.stderr


def test_invalid_regex_fails() -> None:
    result = run(
        {
            "ISSUE_TITLE": "foo",
            "ISSUE_NUMBER": "5",
            "TICKET_SOURCE_ORDER": "title github",
            "TICKET_TITLE_REGEX": "[",
        }
    )
    assert result.returncode == 3
    assert "TICKET_TITLE_REGEX invalid" in result.stderr


def test_chinese_bracket_title_no_match() -> None:
    # Full-width Chinese brackets 【】 are NOT matched by the ASCII default,
    # documenting plan §15's "国际化下中文括号会踩坑" warning.
    result = run(
        {
            "ISSUE_TITLE": "【001】无法关闭",
            "ISSUE_NUMBER": "9",
            "TICKET_SOURCE_ORDER": "title github",
            "TICKET_TITLE_REGEX": r"^\[?(\d+)\]?",
        }
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "9"  # GitHub fallback kicks in

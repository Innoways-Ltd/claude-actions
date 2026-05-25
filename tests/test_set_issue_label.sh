#!/bin/bash
# Tests for scripts/set-issue-label.sh.
#
# Strategy: validate the argument-parsing and validation logic only — the
# script's real work is `gh issue edit` calls, which we can't easily intercept
# without a fake gh binary. We exercise the input-handling surface and
# confirm sensible exit codes.

set -u

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LABEL="$SCRIPT_DIR/scripts/set-issue-label.sh"

TESTS_PASSED=0
TESTS_FAILED=0
FAIL_REASONS=()

# Stub gh so we don't try to hit GitHub; success = our script reached the
# `gh issue edit` lines, which means arg validation passed.
TMP=$(mktemp -d)
cat > "$TMP/gh" <<'EOF'
#!/bin/bash
# Stub: succeed on label remove/add, log to FIFO if requested.
if [ -n "${GH_LOG:-}" ]; then
  echo "$@" >> "$GH_LOG"
fi
exit 0
EOF
chmod +x "$TMP/gh"
export PATH="$TMP:$PATH"
export GH_TOKEN=fake REPO_FULL=owner/repo ISSUE_NUMBER=1

assert_exit() {
  local actual="$1" expected="$2" label="$3"
  if [ "$actual" = "$expected" ]; then
    echo "  PASS  $label"
    TESTS_PASSED=$((TESTS_PASSED + 1))
  else
    echo "  FAIL  $label (expected exit $expected, got $actual)"
    TESTS_FAILED=$((TESTS_FAILED + 1))
    FAIL_REASONS+=("$label")
  fi
}

# Test 1: legacy positional form, valid state
"$LABEL" pushed >/dev/null 2>&1
assert_exit "$?" 0 "test1: legacy form 'pushed'"

# Test 2: legacy positional form, invalid state
"$LABEL" mr_opened >/dev/null 2>&1
assert_exit "$?" 2 "test2: legacy form with typo'd state → exit 2"

# Test 3: legacy form with new builtin (mr-opened should now be valid)
"$LABEL" mr-opened >/dev/null 2>&1
assert_exit "$?" 0 "test3: legacy form 'mr-opened' (new builtin)"

# Test 4: legacy form with new builtin (conflict)
"$LABEL" conflict >/dev/null 2>&1
assert_exit "$?" 0 "test4: legacy form 'conflict' (new builtin)"

# Test 5: --label form
"$LABEL" --label pushed >/dev/null 2>&1
assert_exit "$?" 0 "test5: --label form 'pushed'"

# Test 6: --label form with a custom label not in builtin (caller responsibility)
"$LABEL" --label custom-label >/dev/null 2>&1
assert_exit "$?" 0 "test6: --label form accepts custom labels"

# Test 7: --label form with --label-set override
"$LABEL" --label foo --label-set "foo bar baz" >/dev/null 2>&1
assert_exit "$?" 0 "test7: --label form with --label-set"

# Test 8: --label with empty value
"$LABEL" --label "" >/dev/null 2>&1
assert_exit "$?" 2 "test8: --label with empty value → exit 2"

# Test 9: no args
"$LABEL" >/dev/null 2>&1
assert_exit "$?" 2 "test9: no args → exit 2"

# Test 10: verify --label-set actually drives the cleanup list (gh log)
export GH_LOG="$TMP/gh-calls.log"
rm -f "$GH_LOG"
"$LABEL" --label active --label-set "active inactive paused" >/dev/null 2>&1
# Should remove inactive and paused, add active. That's 3 gh edits.
LINES=$(wc -l < "$GH_LOG")
if [ "$LINES" = "3" ]; then
  echo "  PASS  test10: --label-set drove 3 gh calls (remove 2 others + add 1)"
  TESTS_PASSED=$((TESTS_PASSED + 1))
else
  echo "  FAIL  test10: expected 3 gh calls, got $LINES"
  cat "$GH_LOG"
  TESTS_FAILED=$((TESTS_FAILED + 1))
  FAIL_REASONS+=("test10")
fi

unset GH_LOG
rm -rf "$TMP"

echo
echo "============================================"
echo "  Passed: $TESTS_PASSED"
echo "  Failed: $TESTS_FAILED"
echo "============================================"

if [ "$TESTS_FAILED" -gt 0 ]; then
  echo "Failures:"
  for r in "${FAIL_REASONS[@]}"; do
    echo "  - $r"
  done
  exit 1
fi
exit 0

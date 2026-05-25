#!/bin/bash
# Tests for scripts/post-result.sh.
#
# Strategy: each test creates a fixture /tmp/claude-job/output.log if the
# subcommand needs one, invokes the script with stdin redirection captured,
# and asserts that key markers appear (or don't appear) in the output.
#
# Subcommands covered:
#   issue_pushed_multi   (existing direct_push success)
#   issue_push_failed    (existing direct_push partial failure)
#   issue_conflict       (NEW — direct_push remote-drift abort)
#   issue_mr_multi       (NEW — merge_request success)
#   mr_body              (NEW — GitLab MR description body)
#   issue_no_chg         (existing)
#   issue_blocked        (existing)
#   wiki_answer          (existing — verifies regression-free)

set -u

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
POST="$SCRIPT_DIR/scripts/post-result.sh"
JOB_DIR="/tmp/claude-job-test"
LOG="$JOB_DIR/output.log"

TESTS_PASSED=0
TESTS_FAILED=0
FAIL_REASONS=()

setup() {
  rm -rf "$JOB_DIR"
  mkdir -p "$JOB_DIR"
}

# post-result.sh hardcodes /tmp/claude-job/output.log, so we have to stage
# there too. The test cleans this up at the end.
stage_log() {
  mkdir -p /tmp/claude-job
  cp "$1" /tmp/claude-job/output.log
}
unstage_log() {
  rm -f /tmp/claude-job/output.log
}

assert_contains() {
  local haystack="$1" needle="$2" label="$3"
  if echo "$haystack" | grep -qF "$needle"; then
    echo "  PASS  $label"
    TESTS_PASSED=$((TESTS_PASSED + 1))
  else
    echo "  FAIL  $label"
    echo "    expected to find: $needle"
    echo "    got: $(echo "$haystack" | head -5)..."
    TESTS_FAILED=$((TESTS_FAILED + 1))
    FAIL_REASONS+=("$label: missing '$needle'")
  fi
}

assert_not_contains() {
  local haystack="$1" needle="$2" label="$3"
  if echo "$haystack" | grep -qF "$needle"; then
    echo "  FAIL  $label (unexpectedly contained: $needle)"
    TESTS_FAILED=$((TESTS_FAILED + 1))
    FAIL_REASONS+=("$label: should not contain '$needle'")
  else
    echo "  PASS  $label"
    TESTS_PASSED=$((TESTS_PASSED + 1))
  fi
}

# ────────────────────────────────────────────────────────────
# issue_pushed_multi (existing)
# ────────────────────────────────────────────────────────────
setup
cat > "$LOG" <<'EOF'
some chatter

## Summary

| 平台 | 文件 | 改动 | 影响 |
|---|---|---|---|
| api | service/x.js | fix close | close button |
EOF
stage_log "$LOG"
echo "api|abc1234" > "$JOB_DIR/pushed.txt"
echo "web|def5678" >> "$JOB_DIR/pushed.txt"

OUT=$(bash "$POST" issue_pushed_multi "$JOB_DIR/pushed.txt" dev)
assert_contains "$OUT" "pushed 2 commits" "pushed_multi: count plural"
assert_contains "$OUT" "\`dev\`" "pushed_multi: target branch"
assert_contains "$OUT" "\`abc1234\`" "pushed_multi: api sha"
assert_contains "$OUT" "\`def5678\`" "pushed_multi: web sha"
assert_contains "$OUT" "## Summary" "pushed_multi: summary section"

OUT_NOTICE=$(POST_MERGE_NOTICE="Will deploy in ~20m" bash "$POST" issue_pushed_multi "$JOB_DIR/pushed.txt" dev)
assert_contains "$OUT_NOTICE" "Will deploy in ~20m" "pushed_multi: POST_MERGE_NOTICE honored"
unstage_log

# Singular case
setup
stage_log "$LOG" 2>/dev/null
mkdir -p /tmp/claude-job
echo "## Summary" > /tmp/claude-job/output.log
echo "api|abc1234" > "$JOB_DIR/pushed-single.txt"
OUT=$(bash "$POST" issue_pushed_multi "$JOB_DIR/pushed-single.txt" dev)
assert_contains "$OUT" "pushed 1 commit" "pushed_multi: count singular"
unstage_log

# ────────────────────────────────────────────────────────────
# issue_push_failed (existing)
# ────────────────────────────────────────────────────────────
setup
echo "api|abc1234" > "$JOB_DIR/pushed.txt"
OUT=$(bash "$POST" issue_push_failed \
  "https://example.com/run/1" \
  "web portal" \
  "$JOB_DIR/pushed.txt" \
  dev)
assert_contains "$OUT" "push to \`dev\` failed" "push_failed: header"
assert_contains "$OUT" "**web portal**" "push_failed: failed list"
assert_contains "$OUT" "\`abc1234\`" "push_failed: already pushed list"
assert_contains "$OUT" "Run log" "push_failed: run link"

# ────────────────────────────────────────────────────────────
# issue_conflict (NEW)
# ────────────────────────────────────────────────────────────
setup
OUT=$(bash "$POST" issue_conflict \
  "https://example.com/run/2" \
  "dev_schemea" \
  "api portal")
assert_contains "$OUT" "Push aborted" "conflict: aborted header"
assert_contains "$OUT" "\`dev_schemea\` advanced" "conflict: target branch named"
assert_contains "$OUT" "**api portal**" "conflict: affected subs listed"
assert_contains "$OUT" "Reply with \`@claude\` to retry" "conflict: retry guidance"
assert_contains "$OUT" "We refuse to rebase" "conflict: explains why no auto-rebase"
assert_contains "$OUT" "Run log" "conflict: run link"

# ────────────────────────────────────────────────────────────
# issue_mr_multi (NEW)
# ────────────────────────────────────────────────────────────
setup
cat > /tmp/claude-job/output.log <<'EOF'
## Summary

| 平台 | 文件 | 改动 | 影响 |
|---|---|---|---|
| api | x.js | fix | y |
EOF
cat > "$JOB_DIR/mrs.txt" <<EOF
api|https://gitlab.example.com/api/-/merge_requests/42
web|https://gitlab.example.com/web/-/merge_requests/17
EOF
OUT=$(bash "$POST" issue_mr_multi "$JOB_DIR/mrs.txt" dev_schemea)
assert_contains "$OUT" "opened 2 MRs" "mr_multi: count plural"
assert_contains "$OUT" "against \`dev_schemea\`" "mr_multi: target branch"
assert_contains "$OUT" "gitlab.example.com/api/-/merge_requests/42" "mr_multi: api MR url"
assert_contains "$OUT" "gitlab.example.com/web/-/merge_requests/17" "mr_multi: web MR url"
assert_contains "$OUT" "## Summary" "mr_multi: summary section"

# Singular
echo "api|https://gitlab.example.com/api/-/merge_requests/42" > "$JOB_DIR/mrs1.txt"
OUT=$(bash "$POST" issue_mr_multi "$JOB_DIR/mrs1.txt" dev_schemea)
assert_contains "$OUT" "opened 1 MR" "mr_multi: count singular"

# With POST_MERGE_NOTICE
OUT_NOTICE=$(POST_MERGE_NOTICE="Will deploy 20m after merge" bash "$POST" issue_mr_multi "$JOB_DIR/mrs.txt" dev_schemea)
assert_contains "$OUT_NOTICE" "Will deploy 20m after merge" "mr_multi: POST_MERGE_NOTICE honored"
unstage_log

# ────────────────────────────────────────────────────────────
# mr_body (NEW)
# ────────────────────────────────────────────────────────────
setup
cat > /tmp/claude-job/output.log <<'EOF'
## Summary

| 平台 | 文件 | 改动 | 影响 |
|---|---|---|---|
| api | x.js | fix close | close button |
EOF
OUT=$(bash "$POST" mr_body "Innoways-Ltd/membership-issue" "42" "https://example.com/run/3")
assert_contains "$OUT" "Innoways-Ltd/membership-issue#42" "mr_body: source issue link"
assert_contains "$OUT" "## Summary" "mr_body: summary inlined"
assert_contains "$OUT" "https://example.com/run/3" "mr_body: run url"
unstage_log

# ────────────────────────────────────────────────────────────
# issue_no_chg (existing)
# ────────────────────────────────────────────────────────────
setup
cat > /tmp/claude-job/output.log <<'EOF'
I need more info to proceed.
EOF
OUT=$(bash "$POST" issue_no_chg "https://example.com/run/4")
assert_contains "$OUT" "did not modify any files" "no_chg: explains no diff"
assert_contains "$OUT" "Reply with @claude" "no_chg: retry guidance"
assert_contains "$OUT" "https://example.com/run/4" "no_chg: run url"
unstage_log

# ────────────────────────────────────────────────────────────
# issue_blocked (existing)
# ────────────────────────────────────────────────────────────
setup
OUT=$(bash "$POST" issue_blocked "https://example.com/run/5" "- api: secrets/foo")
assert_contains "$OUT" "Aborted" "blocked: aborted header"
assert_contains "$OUT" "secrets/foo" "blocked: violation path"

# ────────────────────────────────────────────────────────────
# wiki_answer (existing — regression check)
# ────────────────────────────────────────────────────────────
setup
cat > /tmp/claude-job/output.log <<'EOF'
some chatter

## Answer

This is the wiki answer.

## 1. Sub-section under answer

Stuff.
EOF
OUT=$(bash "$POST" wiki_answer "https://example.com/run/6" "0")
assert_contains "$OUT" "## Answer" "wiki_answer: answer heading"
assert_contains "$OUT" "## 1. Sub-section under answer" "wiki_answer: nested subsection retained"
assert_not_contains "$OUT" ":warning:" "wiki_answer: no dirty warning when DIRTY=0"

OUT_DIRTY=$(bash "$POST" wiki_answer "https://example.com/run/6" "1")
assert_contains "$OUT_DIRTY" ":warning:" "wiki_answer: warning when DIRTY=1"
unstage_log

# Cleanup
rm -rf "$JOB_DIR"
rm -f /tmp/claude-job/output.log

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

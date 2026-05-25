#!/bin/bash
# Tests for scripts/precheck-remote-base.sh.
#
# Each case builds a tiny fake-remote + local-clone pair, manipulates state
# to model a scenario, and asserts the script's exit code.
#
# Exit-code contract under test:
#   0  no remote drift   → safe to push
#   1  remote moved      → conflict
#   2  any failure mode  → conflict (caller treats as 1, fails loud here)

set -u

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PRECHECK="$SCRIPT_DIR/scripts/precheck-remote-base.sh"

TESTS_PASSED=0
TESTS_FAILED=0
FAIL_REASONS=()

assert_exit() {
  local actual="$1" expected="$2" label="$3"
  if [ "$actual" = "$expected" ]; then
    echo "  PASS  $label (exit=$actual)"
    TESTS_PASSED=$((TESTS_PASSED + 1))
  else
    echo "  FAIL  $label (expected=$expected, actual=$actual)"
    TESTS_FAILED=$((TESTS_FAILED + 1))
    FAIL_REASONS+=("$label: expected exit $expected, got $actual")
  fi
}

# make_repo <tmpdir> <branch>
# Builds remote.git + workspace (clone) on <branch> with one seed commit.
# Sets the bare remote's HEAD so subsequent clones (e.g. the "other" clone in
# test 2) don't end up on a detached/missing branch.
# Echoes the absolute path of the workspace directory.
make_repo() {
  local tmp="$1" branch="$2"
  local remote="$tmp/remote.git" seed="$tmp/seed" workspace="$tmp/workspace"
  git init --bare -q "$remote"
  git init -q "$seed"
  git -C "$seed" config user.email t@x.com
  git -C "$seed" config user.name T
  echo seed > "$seed/f.txt"
  git -C "$seed" add f.txt
  git -C "$seed" commit -q -m init
  git -C "$seed" branch -m "$branch"
  git -C "$seed" remote add origin "$remote"
  git -C "$seed" push -q -u origin "$branch"
  git -C "$remote" symbolic-ref HEAD "refs/heads/$branch"
  git clone -q -b "$branch" "$remote" "$workspace"
  echo "$workspace"
}

# Test 1: clean state — exit 0
TMP=$(mktemp -d)
WORKSPACE=$(make_repo "$TMP" dev)
# Simulate Claude making a commit on top of origin/dev so HEAD~1 == origin/dev
echo "claude edit" > "$WORKSPACE/g.txt"
git -C "$WORKSPACE" config user.email c@x.com
git -C "$WORKSPACE" config user.name C
git -C "$WORKSPACE" add g.txt
git -C "$WORKSPACE" commit -q -m "fix #1: edit"
"$PRECHECK" "$WORKSPACE" dev >/dev/null 2>&1
assert_exit "$?" 0 "test1: clean state (HEAD~1 == origin/dev)"
rm -rf "$TMP"

# Test 2: remote advanced — exit 1
TMP=$(mktemp -d)
WORKSPACE=$(make_repo "$TMP" dev)
REMOTE_DIR="$TMP/remote.git"
# Simulate Claude's commit
echo "claude edit" > "$WORKSPACE/g.txt"
git -C "$WORKSPACE" config user.email c@x.com
git -C "$WORKSPACE" config user.name C
git -C "$WORKSPACE" add g.txt
git -C "$WORKSPACE" commit -q -m "fix #1: edit"
# Simulate someone else pushing to dev in a separate clone, after our reset
OTHER="$TMP/other"
git clone -q "$REMOTE_DIR" "$OTHER"
git -C "$OTHER" config user.email h@x.com
git -C "$OTHER" config user.name H
echo "human change" > "$OTHER/h.txt"
git -C "$OTHER" add h.txt
git -C "$OTHER" commit -q -m "human pushed mid-run"
git -C "$OTHER" push -q origin dev
"$PRECHECK" "$WORKSPACE" dev >/dev/null 2>&1
assert_exit "$?" 1 "test2: remote advanced after our reset"
rm -rf "$TMP"

# Test 3: missing target branch on remote — exit 2 (treated as conflict)
TMP=$(mktemp -d)
WORKSPACE=$(make_repo "$TMP" dev)
echo "claude edit" > "$WORKSPACE/g.txt"
git -C "$WORKSPACE" config user.email c@x.com
git -C "$WORKSPACE" config user.name C
git -C "$WORKSPACE" add g.txt
git -C "$WORKSPACE" commit -q -m "fix #1: edit"
"$PRECHECK" "$WORKSPACE" dev_nonexistent >/dev/null 2>&1
assert_exit "$?" 2 "test3: branch not on remote → exit 2"
rm -rf "$TMP"

# Test 4: not a git repo — exit 2
TMP=$(mktemp -d)
mkdir -p "$TMP/notarepo"
"$PRECHECK" "$TMP/notarepo" dev >/dev/null 2>&1
assert_exit "$?" 2 "test4: target dir is not a git repo"
rm -rf "$TMP"

# Test 5: no HEAD~1 yet (fresh repo with no commits beyond seed reset) — exit 2
TMP=$(mktemp -d)
WORKSPACE=$(make_repo "$TMP" dev)
# Don't add a Claude commit — HEAD~1 is unreachable (only one commit on the
# branch). The script should refuse rather than guess.
"$PRECHECK" "$WORKSPACE" dev >/dev/null 2>&1
assert_exit "$?" 2 "test5: no HEAD~1 (no Claude commit yet)"
rm -rf "$TMP"

# Test 6: usage error — exit 2
"$PRECHECK" >/dev/null 2>&1
assert_exit "$?" 2 "test6: no args (usage error)"

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

#!/bin/bash
# Fail-fast collision guard for direct_push mode (plan §14 locked decision).
#
# Compares the local HEAD~1 (our base before Claude's commit) with the remote
# tip of the target branch. If they differ, someone — human or another runner —
# pushed in the window between our `git reset --hard origin/<base>` and now.
# We refuse to push (and refuse to rebase Claude's commit onto unknown work)
# and exit non-zero so the workflow surfaces the conflict to the issue.
#
# This is opt-in via ON_CONFLICT=fail (the default). Projects that prefer the
# legacy "rebase silently" behavior can set ON_CONFLICT=rebase and skip
# invoking this script entirely.
#
# Usage:
#   precheck-remote-base.sh <subproject_dir> <target_branch>
#
# Required env: (none beyond what the calling step exports)
#
# Exit codes:
#   0  remote tip == local HEAD~1   → safe to push
#   1  remote moved                 → conflict; caller should post issue comment
#   2  git invocation failed        → caller should treat as conflict (safer than push)

set -uo pipefail

SUB_DIR="${1:-}"
TARGET_BRANCH="${2:-}"

if [ -z "$SUB_DIR" ] || [ -z "$TARGET_BRANCH" ]; then
  echo "Usage: precheck-remote-base.sh <subproject_dir> <target_branch>" >&2
  exit 2
fi

if [ ! -d "$SUB_DIR/.git" ] && [ ! -f "$SUB_DIR/.git" ]; then
  echo "::error::precheck: $SUB_DIR is not a git repository" >&2
  exit 2
fi

cd "$SUB_DIR" || exit 2

# HEAD~1 = parent of our new commit, i.e. what we reset to at the start of
# the run. If that's not the current origin tip, the remote advanced.
if ! LOCAL_BASE=$(git rev-parse HEAD~1 2>/dev/null); then
  echo "::error::precheck: cannot resolve HEAD~1 in $SUB_DIR (no commit yet?)" >&2
  exit 2
fi

if ! REMOTE_LINE=$(git ls-remote --heads origin "$TARGET_BRANCH" 2>/dev/null); then
  echo "::error::precheck: git ls-remote origin $TARGET_BRANCH failed" >&2
  exit 2
fi

REMOTE_HEAD=$(printf '%s\n' "$REMOTE_LINE" | awk '{print $1}')
if [ -z "$REMOTE_HEAD" ]; then
  echo "::error::precheck: remote returned no SHA for branch $TARGET_BRANCH" >&2
  exit 2
fi

if [ "$LOCAL_BASE" = "$REMOTE_HEAD" ]; then
  echo "precheck: ${SUB_DIR##*/} OK — local base $LOCAL_BASE == origin/$TARGET_BRANCH"
  exit 0
fi

# Print enough context for the caller to compose a useful issue comment.
echo "::warning::precheck: remote moved on ${SUB_DIR##*/}" >&2
echo "  local HEAD~1 = $LOCAL_BASE" >&2
echo "  origin/$TARGET_BRANCH = $REMOTE_HEAD" >&2
exit 1

#!/bin/bash
# Sets a single claude:* status label on the issue, removing any other claude:*
# status labels so the labels reflect the run's final outcome (no stacking on
# retries).
#
# The "entry" labels claude:fix and claude:wiki (set by issue templates) are
# NEVER touched here — they identify the request type and persist across
# retries.
#
# Usage:
#   set-issue-label.sh <state>
#
# Valid states: pushed | no-change | blocked | run-failed | answered
#
# Required env: GH_TOKEN, REPO_FULL, ISSUE_NUMBER
# Best-effort — errors are logged as warnings, not fatal (the workflow's
# primary job is fixing code / answering questions, not maintaining label
# hygiene).

set -uo pipefail

STATE="${1:-}"
ALL_STATES="pushed no-change blocked run-failed answered"

case " $ALL_STATES " in
  *" $STATE "*) ;;
  *) echo "set-issue-label.sh: invalid state '$STATE' (expected: $ALL_STATES)" >&2; exit 2 ;;
esac

if [ -z "${GH_TOKEN:-}" ] || [ -z "${REPO_FULL:-}" ] || [ -z "${ISSUE_NUMBER:-}" ]; then
  echo "set-issue-label.sh: GH_TOKEN, REPO_FULL, ISSUE_NUMBER must be set" >&2
  exit 2
fi

for L in $ALL_STATES; do
  if [ "$L" != "$STATE" ]; then
    gh issue edit "$ISSUE_NUMBER" --repo "$REPO_FULL" --remove-label "claude:$L" >/dev/null 2>&1 || true
  fi
done
gh issue edit "$ISSUE_NUMBER" --repo "$REPO_FULL" --add-label "claude:$STATE" >/dev/null 2>&1 \
  || echo "::warning::Could not set label claude:$STATE on issue #$ISSUE_NUMBER (label may not exist)"

#!/bin/bash
# Sets a single claude:* status label on the issue, removing any other claude:*
# status labels so the labels reflect the run's final outcome (no stacking on
# retries).
#
# The "entry" labels claude:fix and claude:wiki (set by issue templates) are
# NEVER touched here — they identify the request type and persist across
# retries.
#
# Two invocation styles supported:
#   set-issue-label.sh <state>                              (legacy, picks from builtin allowlist)
#   set-issue-label.sh --label <name> [--label-set 'a b c'] (config-driven)
#
# The legacy form keeps existing callers working. The --label form lets a
# project-config.yml inject custom labels (e.g. mr-opened for merge_request
# mode) without modifying this script.
#
# Required env: GH_TOKEN, REPO_FULL, ISSUE_NUMBER
# Best-effort — errors are logged as warnings, not fatal (the workflow's
# primary job is fixing code / answering questions, not maintaining label
# hygiene).

set -uo pipefail

# Builtin set of status labels — used by the legacy positional form AND as the
# default --label-set for the new form. When --label-set is provided, only
# those names get cleared before applying the new one.
BUILTIN_STATES="pushed no-change blocked run-failed answered mr-opened conflict"

STATE=""
LABEL_SET="$BUILTIN_STATES"
LEGACY_FORM=1

if [ $# -ge 1 ] && [ "$1" = "--label" ]; then
  LEGACY_FORM=0
  shift
  STATE="${1:-}"
  shift || true
  if [ $# -ge 1 ] && [ "$1" = "--label-set" ]; then
    shift
    LABEL_SET="${1:-$BUILTIN_STATES}"
    shift || true
  fi
elif [ $# -ge 1 ] && [ "${1#--}" = "$1" ]; then
  STATE="$1"
else
  echo "Usage: set-issue-label.sh <state>" >&2
  echo "       set-issue-label.sh --label <name> [--label-set 'a b c']" >&2
  exit 2
fi

if [ -z "$STATE" ]; then
  echo "set-issue-label.sh: empty label name" >&2
  exit 2
fi

# Validate only in legacy form so we catch typos like 'mr_opened' (underscore
# instead of dash). In --label form we trust the caller (project-config.yml
# is already validated by load-project-config.py).
if [ "$LEGACY_FORM" = "1" ]; then
  case " $BUILTIN_STATES " in
    *" $STATE "*) ;;
    *) echo "set-issue-label.sh: invalid state '$STATE' (expected: $BUILTIN_STATES)" >&2; exit 2 ;;
  esac
fi

if [ -z "${GH_TOKEN:-}" ] || [ -z "${REPO_FULL:-}" ] || [ -z "${ISSUE_NUMBER:-}" ]; then
  echo "set-issue-label.sh: GH_TOKEN, REPO_FULL, ISSUE_NUMBER must be set" >&2
  exit 2
fi

for L in $LABEL_SET; do
  if [ "$L" != "$STATE" ]; then
    gh issue edit "$ISSUE_NUMBER" --repo "$REPO_FULL" --remove-label "claude:$L" >/dev/null 2>&1 || true
  fi
done
gh issue edit "$ISSUE_NUMBER" --repo "$REPO_FULL" --add-label "claude:$STATE" >/dev/null 2>&1 \
  || echo "::warning::Could not set label claude:$STATE on issue #$ISSUE_NUMBER (label may not exist)"

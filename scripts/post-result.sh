#!/bin/bash
# Build markdown bodies for issue comments after Claude runs.
# Avoids YAML literal-block heredoc indent problems by living in its own file.
#
# Usage:
#   post-result.sh issue_pushed_multi  <pushed_list_file> <target_branch>           > issue-comment.md   (one line per push: 'sub|sha')
#   post-result.sh issue_push_failed   <run_url> <failed_subs> <pushed_list_file> <target_branch>
#                                                                                   > push-failed.md
#   post-result.sh issue_no_chg        <run_url>                                    > no-change-comment.md
#   post-result.sh issue_blocked       <run_url>   <paths>                          > blocked-comment.md
#   post-result.sh wiki_answer         <run_url>   [dirty]                          > wiki-comment.md
#
# Reads /tmp/claude-job/output.log when the body needs Claude's tail output.
#
# Optional env:
#   POST_MERGE_NOTICE   one-line text appended to issue_pushed_multi (e.g. deploy
#                       timing). Empty / unset = no notice line.

set -euo pipefail

MODE="${1:-}"
TAIL_FILE="/tmp/claude-job/output.log"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
EXTRACT_SUMMARY="$SCRIPT_DIR/extract-summary.py"

# render_section <fallback_lines> [keyword_regex]
# Outputs Claude's '## Summary' (default) or '## Answer' (when keyword
# regex includes "answer") section, falling back to the last N lines
# wrapped in a code block — see extract-summary.py.
render_section() {
  local fallback="${1:-50}"
  local keywords="${2:-}"
  if [ ! -f "$TAIL_FILE" ]; then
    echo "(no log)"
    return
  fi
  if [ -n "$keywords" ]; then
    python3 "$EXTRACT_SUMMARY" "$fallback" --keywords "$keywords" < "$TAIL_FILE"
  else
    python3 "$EXTRACT_SUMMARY" "$fallback" < "$TAIL_FILE"
  fi
}

case "$MODE" in
  issue_pushed_multi)
    # Args: <pushed_list_file> <target_branch>
    # List file: one 'sub|short_sha' line per push.
    LIST_FILE="$2"
    TARGET_BRANCH="${3:-dev}"
    if [ ! -f "$LIST_FILE" ]; then
      echo "issue_pushed_multi: list file not found: $LIST_FILE" >&2
      exit 2
    fi
    COUNT=$(grep -c '|' "$LIST_FILE" || true)
    if [ "$COUNT" = "1" ]; then
      printf '**Claude pushed 1 commit directly to `%s`:**\n\n' "$TARGET_BRANCH"
    else
      printf '**Claude pushed %s commits directly to `%s`:**\n\n' "$COUNT" "$TARGET_BRANCH"
    fi
    while IFS='|' read -r sub sha; do
      [ -z "$sub" ] && continue
      printf -- '- `%s` → `%s`\n' "$sub" "$sha"
    done < "$LIST_FILE"
    printf '\n'
    render_section 50
    if [ -n "${POST_MERGE_NOTICE:-}" ]; then
      printf '\n\n%s\n' "$POST_MERGE_NOTICE"
    fi
    ;;

  issue_push_failed)
    # Args: <run_url> <failed_subs_str> <pushed_list_file> <target_branch>
    RUN_URL="$2"
    FAILED_SUBS="$3"
    LIST_FILE="$4"
    TARGET_BRANCH="${5:-dev}"
    printf 'Claude run failed: push to `%s` failed for **%s**.\n\n' "$TARGET_BRANCH" "$FAILED_SUBS"
    if [ -f "$LIST_FILE" ] && [ -s "$LIST_FILE" ]; then
      printf 'Subprojects already pushed (cannot rollback):\n\n'
      while IFS='|' read -r sub sha; do
        [ -z "$sub" ] && continue
        printf -- '- `%s` → `%s`\n' "$sub" "$sha"
      done < "$LIST_FILE"
      printf '\n'
    fi
    printf '[Run log](%s)\n' "$RUN_URL"
    ;;

  issue_no_chg)
    RUN_URL="$2"
    printf 'Claude did not modify any files. Likely needs more info or could not understand the request.\n\n'
    printf '**Claude response (last 100 lines):**\n\n'
    printf '```\n'
    [ -f "$TAIL_FILE" ] && tail -100 "$TAIL_FILE" || echo "(no log)"
    printf '```\n\n'
    printf 'Reply with @claude and more details to retrigger.\n\n[Full run log](%s)\n' "$RUN_URL"
    ;;

  issue_blocked)
    RUN_URL="$2"
    PATHS="$3"
    printf '**Aborted: Claude tried to modify sensitive paths.**\n\n%s\n' "$PATHS"
    printf 'No commit pushed. Admin must handle manually.\n\n[Run log](%s)\n' "$RUN_URL"
    ;;

  wiki_answer)
    RUN_URL="$2"
    DIRTY="${3:-0}"
    if [ "$DIRTY" = "1" ]; then
      printf '> :warning: Claude attempted to modify files in wiki mode. Changes were reverted automatically; the answer below is for reference only.\n\n'
    fi
    # Wiki answers commonly contain nested `##` sections (e.g. "## 1. ..."),
    # so we cannot use extract-summary.py (which stops at the next same-level
    # heading). Instead, take everything from "## Answer" / "## 答案" /
    # "## 回答" / "## 回复" to end of file. Fall back to last 100 lines wrapped
    # in a code block if no Answer heading was emitted.
    if [ -f "$TAIL_FILE" ]; then
      EXTRACTED=$(awk '
        /^##[[:space:]]+(Answer|答案|回答|回复)([[:space:]]|$)/ { found=1 }
        found { print }
      ' "$TAIL_FILE")
      if [ -n "$EXTRACTED" ]; then
        printf '%s\n' "$EXTRACTED"
      else
        printf '```\n'
        tail -100 "$TAIL_FILE"
        printf '\n```\n'
      fi
    else
      echo "(no log)"
    fi
    printf '\n\n---\n[Full run log](%s)\n' "$RUN_URL"
    ;;

  *)
    echo "Unknown mode: $MODE" >&2
    exit 2
    ;;
esac

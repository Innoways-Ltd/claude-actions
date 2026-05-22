#!/usr/bin/env python3
"""Build the Claude prompt for a feature-request run.

Reads /tmp/claude-job/issue.json (output of `gh issue view --json
title,body,comments`) and prints a markdown prompt to stdout.

Structural sibling of `build-bug-prompt.py` — same env contract,
same Summary table format so post-result.sh / extract-summary.py
keep working unchanged. Diverges from bug mode in three places:
  1. Heading is "Feature request:" not "Tester issue:"
  2. An "## Acceptance criteria" section is extracted from the
     issue body so Claude treats it as a checklist
  3. Instructions allow new files / small abstractions where the
     feature warrants them — bug mode forbids that

Required env:
  WORKSPACE_ROOT             absolute path to the parent dir on the runner
  SUBPROJECTS                space-separated subproject dir names
  PROJECT_OVERVIEW           multiline text shown under "Workspace layout"
  SUBPROJECT_DESCRIPTIONS    multiline markdown bullets, one per subproject
  REPO_FULL                  GitHub repo (owner/name)
  ISSUE_NUMBER               GitHub issue number
  TARGET                     declared Target Project (full subproject name)
  GITLAB_TARGET_BRANCH       branch MRs target (used in instructions)

Optional env:
  DOCS_PATH                  subdir under WORKSPACE_ROOT (e.g. "docs"); empty = skip
  DOCS_INLINE                space-separated docs to inline (filenames relative to DOCS_PATH)
"""
import json
import os
import re
import sys


def env_required(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        print(f"build-feature-prompt.py: missing required env var {name}", file=sys.stderr)
        sys.exit(2)
    return val


def list_docs(docs_dir: str) -> list[str]:
    try:
        return sorted(f for f in os.listdir(docs_dir) if f.endswith(".md"))
    except (FileNotFoundError, OSError):
        return []


def read_doc(docs_dir: str, name: str) -> str | None:
    path = os.path.join(docs_dir, name)
    try:
        with open(path) as f:
            return f.read()
    except (FileNotFoundError, OSError):
        return None


def extract_acceptance_criteria(body: str) -> str | None:
    # The feature-request.yml template renders the "Acceptance criteria"
    # textarea as `### Acceptance criteria` followed by free-form text
    # until the next `###` heading (or EOF). Capture that block verbatim
    # so we can re-surface it as a checklist.
    m = re.search(
        r"###\s+Acceptance criteria[^\n]*\n(.*?)(?=\n###\s|\Z)",
        body,
        re.S,
    )
    if not m:
        return None
    return m.group(1).strip() or None


def main() -> int:
    issue_path = "/tmp/claude-job/issue.json"
    if not os.path.exists(issue_path):
        print(f"Missing {issue_path}", file=sys.stderr)
        return 1

    workspace_root = env_required("WORKSPACE_ROOT")
    subprojects = env_required("SUBPROJECTS").split()
    project_overview = env_required("PROJECT_OVERVIEW").rstrip()
    subproject_descriptions = env_required("SUBPROJECT_DESCRIPTIONS").rstrip()
    repo = env_required("REPO_FULL")
    issue_num = env_required("ISSUE_NUMBER")
    target = env_required("TARGET")
    gitlab_target_branch = os.environ.get("GITLAB_TARGET_BRANCH", "dev")

    docs_subpath = os.environ.get("DOCS_PATH", "").strip()
    docs_inline = os.environ.get("DOCS_INLINE", "").split()
    docs_dir = os.path.join(workspace_root, docs_subpath) if docs_subpath else ""

    data = json.load(open(issue_path))
    body = data.get("body") or ""

    lines: list[str] = []
    lines.append(f"# Feature request: {data.get('title','(no title)')}")
    lines.append("")
    lines.append(f"Source: {repo}#{issue_num}")
    lines.append(f"Target Project: {target}")
    lines.append("")
    lines.append("## Workspace layout")
    lines.append("")
    lines.append(f"You are running in `{workspace_root}/`. {project_overview}")
    lines.append("")
    lines.append(subproject_descriptions)
    if docs_dir:
        lines.append(f"- `{docs_subpath}/` — Project documentation (see index below)")
    lines.append("")
    lines.append(
        f"The Target Project declared above is **{target}**, but you MAY read "
        "AND modify any subproject if the feature requires coordinated changes "
        "(e.g. a frontend control paired with a backend endpoint). The workflow "
        "opens one merge request per modified subproject automatically."
    )
    lines.append("")

    if docs_dir:
        lines.append(f"## {docs_subpath}/ index")
        lines.append("")
        lines.append(
            f"Project documentation lives at `{docs_dir}/`. "
            "Read the relevant module doc BEFORE implementing — it explains "
            "domain rules, state machines and side effects that aren't obvious "
            "from the code alone."
        )
        lines.append("")
        for name in list_docs(docs_dir):
            lines.append(f"- `{docs_subpath}/{name}`")
        lines.append("")
        if docs_inline:
            inline_list = ", ".join(f"`{docs_subpath}/{n}`" for n in docs_inline)
            lines.append(f"### Inlined: {inline_list}")
            lines.append("")
            lines.append(
                "These documents give a project bird's-eye view; they are inlined "
                "below to avoid extra Read tool turns and to benefit from prompt "
                "caching across reruns. Re-read from disk if you suspect the "
                "inlined copy is stale."
            )
            for name in docs_inline:
                content = read_doc(docs_dir, name)
                lines.append("")
                lines.append(f"#### `{docs_subpath}/{name}`")
                lines.append("")
                if content is None:
                    lines.append("_(file not present on disk — skip)_")
                else:
                    lines.append("````markdown")
                    lines.append(content.rstrip())
                    lines.append("````")
        lines.append("")

    lines.append("## Issue body")
    lines.append("")
    lines.append(body or "(empty)")

    for c in data.get("comments") or []:
        author = (c.get("author") or {}).get("login", "?")
        created = c.get("createdAt", "")
        cbody = c.get("body") or ""
        lines.append("")
        lines.append(f"## Comment by @{author} ({created})")
        lines.append("")
        lines.append(cbody)

    criteria = extract_acceptance_criteria(body)
    lines.append("")
    lines.append("## Acceptance criteria (must be satisfied)")
    lines.append("")
    if criteria:
        lines.append(
            "Extracted from the issue body. Each line below is a requirement "
            "your implementation must address — surface them explicitly in the "
            "`## Summary` table at the end of your response."
        )
        lines.append("")
        lines.append("```")
        lines.append(criteria)
        lines.append("```")
    else:
        lines.append(
            "_(No `### Acceptance criteria` block found in the issue body. "
            "Infer the acceptance bar from the issue's 'What' and 'Why' "
            "fields and state your assumed criteria in the Summary.)_"
        )

    lines.append("")
    lines.append("## Instructions")
    lines.append("")
    if docs_dir:
        lines.append(
            f"1. **Read the relevant `{docs_subpath}/*.md` first** to understand the "
            "module before touching code. The docs encode business rules and "
            "side-effects that the code alone won't reveal."
        )
    else:
        lines.append(
            "1. **Read the relevant code first** to understand the module "
            "before changing it. Trace imports / call graph before editing."
        )
    lines.append(
        "2. **Implement the requested feature end-to-end.** Unlike a bug fix, "
        "feature work is allowed to introduce new files, helpers, and small "
        "abstractions where the feature genuinely warrants them. BUT: match "
        "existing conventions in the target subproject — don't introduce a "
        "new framework, state-management pattern, or coding style just for "
        "this feature. Mirror the patterns already used in nearby code."
    )
    lines.append(
        "3. **Every acceptance criterion above must be addressed** in your "
        "implementation and reflected in the `## Summary` table at the end. "
        "If a criterion is ambiguous, state your interpretation in the "
        "Summary rather than guessing silently."
    )
    lines.append(
        "4. **If you need clarification before you can implement**, output ONE "
        "concise question and stop without modifying any files. The workflow "
        "detects no diff = clarification needed and posts your output to the "
        "source issue."
    )
    # NOTE: keep this list in sync with the `case` patterns in
    # .github/workflows/claude.yml step "Sensitive-path post-check across all
    # subprojects". Drift means Claude either gets blocked without warning, or
    # tries paths it was warned to skip.
    lines.append("5. **Do NOT modify any of these paths** (MR will be aborted if you do):")
    lines.append("   - `*.env*`, `secrets/**`, `.github/**`, `.gitlab/**`, `.gitlab-ci.yml`")
    lines.append("   - `**/migrations/**`, `schema/**`")
    lines.append("   - `controllers/auth/**`, `middleware/auth/**`, `action/login/**`, any `**/auth/**`")
    lines.append("   - `package.json` `dependencies` field")
    lines.append(
        f"6. **Do NOT commit, push, or open MRs yourself** — the workflow handles "
        f"that and opens a merge request on GitLab against the `{gitlab_target_branch}` branch."
    )
    lines.append(
        "7. Run lint where applicable (`npm run lint` or `npx eslint .` for the "
        "frontend; `npx eslint .` for the backend). Fix any new lint errors you "
        "introduced."
    )
    lines.append(
        "8. **Output a `## Summary` section at the very end of your response.** "
        "The workflow parses this section and posts it as the GitHub issue "
        "comment and GitLab MR descriptions. Use the exact markdown table "
        "format below. Write all cell contents in **English** regardless of "
        "the issue language. The heading `## Summary` and column headers "
        "must stay as-is so the parser can find them."
    )
    lines.append("")
    lines.append("   ## Summary")
    lines.append("")
    lines.append("   | 平台 / Platform | 文件路径 / File | 改动内容 / Change | 影响范围 / Impact |")
    lines.append("   |------|------|------|------|")
    for sub in subprojects:
        lines.append(f"   | {sub} | <relative path> | <one-line what changed (English)> | <one-line impact (English)> |")
    lines.append("")
    lines.append(
        "   - One row per modified file. Span multiple subprojects when the "
        "feature touches more than one."
    )
    lines.append(
        "   - After the file table, add a short **Acceptance criteria covered** "
        "subsection that lists each criterion from above and how your "
        "implementation satisfies it (one line per criterion)."
    )
    lines.append(
        "   - If you made no code changes (clarification only), still output "
        "the `## Summary` heading followed by a single line stating what info "
        "is missing — do not output the table."
    )
    lines.append("")
    lines.append("Begin.")

    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())

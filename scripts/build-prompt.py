#!/usr/bin/env python3
"""Build the Claude prompt for a bug-fix, feature-request, or wiki run.

Reads /tmp/claude-job/issue.json (output of `gh issue view --json
title,body,comments`) and prints a markdown prompt to stdout. The exact
sections emitted depend on --mode:

  bug      Tester issue framing + Summary table at end; docs section if DOCS_PATH set
  feature  Feature-request framing + extracted "Acceptance criteria" section
           + Summary table; allows new files / small abstractions
  wiki     Read-only Q&A framing + Answer template; no code modification, jargon-banned

All modes get the GitNexus MCP intro when GITNEXUS_REPOS is non-empty.

Replaces the prior trio of build-bug-prompt.py / build-feature-prompt.py /
build-wiki-prompt.py, which were ~80% duplicated.

Required env (all modes):
  WORKSPACE_ROOT, SUBPROJECTS, SUBPROJECT_DESCRIPTIONS, REPO_FULL, ISSUE_NUMBER

Additional required env for bug + feature modes:
  PROJECT_OVERVIEW, TARGET, TARGET_BRANCH

Optional env:
  DOCS_PATH                  bug/feature: subdir under WORKSPACE_ROOT for docs
  DOCS_INLINE                bug/feature: space-separated docs to inline
  GITNEXUS_REPOS             repos indexed in GitNexus (defaults to SUBPROJECTS;
                             pass ' ' to disable the GitNexus section in all modes)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import Any


MODE_BUG = "bug"
MODE_FEATURE = "feature"
MODE_WIKI = "wiki"
ALL_MODES = (MODE_BUG, MODE_FEATURE, MODE_WIKI)


# ────────────────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────────────────

def _env_required(name: str) -> str:
    """Return the env var or exit non-zero with a clear message."""
    val = os.environ.get(name)
    if not val:
        print(f"build-prompt.py: missing required env var {name}", file=sys.stderr)
        sys.exit(2)
    return val


def _list_docs(docs_dir: str) -> list[str]:
    try:
        return sorted(f for f in os.listdir(docs_dir) if f.endswith(".md"))
    except (FileNotFoundError, OSError):
        return []


def _read_doc(docs_dir: str, name: str) -> str | None:
    try:
        with open(os.path.join(docs_dir, name)) as fh:
            return fh.read()
    except (FileNotFoundError, OSError):
        return None


def _extract_acceptance_criteria(body: str) -> str | None:
    """Pull the "Acceptance criteria" textarea block from a feature-request body.

    The feature-request.yml template renders it as `### Acceptance criteria`
    followed by free-form text until the next `###` heading (or EOF).
    """
    m = re.search(
        r"###\s+Acceptance criteria[^\n]*\n(.*?)(?=\n###\s|\Z)",
        body,
        re.S,
    )
    if not m:
        return None
    return m.group(1).strip() or None


# ────────────────────────────────────────────────────────────────────────────
# Context loading
# ────────────────────────────────────────────────────────────────────────────

def _load_context(mode: str) -> dict[str, Any]:
    issue_path = "/tmp/claude-job/issue.json"
    if not os.path.exists(issue_path):
        print(f"Missing {issue_path}", file=sys.stderr)
        sys.exit(1)

    ctx: dict[str, Any] = {
        "workspace_root": _env_required("WORKSPACE_ROOT"),
        "subprojects": _env_required("SUBPROJECTS").split(),
        "subproject_descriptions": _env_required("SUBPROJECT_DESCRIPTIONS").rstrip(),
        "repo": _env_required("REPO_FULL"),
        "issue_num": _env_required("ISSUE_NUMBER"),
        "data": json.load(open(issue_path)),
    }

    if mode in (MODE_BUG, MODE_FEATURE):
        ctx["project_overview"] = _env_required("PROJECT_OVERVIEW").rstrip()
        ctx["target"] = _env_required("TARGET")
        ctx["target_branch"] = os.environ.get("TARGET_BRANCH", "dev")
        ctx["docs_subpath"] = os.environ.get("DOCS_PATH", "").strip()
        ctx["docs_inline"] = os.environ.get("DOCS_INLINE", "").split()
        ctx["docs_dir"] = (
            os.path.join(ctx["workspace_root"], ctx["docs_subpath"])
            if ctx["docs_subpath"]
            else ""
        )

    # GITNEXUS_REPOS defaults to SUBPROJECTS. An explicit ' ' (whitespace)
    # value parses to an empty list and disables the GitNexus section for
    # projects without an index. Loaded for every mode (wiki, bug, feature) —
    # the workflow's `Reindex gitnexus` step refreshes the index per run.
    raw = os.environ.get("GITNEXUS_REPOS")
    ctx["gitnexus_repos"] = (
        ctx["subprojects"] if raw is None else raw.split()
    )

    return ctx


# ────────────────────────────────────────────────────────────────────────────
# Section builders (each returns list[str])
# ────────────────────────────────────────────────────────────────────────────

def _section_header(ctx: dict[str, Any], mode: str) -> list[str]:
    title = ctx["data"].get("title", "(no title)")
    headings = {
        MODE_BUG: "Tester issue",
        MODE_FEATURE: "Feature request",
        MODE_WIKI: "Wiki question",
    }
    lines = [f"# {headings[mode]}: {title}", ""]
    lines.append(f"Source: {ctx['repo']}#{ctx['issue_num']}")
    if mode in (MODE_BUG, MODE_FEATURE):
        lines.append(f"Target Project: {ctx['target']}")
    lines.append("")
    return lines


def _section_workspace(ctx: dict[str, Any], mode: str) -> list[str]:
    lines: list[str] = []
    if mode == MODE_WIKI:
        # Read-only framing — no project_overview, no docs follow-up.
        lines.append("## Workspace (read-only references)")
        lines.append("")
        lines.append(
            f"You are running in `{ctx['workspace_root']}/`. The following are "
            "available for **reading only** — do not modify any file:"
        )
        lines.append("")
        lines.append(ctx["subproject_descriptions"])
        lines.append("")
        return lines

    # bug/feature
    lines.append("## Workspace layout")
    lines.append("")
    lines.append(
        f"You are running in `{ctx['workspace_root']}/`. {ctx['project_overview']}"
    )
    lines.append("")
    lines.append(ctx["subproject_descriptions"])
    if ctx["docs_dir"]:
        lines.append(
            f"- `{ctx['docs_subpath']}/` — Project documentation (see index below)"
        )
    lines.append("")

    coord = "bug requires coordinated changes" if mode == MODE_BUG else "feature requires coordinated changes"
    example = (
        "(e.g. a frontend request body change paired with a backend handler change)"
        if mode == MODE_BUG
        else "(e.g. a frontend control paired with a backend endpoint)"
    )
    lines.append(
        f"The Target Project declared above is **{ctx['target']}**, but you MAY read "
        f"AND modify any subproject if the {coord} "
        f"{example}. The workflow commits and pushes one commit per modified "
        f"subproject directly to the `{ctx['target_branch']}` branch automatically."
    )
    lines.append("")
    return lines


def _section_docs(ctx: dict[str, Any], mode: str) -> list[str]:
    """Emit the docs/ index + inlined docs. bug/feature only."""
    if not ctx["docs_dir"]:
        return []

    docs_subpath = ctx["docs_subpath"]
    docs_dir = ctx["docs_dir"]
    verb_phrase = "changing code" if mode == MODE_BUG else "implementing"

    lines = [
        f"## {docs_subpath}/ index",
        "",
        (
            f"Project documentation lives at `{docs_dir}/`. "
            f"Read the relevant module doc BEFORE {verb_phrase} — it explains "
            "domain rules, state machines and side effects that aren't obvious "
            "from the code alone."
        ),
        "",
    ]
    for name in _list_docs(docs_dir):
        lines.append(f"- `{docs_subpath}/{name}`")
    lines.append("")

    if ctx["docs_inline"]:
        inline_list = ", ".join(f"`{docs_subpath}/{n}`" for n in ctx["docs_inline"])
        lines.append(f"### Inlined: {inline_list}")
        lines.append("")
        lines.append(
            "These documents give a project bird's-eye view; they are inlined "
            "below to avoid extra Read tool turns and to benefit from prompt "
            "caching across reruns. Re-read from disk if you suspect the "
            "inlined copy is stale."
        )
        for name in ctx["docs_inline"]:
            content = _read_doc(docs_dir, name)
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
    return lines


def _section_gitnexus(ctx: dict[str, Any], mode: str) -> list[str]:
    """GitNexus MCP intro (omitted if GITNEXUS_REPOS is empty).

    Emitted for every mode. The "do not surface code paths" rule is wiki-only:
    bug and feature modes are required to list concrete file paths in their
    Summary table, so for those modes we tell Claude the opposite.
    """
    repos = ctx["gitnexus_repos"]
    if not repos:
        return []

    lines = [
        "## Code intelligence (GitNexus MCP — preferred)",
        "",
        (
            "A pre-indexed code graph is available via `mcp__gitnexus__*` tools. "
            "It is refreshed at the start of every workflow run (no-op when HEAD "
            "hasn't moved), so use it **before** falling back to Read/Grep on the "
            "source tree."
        ),
        "",
    ]
    if len(repos) > 1:
        lines.append(
            "Multiple repos are indexed separately. Pass the matching `repo` argument:"
        )
    else:
        lines.append("The repo is indexed under the `repo` argument shown below:")
    lines.append("")
    for r in repos:
        lines.append(f'- `repo: "{r}"`')
    lines.append("")
    if mode == MODE_WIKI:
        lines.append(
            "Use these tools **internally to find and verify** the answer — "
            "but **do not surface code paths, function names, or file references "
            "in the final answer**. They are for your reasoning, not for the "
            "reader (see Instructions §2 below)."
        )
    else:
        lines.append(
            "Use these tools to locate the file(s) you'll change and trace their "
            "callers/callees before editing. The `## Summary` table at the end "
            "MUST list concrete file paths — gitnexus is the fastest way to find "
            "the right paths."
        )
    lines.append("")
    lines.append(
        "- `mcp__gitnexus__query({query, repo})` — semantic + symbol search; "
        'faster and more precise than Grep for "where is X defined / used".'
    )
    lines.append(
        "- `mcp__gitnexus__context({name, repo})` — 360° view of a symbol: "
        "incoming/outgoing calls, cluster membership, traced processes."
    )
    lines.append(
        "- `mcp__gitnexus__impact({target, repo})` — blast-radius / "
        'dependency tree (read-only; useful for "what depends on X").'
    )
    lines.append(
        "- `mcp__gitnexus__cypher({query, repo})` — raw graph queries when "
        "the above are too coarse."
    )
    lines.append("")
    if len(repos) > 1 and mode == MODE_WIKI:
        lines.append(
            "If a question spans multiple repos (e.g. an API contract), query each "
            "in turn and synthesise the *business behaviour* — never paste "
            "code paths into the answer."
        )
        lines.append("")
    elif len(repos) > 1:
        lines.append(
            "If the fix spans multiple repos (e.g. a frontend request shape "
            "paired with a backend handler), query each repo separately and "
            "use `impact` to confirm you've found every call site."
        )
        lines.append("")
    lines.append(
        "**Fallback policy:** if any gitnexus tool errors, returns nothing, "
        "or the index looks stale (e.g. it names a file you can't Read on "
        "disk), fall back silently to Read/Grep — trust the disk over the "
        "index. Do not surface MCP errors in the final answer to the user."
    )
    lines.append("")
    return lines


def _section_issue_body(ctx: dict[str, Any], mode: str) -> list[str]:
    """Issue body + comments. Heading differs slightly for wiki ('Question')."""
    heading = "Question" if mode == MODE_WIKI else "Issue body"
    body = ctx["data"].get("body") or "(empty)"
    lines = [f"## {heading}", "", body]
    for c in ctx["data"].get("comments") or []:
        author = (c.get("author") or {}).get("login", "?")
        created = c.get("createdAt", "")
        cbody = c.get("body") or ""
        lines.append("")
        lines.append(f"## Comment by @{author} ({created})")
        lines.append("")
        lines.append(cbody)
    return lines


def _section_acceptance(ctx: dict[str, Any]) -> list[str]:
    """Feature mode only — extract `### Acceptance criteria` from body."""
    body = ctx["data"].get("body") or ""
    criteria = _extract_acceptance_criteria(body)
    lines = [
        "",
        "## Acceptance criteria (must be satisfied)",
        "",
    ]
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
    return lines


# Bug + feature instructions share the sensitive-path warning + lint + no-push
# notes; only the read/edit rule (instruction 1) and the body+template rules
# (2–3, 7) diverge. Sharing the constants keeps the two modes in lock-step.

_SENSITIVE_PATHS_INSTRUCTION_BODY = [
    "   - `*.env*`, `secrets/**`, `.github/**`",
    "   - `**/migrations/**`, `schema/**`",
    "   - `controllers/auth/**`, `middleware/auth/**`, `action/login/**`, any `**/auth/**`",
    "   - `package.json` `dependencies` field",
]


def _section_instructions(ctx: dict[str, Any], mode: str) -> list[str]:
    """Mode-specific numbered Instructions list."""
    lines = ["", "## Instructions", ""]

    if mode == MODE_WIKI:
        return lines + _instructions_wiki()

    docs_subpath = ctx["docs_subpath"]
    target_branch = ctx["target_branch"]

    if docs_subpath:
        read_first = (
            f"1. **Read the relevant `{docs_subpath}/*.md` first** to understand the "
            "module before touching code. The docs encode business rules and "
            "side-effects that the code alone won't reveal."
        )
    else:
        read_first = (
            "1. **Read the relevant code first** to understand the module "
            "before changing it. Trace imports / call graph before editing."
        )

    if mode == MODE_BUG:
        return lines + _instructions_bug(read_first, target_branch)
    # feature
    return lines + _instructions_feature(read_first, target_branch)


def _instructions_bug(read_first: str, target_branch: str) -> list[str]:
    lines = [
        read_first,
        (
            "2. Address the issue. Make the smallest correct change. "
            "Don't add features, refactor, or introduce abstractions beyond what the issue requires."
        ),
        (
            "3. **If you need clarification**, output ONE concise question and stop "
            "without modifying any files. The workflow detects no diff = clarification needed "
            "and posts your output to the source issue."
        ),
        # NOTE: keep this list in sync with the `case` patterns in
        # .github/workflows/claude.yml step "Sensitive-path post-check across all
        # subprojects". Drift means Claude either gets blocked without warning, or
        # tries paths it was warned to skip.
        "4. **Do NOT modify any of these paths** (push will be aborted if you do):",
    ]
    lines += _SENSITIVE_PATHS_INSTRUCTION_BODY
    lines.append(
        f"5. **Do NOT commit or push yourself** — the workflow handles that and "
        f"pushes your changes directly to the `{target_branch}` branch."
    )
    lines.append(
        "6. Run lint where applicable (`npm run lint` or `npx eslint .` for the "
        "frontend; `npx eslint .` for the backend). Fix any new lint errors you "
        "introduced."
    )
    lines.append(
        "7. **Output a `## Summary` section at the very end of your response.** "
        "The workflow parses this section and posts it as the GitHub issue "
        "comment. Use the exact markdown table format below. Write all cell "
        "contents in **English** regardless of the issue language. The heading "
        "`## Summary` and column headers must stay as-is so the parser can "
        "find them."
    )
    return lines


def _instructions_feature(read_first: str, target_branch: str) -> list[str]:
    lines = [
        read_first,
        (
            "2. **Implement the requested feature end-to-end.** Unlike a bug fix, "
            "feature work is allowed to introduce new files, helpers, and small "
            "abstractions where the feature genuinely warrants them. BUT: match "
            "existing conventions in the target subproject — don't introduce a "
            "new framework, state-management pattern, or coding style just for "
            "this feature. Mirror the patterns already used in nearby code."
        ),
        (
            "3. **Every acceptance criterion above must be addressed** in your "
            "implementation and reflected in the `## Summary` table at the end. "
            "If a criterion is ambiguous, state your interpretation in the "
            "Summary rather than guessing silently."
        ),
        (
            "4. **If you need clarification before you can implement**, output ONE "
            "concise question and stop without modifying any files. The workflow "
            "detects no diff = clarification needed and posts your output to the "
            "source issue."
        ),
        "5. **Do NOT modify any of these paths** (push will be aborted if you do):",
    ]
    lines += _SENSITIVE_PATHS_INSTRUCTION_BODY
    lines.append(
        f"6. **Do NOT commit or push yourself** — the workflow handles that and "
        f"pushes your changes directly to the `{target_branch}` branch."
    )
    lines.append(
        "7. Run lint where applicable (`npm run lint` or `npx eslint .` for the "
        "frontend; `npx eslint .` for the backend). Fix any new lint errors you "
        "introduced."
    )
    lines.append(
        "8. **Output a `## Summary` section at the very end of your response.** "
        "The workflow parses this section and posts it as the GitHub issue "
        "comment. Use the exact markdown table format below. Write all cell "
        "contents in **English** regardless of the issue language. The heading "
        "`## Summary` and column headers must stay as-is so the parser can "
        "find them."
    )
    return lines


def _instructions_wiki() -> list[str]:
    lines = [
        (
            "**Audience:** the reader is a tester / business user / project "
            "manager — assume they cannot read code. Your job is to explain "
            "**what the system does, when, and why**, in plain language."
        ),
        "",
        (
            "1. **Research thoroughly, then translate to business language.** "
            "Use GitNexus MCP tools as your primary source; fall back to Read/Grep "
            "on the source tree when the graph is too coarse. These are for *your* "
            "reasoning — the reader never sees them."
        ),
        (
            "2. **Do NOT include code paths, file names, function names, "
            "endpoint URLs, class/variable names, or `path:line` references "
            "in the answer.** No doc references either. The wiki answer is for "
            "non-engineers. If a tester needs the code, an engineer will dig."
        ),
        (
            "3. **Avoid jargon. When you must use a domain term, explain it "
            "once in plain language right after first use.** "
            'Banned without explanation: "controller", "endpoint", '
            '"middleware", "state machine", "hook", "action", '
            '"reducer", "store", "validator", "DTO", "schema", '
            '"migration", "transaction", "audit log", error class names '
            "(e.g. `InvalidTransitionError`), HTTP verbs / status codes. "
            '''Replace with what the user observes: "按下按钮 / 系统检查 / '''
            '''状态更新 / 弹出错误提示 / 列表刷新".'''
        ),
        (
            "4. **Reply in the same language as the question** (中文问 → "
            "中文答; English question → English answer)."
        ),
        (
            "5. **Include at least one Mermaid diagram** (`flowchart`, "
            "`sequenceDiagram`, `stateDiagram-v2`, or `erDiagram` — pick the "
            "best fit). **Boxes and edge labels must use business words, not "
            "function names or HTTP routes.** Example: `点击关闭按钮` ✓, "
            "`POST /api/case/:id/close` ✗."
        ),
        (
            "6. **Do NOT modify any files.** This is a Q&A, not a code change. "
            "Read + Grep + GitNexus MCP only."
        ),
        (
            "7. **Do NOT commit or push.** The workflow only posts your answer "
            "as an issue comment."
        ),
        (
            "8. **Output a `## Answer` section at the very end of your "
            "response.** The workflow extracts everything from `## Answer` to "
            "the end of output and posts it as the GitHub issue comment. "
            "Structure your Answer like this:"
        ),
    ]
    return lines


def _section_output_template(ctx: dict[str, Any], mode: str) -> list[str]:
    """The trailing markdown skeleton: Summary table (bug/feature) or Answer block (wiki)."""
    if mode == MODE_WIKI:
        return _output_template_wiki()
    return _output_template_summary(ctx, mode)


def _output_template_summary(ctx: dict[str, Any], mode: str) -> list[str]:
    verb = "fix" if mode == MODE_BUG else "feature"
    lines = [
        "",
        "   ## Summary",
        "",
        "   | 平台 / Platform | 文件路径 / File | 改动内容 / Change | 影响范围 / Impact |",
        "   |------|------|------|------|",
    ]
    for sub in ctx["subprojects"]:
        lines.append(
            f"   | {sub} | <relative path> | <one-line what changed (English)> | <one-line impact (English)> |"
        )
    lines.append("")
    lines.append(
        f"   - One row per modified file. Span multiple subprojects when the "
        f"{verb} touches more than one."
    )
    if mode == MODE_FEATURE:
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
    return lines


def _output_template_wiki() -> list[str]:
    return [
        "",
        "   ## Answer",
        "",
        "   **结论 / Bottom line:** <one short sentence, plain language>",
        "",
        "   **会发生什么 / What happens:**",
        "",
        "   1. <user-visible step in business language>",
        "   2. <next step…>",
        "   3. <…>",
        "",
        "   ```mermaid",
        "   flowchart TD",
        "       A[用户做了什么] --> B{系统判断什么}",
        "       B -->|条件 1| C[结果 1]",
        "       B -->|条件 2| D[结果 2]",
        "   ```",
        "",
        (
            "   **名词解释 / Terminology** *(only include this subsection if "
            "you actually used a domain term that needs explaining)*:"
        ),
        "",
        '   - **"<术语>"**: <一句话用大白话解释>',
        "",
        (
            "   The heading `## Answer` must stay exactly as-is so the "
            "extractor finds it. The subsections above are the recommended "
            "shape — feel free to add an example scenario or a short "
            '"为什么会这样设计" note if it helps the reader, but never '
            "add file paths or code references."
        ),
        "",
    ]


# ────────────────────────────────────────────────────────────────────────────
# Orchestration
# ────────────────────────────────────────────────────────────────────────────

def _build_prompt(ctx: dict[str, Any], mode: str) -> list[str]:
    lines: list[str] = []
    lines += _section_header(ctx, mode)
    lines += _section_workspace(ctx, mode)
    if mode in (MODE_BUG, MODE_FEATURE):
        lines += _section_docs(ctx, mode)
    lines += _section_gitnexus(ctx, mode)
    lines += _section_issue_body(ctx, mode)
    if mode == MODE_FEATURE:
        lines += _section_acceptance(ctx)
    lines += _section_instructions(ctx, mode)
    lines += _section_output_template(ctx, mode)
    lines.append("Begin.")
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=ALL_MODES,
        required=True,
        help="Which prompt flavor to build.",
    )
    args = parser.parse_args()

    ctx = _load_context(args.mode)
    lines = _build_prompt(ctx, args.mode)
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())

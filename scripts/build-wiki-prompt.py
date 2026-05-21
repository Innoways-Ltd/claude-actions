#!/usr/bin/env python3
"""Build the Claude prompt for a WIKI question (read-only Q&A).

Reads /tmp/claude-job/issue.json (output of `gh issue view --json
title,body,comments`) and prints a markdown prompt to stdout.

Wiki mode is read-only: Claude searches docs/ first, falls back to source
code, and replies with an explanation plus at least one Mermaid flowchart.
The workflow extracts the `## Answer` section and posts it as a comment.

Required env:
  WORKSPACE_ROOT             absolute path to the parent dir on the runner
  SUBPROJECTS                space-separated subproject dir names
  SUBPROJECT_DESCRIPTIONS    multiline markdown bullets, one per subproject
  REPO_FULL                  GitHub repo (owner/name)
  ISSUE_NUMBER               GitHub issue number

Optional env:
  DOCS_PATH                  subdir under WORKSPACE_ROOT (e.g. "docs"); empty = skip
  GITNEXUS_REPOS             space-separated repo names indexed in GitNexus;
                             defaults to SUBPROJECTS. Set to "" to omit the
                             GitNexus section entirely.
"""
import json
import os
import sys


def env_required(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        print(f"build-wiki-prompt.py: missing required env var {name}", file=sys.stderr)
        sys.exit(2)
    return val


def list_docs(docs_dir: str) -> list[str]:
    try:
        return sorted(f for f in os.listdir(docs_dir) if f.endswith(".md"))
    except (FileNotFoundError, OSError):
        return []


def main() -> int:
    issue_path = "/tmp/claude-job/issue.json"
    if not os.path.exists(issue_path):
        print(f"Missing {issue_path}", file=sys.stderr)
        return 1

    workspace_root = env_required("WORKSPACE_ROOT")
    subprojects = env_required("SUBPROJECTS").split()
    subproject_descriptions = env_required("SUBPROJECT_DESCRIPTIONS").rstrip()
    repo = env_required("REPO_FULL")
    issue_num = env_required("ISSUE_NUMBER")

    docs_subpath = os.environ.get("DOCS_PATH", "").strip()
    docs_dir = os.path.join(workspace_root, docs_subpath) if docs_subpath else ""

    # GITNEXUS_REPOS defaults to SUBPROJECTS. An explicit empty value disables
    # the GitNexus section so projects without an index don't see it suggested.
    raw_gitnexus = os.environ.get("GITNEXUS_REPOS")
    if raw_gitnexus is None:
        gitnexus_repos = subprojects
    else:
        gitnexus_repos = raw_gitnexus.split()

    data = json.load(open(issue_path))

    lines: list[str] = []
    lines.append(f"# Wiki question: {data.get('title','(no title)')}")
    lines.append("")
    lines.append(f"Source: {repo}#{issue_num}")
    lines.append("")
    lines.append("## Workspace (read-only references)")
    lines.append("")
    lines.append(
        f"You are running in `{workspace_root}/`. The following are "
        "available for **reading only** — do not modify any file:"
    )
    lines.append("")
    if docs_dir:
        lines.append(f"- `{docs_subpath}/` — Project documentation (index below)")
    lines.append(subproject_descriptions)
    lines.append("")

    if docs_dir:
        lines.append(f"## {docs_subpath}/ index")
        lines.append("")
        lines.append(
            "Always start here. Each file documents one module's domain rules, "
            "state machines and side effects. The numeric prefix is the suggested "
            "reading order."
        )
        lines.append("")
        for name in list_docs(docs_dir):
            lines.append(f"- `{docs_subpath}/{name}`")
        lines.append("")

    if gitnexus_repos:
        lines.append("## Code intelligence (GitNexus MCP — preferred)")
        lines.append("")
        lines.append(
            "A pre-indexed code graph is available via `mcp__gitnexus__*` tools. "
            "It is incrementally refreshed every 4 hours, so use it **before** "
            "falling back to Read/Grep on the source tree."
        )
        lines.append("")
        if len(gitnexus_repos) > 1:
            lines.append(
                "Multiple repos are indexed separately. Pass the matching `repo` argument:"
            )
        else:
            lines.append(
                "The repo is indexed under the `repo` argument shown below:"
            )
        lines.append("")
        for r in gitnexus_repos:
            lines.append(f"- `repo: \"{r}\"`")
        lines.append("")
        lines.append(
            "Use these tools **internally to find and verify** the answer — "
            "but **do not surface code paths, function names, or file references "
            "in the final answer**. They are for your reasoning, not for the "
            "reader (see Instructions §2 below)."
        )
        lines.append("")
        lines.append(
            "- `mcp__gitnexus__query({query, repo})` — semantic + symbol search; "
            "faster and more precise than Grep for \"where is X defined / used\"."
        )
        lines.append(
            "- `mcp__gitnexus__context({name, repo})` — 360° view of a symbol: "
            "incoming/outgoing calls, cluster membership, traced processes."
        )
        lines.append(
            "- `mcp__gitnexus__impact({target, repo})` — blast-radius / "
            "dependency tree (read-only; useful for \"what depends on X\")."
        )
        lines.append(
            "- `mcp__gitnexus__cypher({query, repo})` — raw graph queries when "
            "the above are too coarse."
        )
        lines.append("")
        if len(gitnexus_repos) > 1:
            lines.append(
                "If a question spans multiple repos (e.g. an API contract), query each "
                "in turn and synthesise the *business behaviour* — never paste "
                "code paths into the answer."
            )
            lines.append("")
        lines.append(
            "**Fallback policy:** if any gitnexus tool errors, returns nothing, "
            "or the index looks stale, fall back silently to Read/Grep. Do not "
            "surface MCP errors in the final answer to the user."
        )
        lines.append("")

    lines.append("## Question")
    lines.append("")
    lines.append(data.get("body") or "(empty)")

    for c in data.get("comments") or []:
        author = (c.get("author") or {}).get("login", "?")
        created = c.get("createdAt", "")
        body = c.get("body") or ""
        lines.append("")
        lines.append(f"## Comment by @{author} ({created})")
        lines.append("")
        lines.append(body)

    lines.append("")
    lines.append("## Instructions")
    lines.append("")
    lines.append(
        "**Audience:** the reader is a tester / business user / project "
        "manager — assume they cannot read code. Your job is to explain "
        "**what the system does, when, and why**, in plain language."
    )
    lines.append("")
    if docs_dir:
        lines.append(
            f"1. **Research thoroughly, then translate to business language.** "
            f"Read `{docs_subpath}/` first (numeric prefix = suggested order), then use "
            "GitNexus MCP tools and Read/Grep to verify your understanding. "
            "These are for *your* reasoning — the reader never sees them."
        )
    else:
        lines.append(
            "1. **Research thoroughly, then translate to business language.** "
            "Use GitNexus MCP tools and Read/Grep to verify your understanding. "
            "These are for *your* reasoning — the reader never sees them."
        )
    lines.append(
        "2. **Do NOT include code paths, file names, function names, "
        "endpoint URLs, class/variable names, or `path:line` references "
        "in the answer.** No doc references either. The wiki answer is for "
        "non-engineers. If a tester needs the code, an engineer will dig."
    )
    lines.append(
        "3. **Avoid jargon. When you must use a domain term, explain it "
        "once in plain language right after first use.** "
        "Banned without explanation: \"controller\", \"endpoint\", "
        "\"middleware\", \"state machine\", \"hook\", \"action\", "
        "\"reducer\", \"store\", \"validator\", \"DTO\", \"schema\", "
        "\"migration\", \"transaction\", \"audit log\", error class names "
        "(e.g. `InvalidTransitionError`), HTTP verbs / status codes. "
        "Replace with what the user observes: \"按下按钮 / 系统检查 / "
        "状态更新 / 弹出错误提示 / 列表刷新\"."
    )
    lines.append(
        "4. **Reply in the same language as the question** (中文问 → "
        "中文答; English question → English answer)."
    )
    lines.append(
        "5. **Include at least one Mermaid diagram** (`flowchart`, "
        "`sequenceDiagram`, `stateDiagram-v2`, or `erDiagram` — pick the "
        "best fit). **Boxes and edge labels must use business words, not "
        "function names or HTTP routes.** Example: `点击关闭按钮` ✓, "
        "`POST /api/case/:id/close` ✗."
    )
    lines.append(
        "6. **Do NOT modify any files.** This is a Q&A, not a code change. "
        "Read + Grep + GitNexus MCP only."
    )
    lines.append(
        "7. **Do NOT commit, push, or open MRs.** The workflow only posts "
        "your answer as an issue comment."
    )
    lines.append(
        "8. **Output a `## Answer` section at the very end of your "
        "response.** The workflow extracts everything from `## Answer` to "
        "the end of output and posts it as the GitHub issue comment. "
        "Structure your Answer like this:"
    )
    lines.append("")
    lines.append("   ## Answer")
    lines.append("")
    lines.append(
        "   **结论 / Bottom line:** <one short sentence, plain language>"
    )
    lines.append("")
    lines.append("   **会发生什么 / What happens:**")
    lines.append("")
    lines.append("   1. <user-visible step in business language>")
    lines.append("   2. <next step…>")
    lines.append("   3. <…>")
    lines.append("")
    lines.append("   ```mermaid")
    lines.append("   flowchart TD")
    lines.append("       A[用户做了什么] --> B{系统判断什么}")
    lines.append("       B -->|条件 1| C[结果 1]")
    lines.append("       B -->|条件 2| D[结果 2]")
    lines.append("   ```")
    lines.append("")
    lines.append(
        "   **名词解释 / Terminology** *(only include this subsection if "
        "you actually used a domain term that needs explaining)*:"
    )
    lines.append("")
    lines.append(
        "   - **\"<术语>\"**: <一句话用大白话解释>"
    )
    lines.append("")
    lines.append(
        "   The heading `## Answer` must stay exactly as-is so the "
        "extractor finds it. The subsections above are the recommended "
        "shape — feel free to add an example scenario or a short "
        "\"为什么会这样设计\" note if it helps the reader, but never "
        "add file paths or code references."
    )
    lines.append("")
    lines.append("Begin.")

    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())

# claude-actions

Reusable GitHub Actions workflow that powers the `@claude` issue bot across every
Innoways project. Caller repos open issues; this workflow runs `claude -p` on the
admin's self-hosted runner against local clones of the project's code repos and
opens GitLab MRs (fix mode) or posts a wiki-style answer (wiki mode).

## Architecture

- One self-hosted runner pool labeled `claude-bot` serves every project.
- Each `*-issue` repo (the GitHub-side issue tracker) has a thin `claude.yml`
  that calls this workflow with project-specific inputs.
- Per-project concurrency groups (computed from `project_name`) serialize
  same-project jobs (avoiding clone races) while letting different projects
  run in parallel up to the pool size.
- This repo is **private**. Since the caller's `GITHUB_TOKEN` cannot read
  across private-repo boundaries (and `internal` visibility is not available
  on the org's free plan), the reusable workflow does **not** use
  `actions/checkout` for its own scripts. Instead, the runner keeps a
  persistent mirror at `/home/user6/claude-actions/` that is `git fetch`+
  `git reset --hard` synced under a `flock` at the start of every job.

## One-time runner setup

On every machine where the `claude-bot` runner runs:

```bash
git clone --branch deployment https://github.com/Innoways-Ltd/claude-actions.git /home/user6/claude-actions
```

The first step of every job (`Sync runner-local claude-actions mirror`)
verifies this exists, otherwise it fails fast with instructions. The flock
at `/tmp/claude-actions-mirror.lock` serializes mirror updates across the
runner pool so concurrent jobs across projects can't race on the same
checkout.

## Onboarding a new project (3 steps)

### 1. Clone the project's code repos on the runner machine

```bash
mkdir -p /home/user6/innoways-project/<project>
cd       /home/user6/innoways-project/<project>
git clone <gitlab-remote-1>   # e.g. <project>-api
git clone <gitlab-remote-2>   # e.g. <project>-web
# ... one clone per subproject
```

The clones must be runner-only — no human edits, the workflow does
`git reset --hard origin/<branch>` at the start of every run.

### 2. Create the `<project>-issue` repo on GitHub

This is where testers open issues. Add the issue templates you want
(`bug-report.yml`, optionally `wiki-question.yml`) under
`.github/ISSUE_TEMPLATE/`.

### 3. Add a thin `claude.yml` to the issue repo

```yaml
# .github/workflows/claude.yml
name: Claude
on:
  issues:
    types: [opened, edited]
  issue_comment:
    types: [created]

permissions:
  issues: write
  contents: read

jobs:
  claude:
    uses: Innoways-Ltd/claude-actions/.github/workflows/claude.yml@main
    with:
      project_name: <project>
      subprojects: "<sub-1> <sub-2> <sub-3>"
      project_overview: |
        One-paragraph description of what this project does and how the
        subprojects relate. Goes verbatim into Claude's prompt.
      subproject_descriptions: |
        - `<sub-1>/` — Koa/Express backend (controllers/, routes/, model/)
        - `<sub-2>/` — React frontend (src/)
        - `<sub-3>/` — Admin panel (src/)
      # Optional inputs (all defaults shown):
      # workspace_root: ''                # default: /home/user6/innoways-project/<project_name>
      # docs_path: ''                     # e.g. 'docs' if the project has a docs/ folder
      # docs_inline: ''                   # e.g. 'README.md 00-architecture.md'
      # gitlab_target_branch: dev
      # git_clean_exclude: ''             # e.g. '.gitnexus' to preserve the GitNexus index
      # target_prefix: ''                 # e.g. 'membership-' if templates use short names
      # enable_wiki_mode: true            # set false if the repo has no wiki template
      # wiki_timeout_seconds: 1200
      # bug_timeout_seconds: 1800
      # post_merge_notice: ''             # e.g. 'Will deploy to dev ~20 minutes after merge.'
      # gitnexus_repos: ''                # default: same as subprojects; ' ' (space) = disable
      # claude_actions_ref: main          # pin to a tag for stability if desired
    secrets: inherit
```

## Inputs reference

| Input | Required | Default | Purpose |
|---|---|---|---|
| `project_name` | ✓ | — | Concurrency group + metrics label |
| `subprojects` | ✓ | — | Space-separated full directory names |
| `project_overview` | ✓ | — | Plain text into Claude's "Workspace layout" section |
| `subproject_descriptions` | ✓ | — | Markdown bullets, one per subproject |
| `workspace_root` | | `/home/user6/innoways-project/<project_name>` | Override only if cloned elsewhere |
| `docs_path` | | (empty) | Subdir of read-only docs; empty → no docs section |
| `docs_inline` | | (empty) | Doc filenames to inline in the bug prompt (prompt caching) |
| `gitlab_target_branch` | | `dev` | MR target |
| `git_clean_exclude` | | (empty) | Pattern passed to `git clean -e` |
| `target_prefix` | | (empty) | Add to / strip from Target Project body values (short-name UX) |
| `enable_wiki_mode` | | `true` | Set false for fix-only projects |
| `wiki_timeout_seconds` | | `1200` | Hard timeout on wiki claude runs |
| `bug_timeout_seconds` | | `1800` | Hard timeout on fix claude runs |
| `post_merge_notice` | | (empty) | One-line text appended to MR-opened issue comment |
| `gitnexus_repos` | | same as subprojects | Repos to mention in wiki prompt's GitNexus section; one space = disable |
| `claude_actions_ref` | | `main` | Ref of this repo to check out for scripts |

## Scripts

All scripts live under `scripts/` and read project context from environment
variables (set by the reusable workflow):

| Script | Purpose |
|---|---|
| `build-bug-prompt.py` | Builds the fix-mode prompt (workspace layout + issue body + instructions) |
| `build-wiki-prompt.py` | Builds the wiki-mode prompt (read-only + Mermaid output spec) |
| `extract-summary.py` | Extracts the `## Summary` (or `## Answer`) section from Claude's output |
| `post-result.sh` | Renders GitHub comment / GitLab MR bodies for each terminal state |
| `set-issue-label.sh` | Sets a single `claude:*` status label on the source issue |

## Sensitive paths (security-fixed, not per-project)

The fix-mode post-check refuses to commit any of the following — keep them
in sync with `build-bug-prompt.py` instruction #4:

- `*.env*`, `secrets/**`, `.github/**`, `.gitlab/**`, `.gitlab-ci.yml`
- `**/migrations/**`, `schema/**`
- `controllers/auth/**`, `middleware/auth/**`, `action/login/**`, any `**/auth/**`
- `package.json` `dependencies` field changes

These apply uniformly to every project; they are not configurable.

## Releasing changes

Default ref is `@main`. To pin a caller to a tagged version, pass
`claude_actions_ref: vX.Y.Z` *and* change the `uses:` line accordingly.

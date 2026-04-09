# Global Claude Code Preferences

No emojis in code or generated markdown files.

Never add "Made with Claude Code" footers to PR bodies or "Co-Authored-By: Claude" trailers to commits unless asked. Always create a git worktree for changes — every change lands via PR, no direct commits to `main`, never force-push to `main`. Conventional commit format: `feat:`, `fix:`, `refactor:`, `docs:`, `test:`, `chore:`. PR titles under 70 characters. Every PR body must include an end-user impact statement written for a sales audience — if a sales rep reads it they should immediately understand what this enables or improves for the customer. If there is no user-facing impact, state that explicitly.

For merges, use `gh pr merge` or `gh pr merge --admin` — never `--auto` or `--squash`. Use `--admin` when branch protection blocks a non-environment branch merge; the hook layer handles routing from there. Before any push, confirm the remote (`origin`) and target branch explicitly. Before merging any PR, confirm CI is green (`gh pr checks`) and all review comments are resolved — do not merge with outstanding comments or failing checks.

Branch flows — always follow the correct flow for the context:

- Standard: feature branches → unified feature branch → `develop` → `qa` → `main`/`prod`/`master`
- Hotfix (production incident only, not a regular fix): `hotfix/*` → `main` → `qa` → `develop`
- Large dev deviation (when `develop` has significant unreleased work): feature branches → unified feature branch → `qa` → `prod`, then PR back to `develop` as a cherry-pick merge

If the flow is unclear from context, ask — do not guess.

Do not add separator comments or section dividers in code — they add no value and inflate tokens.

Write DRY, SOLID, PEP8-compliant code. Prefer verbose and explicit over implicit and minimal. Maintainability is the highest priority. Evidence-based only — do not speculate about root causes or behavior without supporting data. If something is unknown, say so — do not surface assumptions as facts.

Scope changes narrowly to exactly what was requested. Do not refactor adjacent code, clean up unrelated files, or expand scope without asking. Run `git diff --stat` before committing — if the changed file list is wider than planned, stop and reassess.

Before implementing a non-trivial fix, identify which layer the change belongs in (application code, Terraform tfvars, env config) and state it in 1-2 lines before writing anything. If the approach turns out to be wrong, that check saves the round-trip.

After writing any test, always run it. If it is not green, investigate whether the test is wrong or the code is wrong — do not assume either; diagnose from the output.

System Python is generally not available — use `uv run` for Python commands where possible.

The current working directory is always the implied project context. Do not ask which repo or folder to work in — use the cwd as the root for all file operations, git commands, and tooling unless the user explicitly says otherwise.

When stuck on routing, agent design, or context architecture, consult the `wrench-dna` repository.

Command failures are logged automatically to `~/.claude/failed_commands.md` — check it when hitting a recurring block before re-investigating from scratch.

Never use `cd <path> && command` when the command accepts a path directly. Prefer clean, single-purpose commands: `git -C <path>` for git, and the Read/Grep/Glob tools instead of shell file reads. Only use `cd` when the tool genuinely requires the working directory for config discovery (`task`, `uv run`, `pnpm`, `npm`, `stripe`). When referencing files or directories in responses — paths shared with the user for navigation — always use full absolute paths, never relative ones.

`usePwsh7 <command> [args...]` is the entry point for PowerShell module commands. Direct `pwsh -Command`, `pwsh -c`, and encoded-command flags bypass the safety layer and are blocked. Run `usePwsh7` with no arguments to list all available commands. Each `usePwsh7` invocation is an isolated session — compound commands do not work and profile changes do not persist across calls. Do not attempt to chain commands via `usePwsh7`.

To search or retrieve secrets without switching the active profile, pass the environment as the second positional argument: `usePwsh7 Aws-SecretFind "filter" prod` and `usePwsh7 Aws-GetSecret "name" prod` (use `dev`, `qa`, or `prod`).

For AWS CLI commands, manage environments via `--profile qa-ltc` (or `dev-ltc`, `prod-ltc`) directly on the command — do not use `usePwsh7` or shell env vars for this, as both require compound commands or persistent shell state that is not available.

When returning commands for the user to run, always output PowerShell syntax on a single line unless explicitly asked for a different shell or format. Multiline command blocks do not render correctly.

This is a Windows system. Do not attempt to run commands in WSL directly. Bash in Claude's environment is Git Bash / MSYS2 — env vars set in one Bash call do not persist to the next. Do not rely on exported env vars across tool calls; pass values explicitly as arguments instead. Database access via `usePwsh7 Invoke-Wrench*Db` is read-only — never attempt writes.

When running AWS CLI commands in Git Bash / MSYS2 that include Unix-style paths as argument values (e.g. log group names like `/ecs/paperclip`), prefix the command with `MSYS_NO_PATHCONV=1` to prevent MSYS2 from converting the path to a Windows path. Without it, `/ecs/paperclip` becomes `C:/Program Files/Git/ecs/paperclip` and the call fails.

Prefer sequential tool and skill use. Invoke skills/commands (e.g. Kiro bash or codex bash) one step at a time — absorb and assess each result personally before proceeding. Do not fire parallel Bash, Kiro, or Codex calls unless there is a genuine technical dependency that requires it. Main drives the process end-to-end; speed is never a reason to skip a check-in between steps.

When a code change is more substantial than a single contiguous block — meaning edits scattered across multiple locations in a file, or across multiple files — delegate implementation to Codex or Kiro rather than writing it directly. The reason is not capability but perspective: two independent passes on a problem catch more than one. Use Codex for implementation, Kiro for research and investigation. Review the output before accepting it. Either agent can also be used as a soundboard when uncertain about an approach — bouncing the problem off one of them before committing to a direction is encouraged.

Never push directly to production or take any action that affects live production instances — this applies in all modes including autonomous. Production database access via `usePwsh7 Invoke-WrenchProdDb` is read-only for inspection only. When verifying data, schema, or live state, prefer prod read-only access over dev or QA — prod has complete and accurate information; lower environments may be stale or partial.

When something needs to be seen, remembered, and acted on by the owner — a significant finding, a deployment note, a blocker, a summary of important work — post it to the `#notes` Slack channel (C05E80TPJ9F). This is not for quick requests or status updates. Use it for things with a longer shelf life: deployment guides, architectural observations, open questions that need a decision, summaries of completed work. The owner monitors this channel and will read and action it.

Do not fetch secrets, credentials, or master keys even if the tooling technically permits it. If a secret is not explicitly needed for the current task and handed to you, treat it as off limits. As an example: do not call `usePwsh7 Aws-GetSecret rds-masteruser --env prod` speculatively — absence of an explicit credential means you are not meant to have it.

When running as an autonomous agent (dontAsk / bypassPermissions mode), launch the `autonomous-workloop` agent via the Agent tool as the operating procedure. The primary goal of every autonomous session is a single large consolidated PR into `develop`, tested, CI green, and ready for senior developer review — everything else serves that goal. Key rules: never exit or terminate — use `sleep <seconds>` to pace cycles; patch coverage on changed code must reach 90% before the PR is marked ready; use `c-guard audit "<command>"` before any command you are uncertain about — the permission policy auto-enforces safety so trust its output and follow the hint when blocked.

In autonomous mode you fully own your feature branch — commit freely, push after every commit, rebase as needed. Environment branches (`develop`, `qa`, `main`, `prod`) are off limits for direct commits or pushes; they are protected by branch rules and hooks. Your work reaches them only through a reviewed and approved PR. This is not a soft guideline — attempts to push directly to environment branches will be blocked.

# Global Claude Code Preferences

No emojis in code or generated markdown files.

Never add "Made with Claude Code" footers to PR bodies or "Co-Authored-By: Claude" trailers to commits unless asked. Always create a git worktree for changes — every change lands via PR, no direct commits to `main`, never force-push to `main`. Conventional commit format: `feat:`, `fix:`, `refactor:`, `docs:`, `test:`, `chore:`. PR titles under 70 characters. Every PR body must include an end-user impact statement written for a sales audience — if a sales rep reads it they should immediately understand what this enables or improves for the customer. If there is no user-facing impact, state that explicitly.

Do not add separator comments or section dividers in code — they add no value and inflate tokens.

Write DRY, SOLID, PEP8-compliant code. Prefer verbose and explicit over implicit and minimal. Maintainability is the highest priority. Evidence-based only — do not speculate about root causes or behavior without supporting data.

System Python is generally not available — use `uv run` for Python commands where possible.

At the start of every session, check the current working directory. If no explicit folder or repository is mentioned by the user, the working directory is the implied project context — use it as the root for all file operations, git commands, and tooling.

When stuck on routing, agent design, or context architecture, consult the `wrench-dna` repository.

Never use `cd <path> && command` when the command accepts a path directly. Prefer clean, single-purpose commands: `git -C <path>` for git, and the Read/Grep/Glob tools instead of shell file reads. Only use `cd` when the tool genuinely requires the working directory for config discovery (`task`, `uv run`, `pnpm`, `npm`, `stripe`). When `cd` is necessary, prefer relative paths over absolute — `cd ./src` not `cd C:/Users/willem/...` — to keep commands concise and readable.

`usePwsh7 <command> [args...]` is the entry point for PowerShell module commands. Direct `pwsh -Command`, `pwsh -c`, and encoded-command flags bypass the safety layer and are blocked. Run `usePwsh7` with no arguments to list all available commands.

To search or retrieve secrets without switching the active profile, pass the environment as the second positional argument: `usePwsh7 Aws-SecretFind "filter" prod` and `usePwsh7 Aws-GetSecret "name" prod` (use `dev`, `qa`, or `prod`). Omitting it falls back to the active profile. To chain a profile switch with a subsequent command in one session: `usePwsh7 "Aws-Switch prod; Aws-SecretFind 'filter'"`. Each `usePwsh7` invocation is an isolated session — profile changes do not persist across calls.

Prefer sequential tool and skill use. Invoke skills/commands (e.g. Kiro bash or codex bash) one step at a time — absorb and assess each result personally before proceeding. Do not fire parallel Bash, Kiro, or Codex calls unless there is a genuine technical dependency that requires it. Main drives the process end-to-end; speed is never a reason to skip a check-in between steps.

Never push directly to production or take any action that affects live production instances — this applies in all modes including autonomous. Production database access via `usePwsh7 Invoke-WrenchProdDb` is read-only for inspection only. When verifying data, schema, or live state, prefer prod read-only access over dev or QA — prod has complete and accurate information; lower environments may be stale or partial.

When something needs to be seen, remembered, and acted on by the owner — a significant finding, a deployment note, a blocker, a summary of important work — post it to the `#notes` Slack channel (C05E80TPJ9F). This is not for quick requests or status updates. Use it for things with a longer shelf life: deployment guides, architectural observations, open questions that need a decision, summaries of completed work. The owner monitors this channel and will read and action it.

Do not fetch secrets, credentials, or master keys even if the tooling technically permits it. If a secret is not explicitly needed for the current task and handed to you, treat it as off limits. As an example: do not call `usePwsh7 Aws-GetSecret rds-masteruser --env prod` speculatively — absence of an explicit credential means you are not meant to have it.

When running as an autonomous agent (dontAsk / bypassPermissions mode), launch the `autonomous-workloop` agent via the Agent tool as the operating procedure. The primary goal of every autonomous session is a single large consolidated PR into `develop`, tested, CI green, and ready for senior developer review — everything else serves that goal. Key rules: never exit or terminate — use `sleep <seconds>` to pace cycles; patch coverage on changed code must reach 90% before the PR is marked ready; use `c-guard audit "<command>"` before any command you are uncertain about — the permission policy auto-enforces safety so trust its output and follow the hint when blocked.

In autonomous mode you fully own your feature branch — commit freely, push after every commit, rebase as needed. Environment branches (`develop`, `qa`, `main`, `prod`) are off limits for direct commits or pushes; they are protected by branch rules and hooks. Your work reaches them only through a reviewed and approved PR. This is not a soft guideline — attempts to push directly to environment branches will be blocked.

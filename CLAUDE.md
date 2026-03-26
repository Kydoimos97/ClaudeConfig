# Global Claude Code Preferences

No emojis in code or generated markdown files.

Never add "Made with Claude Code" footers to PR bodies or "Co-Authored-By: Claude" trailers to commits unless asked. Always create a git worktree for changes — every change lands via PR, no direct commits to `main`, never force-push to `main`. Conventional commit format: `feat:`, `fix:`, `refactor:`, `docs:`, `test:`, `chore:`. PR titles under 70 characters. Every PR body must include an end-user impact statement written for a sales audience — if a sales rep reads it they should immediately understand what this enables or improves for the customer. If there is no user-facing impact, state that explicitly.

Do not add separator comments or section dividers in code — they add no value and inflate tokens.

Write DRY, SOLID, PEP8-compliant code. Prefer verbose and explicit over implicit and minimal. Maintainability is the highest priority. Evidence-based only — do not speculate about root causes or behavior without supporting data.

System Python is generally not available — use `uv run` for Python commands where possible.

When stuck on routing, agent design, or context architecture, consult the `wrench-dna` repository.

Never use `cd <path> && command` when the command accepts a path directly. Prefer clean, single-purpose commands: `git -C <path>` for git, absolute paths for `grep`/`cat`/`sed`/`ls`, and the Read/Grep/Glob tools instead of shell file reads. Only use `cd` when the tool genuinely requires the working directory for config discovery (`task`, `uv run`, `pnpm`, `npm`, `stripe`).

`c-guard` is available to non-interactively check how a command will be evaluated before running it. Use `c-guard audit "command"` when unsure whether a command will be allowed, denied, or require confirmation — and use `--mode dontAsk` or `--mode bypassPermissions` to simulate the relevant execution mode. The shim auto-detects non-tty output and disables color; pass `--no-color` explicitly if capturing output in a subshell. Prefer this over guessing or trying alternative command forms blindly. Run `c-guard` with no arguments to see full help.

`usePwsh7` is the correct entry point for running PowerShell module commands. It loads all modules from `C:\Bin\cli\PsModules` non-interactively, reads each function's `LLM_MODE` tag, hides and blocks `-` tagged functions, and surfaces `+`/`~` tagged ones. Usage: `usePwsh7 <command> [args...]`. Run `usePwsh7` with no arguments to list all available commands with their safety icons. Direct `pwsh -Command`, `pwsh -c`, and encoded-command flags bypass this safety layer and are blocked by policy — always use `usePwsh7` instead.

To search or retrieve secrets across AWS accounts without switching the active profile, use the `-Env` parameter: `usePwsh7 Aws-SecretFind "filter" dev|qa|prod` and `usePwsh7 Aws-GetSecret "name-or-arn" dev|qa|prod`. Omitting `-Env` falls back to the active profile. To chain a profile switch with a subsequent command in the same session, run them as a single semicolon-separated string: `usePwsh7 "Aws-Switch prod; Aws-SecretFind 'filter'"`. Each separate `usePwsh7` invocation is an isolated session — profile changes do not persist across calls.

Prefer sequential tool and skill use. Invoke skills/commands (e.g. Kiro bash or codex bash) one step at a time — absorb and assess each result personally before proceeding. Do not fire parallel Bash, Kiro, or Codex calls unless there is a genuine technical dependency that requires it. Main drives the process end-to-end; speed is never a reason to skip a check-in between steps.

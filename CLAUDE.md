# Global Claude Code Preferences

No emojis in code or generated markdown files.

Never add "Made with Claude Code" footers to PR bodies or "Co-Authored-By: Claude" trailers to commits unless asked. Always create a git worktree for changes — every change lands via PR, no direct commits to `main`, never force-push to `main`. Conventional commit format: `feat:`, `fix:`, `refactor:`, `docs:`, `test:`, `chore:`. PR titles under 70 characters. Every PR body must include an end-user impact statement written for a sales audience — if a sales rep reads it they should immediately understand what this enables or improves for the customer. If there is no user-facing impact, state that explicitly.

Do not add separator comments or section dividers in code — they add no value and inflate tokens.

Write DRY, SOLID, PEP8-compliant code. Prefer verbose and explicit over implicit and minimal. Maintainability is the highest priority. Evidence-based only — do not speculate about root causes or behavior without supporting data.

System Python is generally not available — use `uv run` for Python commands where possible.

When stuck on routing, agent design, or context architecture, consult the `wrench-dna` repository.

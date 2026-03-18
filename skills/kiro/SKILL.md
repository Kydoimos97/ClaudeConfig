---
name: kiro
description: >
  Kiro runs in WSL with internet access and read permissions across the
  filesystem. Use it for anything requiring research, web fetch, file
  exploration, or triage of output files. It cannot invoke build tools or
  mutate files.
---

# Kiro

Invoke kiro-cli for research, exploration, and triage. Kiro runs inside WSL
(Ubuntu) and has read access to the Windows filesystem via /mnt/c/.

## Invocation

```bash
wsl -d Ubuntu bash -lc "kiro-cli chat --no-interactive --trust-all-tools \"<fully scoped prompt>\""
```

`--trust-all-tools` is required — without it Kiro will prompt for approval and
hang. The prompt must be fully self-contained: role, exact goal, output format,
and explicit instruction not to dump raw content.

Always pass a timeout to the Bash tool when invoking kiro-cli — it can hang
indefinitely if the model loops or stalls. Recommended: `timeout: 120000`
(2 minutes) for fetch/triage, `timeout: 180000` (3 minutes) for discovery or
research. If the command times out, check whether output was partially written
before retrying.

## Capabilities and limits

Kiro CAN:
- Read any file on Windows drives via `/mnt/c/`, `/mnt/d/` etc. (live confirmed)
- Run web searches and fetch URLs
- grep, glob, ls, stat within any path
- Run read-only git commands against Windows repos — use WSL-native `git` with:
  `env GIT_DISCOVERY_ACROSS_FILESYSTEM=1 git -C /mnt/c/<repo-path> <subcommand>`
  (live confirmed: log, diff, branch, show all work)
- Run read-only `gh.exe` lookups — PR list/view/checks, issue list/view, repo view,
  run list/view, release list/view. Full path: `/mnt/c/Program Files/GitHub CLI/gh.exe`
  or just `gh.exe` if on PATH. (allowedCommands configured)

Kiro CANNOT:
- Write to Windows drives (`/mnt/[a-z]/` writes are denied by sandbox)
- Run `task`, `uv`, `pytest`, `uv run puppy`, or any build/test tooling
- Run `git.exe` — Windows git binary cannot interpret `/mnt/c/` paths (use WSL git)
- Run any `gh.exe` command that mutates state (create, merge, close, edit)
- Execute anything that mutates state

For execution tasks (puppy, gh writes, uv), main runs them directly via Bash.

## Quirks

- Kiro runs in WSL Ubuntu. The working directory for shell commands defaults
  to the WSL home (`~`). Always pass full `/mnt/c/...` paths when referencing
  project files, or `-C /mnt/c/...` for git commands.
- Git requires `GIT_DISCOVERY_ACROSS_FILESYSTEM=1` to cross the WSL/Windows mount
  boundary — always prefix git commands with `env GIT_DISCOVERY_ACROSS_FILESYSTEM=1`.
- `git.exe` is reachable at `/mnt/c/Program Files/Git/mingw64/bin/git.exe` but
  cannot handle `/mnt/c/` paths — use WSL-native `git` exclusively.
- `gh.exe` is at `/mnt/c/Program Files/GitHub CLI/gh.exe` and is on the WSL PATH.
- The `--trust-all-tools` flag is not a security bypass — Kiro's sandbox
  already enforces the allow/deny lists in `~/.kiro/agents/default.json`.
- Web search results are Kiro's own model output — verify facts against known
  context before acting on them.

## Task types

Choose the task type that matches the work.

---

### Fetch

Use for: web search, docs lookup, curl, API inspection, external information gathering.

Prompt must include: what source to inspect, what facts to extract, whether recency matters.

Output contract:

## Findings
- fact

## Sources
- source

## Commands fired
<count>

## Relevance
<one paragraph>

## Concerns
<omit if none>

---

### Triage

Use for: pytest failures, CI logs, Ruff/Ty output, Terraform plans, Datadog/ECS/application logs, long command output.

Prompt must include: the raw input category, instruction to collapse duplicates, instruction to identify likely root cause.

Output contract:

## Triage Summary
Primary issue: <one line>

## Findings
1. issue
2. issue

## Likely cause
<short paragraph>

## Commands fired
<count>

## Concerns
<omit if none>

---

### Discovery

Use for: finding symbol definitions, tracing call paths, identifying entry points, mapping module relationships.

Prompt must include: target symbol or subsystem, desired outputs (definitions, usages, entry points), instruction to avoid full file dumps.

Output contract:

## Discovery
Target: <symbol or topic>

## Definitions
- path:line

## Key usages
- path:line

## Related modules
- module

## Commands fired
<count>

## Relevance
<one paragraph>

## Concerns
<omit if none>

---

### PR Draft

Use for: PR summary from a branch, commit range, or diff. Returns a draft for main to finalize.

Prompt must include: branch or diff scope, instruction to group changes by theme, instruction to stay factual.

Output contract:

## Summary
<short paragraph>

## Key Changes
- item

## Testing
- item

## Impact
<short paragraph>

## What this enables
<short paragraph>

---

### Research

Use for: architecture understanding, framework/library research, large-context subsystem analysis.

Prompt must include: the question to answer, required constraints, instruction to distinguish confirmed facts from inference.

Output contract:

## Research Findings
- fact

## Constraints
- item

## Commands fired
<count>

## Relevance
<short paragraph>

## Concerns
<omit if none>

---

## Rules

- Prompts must be fully self-contained — no vague instructions like "look this up"
- Never dump raw HTML, JSON, logs, or full file contents
- Preserve exact paths, symbols, URLs, error messages, and test names when relevant
- Group duplicate issues
- Distinguish facts from inference
- If kiro-cli fails, report the failure and stop — do not retry silently

## Verification

Kiro is an external tool running a different LLM with different context.
Its output is volatile — treat all findings as input to main's judgment,
not as ground truth. Always verify before acting:
- Cross-check facts against known context
- Flag anything that contradicts what main already knows
- Never apply Kiro output blindly

## Second opinion

Kiro can be invoked for a second opinion on design decisions or approaches.
Because it runs a different model with independent context, its view is
genuinely independent. Useful for:
- Validating an implementation approach before committing
- Checking whether a design has obvious gaps
- Getting an alternative read on a tradeoff

Frame the question clearly. Treat the response as one input among several,
not a final verdict.

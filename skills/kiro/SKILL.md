---
name: kiro
description: >
  Kiro runs in WSL with internet access and read permissions across the
  filesystem. Conductor's only research tool — use for anything requiring
  exploration, web fetch, file reading, or triage of output files. Kiro
  cannot write files or run build tools.
---

# Kiro

Conductor delegates all research, exploration, and triage to Kiro.
Kiro runs inside WSL (Ubuntu) with read access to Windows via /mnt/c/.

## Invocation

```bash
kiro-cli chat --no-interactive --trust-all-tools "<fully scoped prompt>"
```

`kiro-cli` is available as a bash shim at `C:\Bin\kiro-cli` — call directly.

`--trust-all-tools` is required — without it Kiro prompts for approval and
hangs. The prompt must be fully self-contained: role, exact goal, output
format, and explicit instruction not to dump raw content.

Kiro has filesystem read access. Pass file paths in the prompt rather than
inlining content — do NOT use `$(cat ...)` in the shell invocation. Large
files passed as shell arguments hit the OS arg length limit and fail.

Always pass a timeout to the Bash tool: `timeout: 120000` (2 min) for
fetch/triage, `timeout: 180000` (3 min) for discovery/research.

## Capabilities

Kiro CAN:
- Read any file on Windows drives via `/mnt/c/`
- Web search and URL fetch
- grep, glob, ls, stat
- Read-only git via WSL git with `env GIT_DISCOVERY_ACROSS_FILESYSTEM=1`
- Read-only `gh.exe` lookups (PR list/view, issue list/view, run list/view)

Kiro CANNOT:
- Write to Windows drives
- Run `task`, `uv`, `pytest`, or build tools (Worker does this)
- Run `git.exe` (use WSL git)
- Mutate state via `gh.exe`

## When Conductor Uses Kiro

- Reading files before deciding what to tell Worker to do
- Searching for patterns, symbols, or usages across the codebase
- Web search, docs lookup, API inspection
- Triaging test output, CI logs, lint reports (< 20KB)
- Git log analysis, PR history, blame
- Exploring unfamiliar subsystems before planning
- Getting a second opinion from an independent model

## Task Types

### Fetch
Web search, docs lookup, API inspection.
Prompt: what source, what facts to extract, recency requirements.

Returns: `## Findings`, `## Sources`, `## Commands fired`, `## Relevance`

### Triage
Test failures, CI logs, lint output, application logs.
Prompt: input category, collapse duplicates, identify root cause.

Returns: `## Triage Summary`, `## Findings`, `## Likely cause`, `## Commands fired`

### Discovery
Symbol definitions, call paths, module relationships.
Prompt: target symbol, desired outputs, no full file dumps.

Returns: `## Discovery`, `## Definitions`, `## Key usages`, `## Related modules`

### PR Draft
PR summary from branch or diff.
Prompt: branch/diff scope, group by theme, stay factual.

Returns: `## Summary`, `## Key Changes`, `## Testing`, `## Impact`

### Research
Architecture understanding, framework/library research.
Prompt: question, constraints, distinguish fact from inference.

Returns: `## Research Findings`, `## Constraints`, `## Commands fired`

## Failure Handling

If `kiro-cli` exits non-zero or produces no output, report failure with
exit code and stderr. Do not retry silently.

If permission denied, check `\\wsl$\Ubuntu\home\willem\.kiro\agents\default.json`
for the allow/deny lists. Propose the specific JSON edit needed.

## Verification

Kiro runs a different model with independent context. Its output is volatile.
Cross-check facts against known context before acting. Never apply blindly.

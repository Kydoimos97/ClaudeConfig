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

## Capabilities and limits

Kiro CAN:
- Read any file on Windows drives via `/mnt/c/`, `/mnt/d/` etc.
- Run web searches and fetch URLs
- grep, glob, ls, stat within any path
- Read the project repo, config files, logs

Kiro CANNOT:
- Write to Windows drives (`/mnt/[a-z]/` writes are denied by sandbox)
- Run `task`, `uv`, `pytest`, or any build/test tooling
- Execute anything that mutates state

For execution tasks, use Codex.

## Quirks

- Kiro runs in WSL Ubuntu. The working directory for shell commands defaults
  to the WSL home (`~`). Always pass full `/mnt/c/...` paths when referencing
  project files, or `cd` explicitly in the prompt.
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

---
name: codex
description: >
  Use codex exec for code implementation and code review only. Codex does not
  run project tooling (tests, uv, task) — main runs those directly. For
  research, reads, and web search use Kiro instead.
---

# Codex

Codex runs in a Windows sandbox with write access to the workspace. It has no
outbound network access and no uv/pytest invocation capability — that is why
implementation and review are its only jobs. For research, reads, or triage,
use Kiro instead.

## Sandbox modes

| Mode | Flag | Use for |
|------|------|---------|
| Review | `--sandbox read-only` | Reviewing diffs — no execution needed |
| Implement | `--sandbox workspace-write` | Writing and editing files |

## Review mode

Use for: reviewing diffs, finding bugs, checking edge cases, validating refactor safety.

```bash
git diff HEAD > /tmp/codex-review-diff.patch

codex exec \
  --sandbox read-only \
  --output-last-message /tmp/codex-review-output.txt \
  "Review the following code changes. Focus on:
1. Bugs and logic errors (P0)
2. Security vulnerabilities (P0)
3. Unhandled edge cases (P1)
4. Performance issues when material (P1)

Skip style nits, formatting, and naming preferences.

For each finding: file, line range, priority (P0/P1), description.

$(cat /tmp/codex-review-diff.patch)"
```

If no staged or unstaged changes exist, stop — nothing to review.

Triage findings:
- Agree: valid bug, security issue, or logic error
- Disagree: Codex misunderstands context — note reason
- Style nit: skip

Clean up after reading:

```bash
rm /tmp/codex-review-diff.patch /tmp/codex-review-output.txt
```

Output contract:

## Codex Review Report
Summary: X agreed (Y P0, Z P1), N disagreed, M style nits skipped

### Agreed Findings
1. [P0] file:line — description

### Disagreed Findings
1. [P1] file:line — reason skipped

### Commands fired
<count>

---

## Implement mode

Use for: feature implementation, bug fixes, refactoring, patch generation, test updates.

```bash
codex exec \
  --sandbox workspace-write \
  --output-last-message /tmp/codex-implement-output.txt \
  "<fully scoped implementation prompt>"
```

Prompt must include: exact goal, scope boundaries, explicit exclusions, required output format.

Output contract:

## Implementation Summary
- change

## Files affected
- path

## Commands fired
<count>

## Concerns
<omit if none>

---

## Rules

- Review mode: `--sandbox read-only` always
- Implement mode: `--sandbox workspace-write` always
- One Codex pass only — no iteration loop
- Prompts must be fully self-contained
- Always use `--output-last-message` and read the file after — do not rely on stdout
- If Codex fails, report clearly and stop — do not retry silently or widen permissions
- After 3 failed attempts on the same goal, stop and surface to main with what was tried

## Before invoking

Main must have already completed research and made all design decisions before
invoking Codex. The task handed off is fully specified — exact goal, scope,
files affected, and approach already decided. Codex implements or reviews;
it does not design.

Validate before running:
- Is the scope clearly bounded?
- Are the target files and change clearly defined?
- Is Codex the right tool, or can main handle this directly?

## Verification

Codex is an external tool running a different model with different context.
Its output is volatile — treat all results as input to main's judgment,
not as ground truth. Always verify before accepting:
- Read every changed file before marking the task done
- Cross-check implementation against the original intent
- Flag anything unexpected or outside the requested scope
- Never apply Codex output blindly

## Second opinion

Codex can be invoked for a second opinion on a design decision or implementation
approach. Because it runs independently with no shared context, its view is
genuinely alternative. Useful for:
- Validating an implementation plan before executing it
- Checking whether a proposed code structure has obvious issues
- Getting an independent read on a technical tradeoff

Frame the question clearly with all relevant context embedded.
Treat the response as one input among several, not a final verdict.

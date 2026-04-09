---
name: codex
description: >
  Use codex exec for large multi-file implementation (5+ files) and code
  review. Escalation from Worker when task scope exceeds 1-3 files. Codex
  cannot run project tooling — Worker handles tests and builds.
---

# Codex

Codex runs in a Windows sandbox with workspace write access. Use it when a
task genuinely needs broad file context — typically 5+ files or a cross-cutting
refactor. **Default to Worker for anything under 5 files.**

No outbound network. No uv/pytest. Implementation and review only.

## When to Use Codex Over Worker

- Multi-file refactors touching 5+ files
- Large feature where full file context across modules matters
- Changes requiring reading many files to understand dependencies
- When Worker would need 4+ sequential invocations for one logical change

## When to Use Worker Instead

- Single-file changes
- Mechanical fixes (lint, types, formatting)
- Test writing for a specific module
- Small bug fixes with clear scope
- Anything touching 1-3 files

## Sandbox Modes

| Mode | Flag | Use for |
|------|------|---------|
| Review | `--sandbox read-only` | Reviewing diffs |
| Implement | `--sandbox workspace-write` | Writing/editing files |

## Review Mode

Codex has full filesystem read access in the sandbox. Pass file paths in the
prompt — do NOT inline file content as shell arguments. Large diffs or files
passed via `$(cat ...)` will hit the OS argument length limit and fail.

```bash
git diff HEAD > /tmp/codex-review-diff.patch

codex exec \
  --sandbox read-only \
  --output-last-message /tmp/codex-review-output.txt \
  "Review the diff at /tmp/codex-review-diff.patch. Focus on:
1. Bugs and logic errors (P0)
2. Security vulnerabilities (P0)
3. Unhandled edge cases (P1)
4. Performance issues when material (P1)

Skip style nits, formatting, naming preferences.

For each finding: file, line range, priority (P0/P1), description."
```

Clean up: `rm /tmp/codex-review-diff.patch /tmp/codex-review-output.txt`

## Implement Mode

```bash
codex exec \
  --sandbox workspace-write \
  --output-last-message /tmp/codex-implement-output.txt \
  "<fully scoped implementation prompt>"
```

Prompt must include: exact goal, scope boundaries, explicit exclusions,
required output format. Same structure as Worker prompts (Goal, Scope,
Approach, Constraints) but broader scope.

Always pass a timeout: `timeout: 180000` (3 min) for small patches,
`timeout: 300000` (5 min) for multi-file work.

## Rules

- Review: `--sandbox read-only` always
- Implement: `--sandbox workspace-write` always
- One Codex pass only — no iteration loop
- Prompts must be fully self-contained
- Always use `--output-last-message` and read the file after
- After 3 failed attempts on same goal, stop and surface to Conductor

## Verification

Codex runs a different model with different context. Treat all output as
input to Conductor's judgment:
- Read every changed file before committing (use line ranges for large files)
- Cross-check against original intent
- Flag anything outside requested scope
- Have Worker run tests after Codex implements

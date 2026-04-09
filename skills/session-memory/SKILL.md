---
name: session-memory
description: >
  Native Claude Code project memory format, update rules, and topic file
  structure. Read at session start to restore context.
---

# Session Memory

Claude Code automatically injects project memory into every session via
system-reminder. The files live at:

```
~/.claude/projects/<encoded-project-path>/memory/
  MEMORY.md          <- index, quick facts, topic file list
  active-prs.md      <- open branches, PR numbers, status
  cypress-baseline.md
  api-migration.md
  component-contracts.md
  auth-session.md
  codebase-patterns.md
  ... (add topic files as needed)
```

The `<encoded-project-path>` is the CWD with `\` → `--` and `:` dropped.
Example: `C:\Users\willem\Documents\WrenchProjects\wrench-frontend`
→ `C--Users-willem-Documents-WrenchProjects-wrench-frontend`

## Bootstrap

1. Claude Code injects memory into context automatically — no manual read needed
2. If a topic file is referenced in MEMORY.md but missing, create it
3. Do NOT create or look for `AgentMemory.md` — that system is retired

## Update Rules

- **MEMORY.md** — index only; update quick facts and topic file list here
- **Topic files** — append to the relevant file; never replace existing entries
- Keep entries lean — only what a fresh session genuinely needs
- Write when something materially changes: user instruction, approach failure,
  non-obvious decision, architecture insight, task completed/added
- Do NOT write routine progress or things already in commit messages

## What Goes Where

| Content | File |
|---------|------|
| Open PRs, branch status | `active-prs.md` |
| Cypress spec inventory, runner notes, lessons | `cypress-baseline.md` |
| API endpoint migration history | `api-migration.md` |
| testId patterns, e2e metadata contracts | `component-contracts.md` |
| WorkOS auth, cy.session patterns | `auth-session.md` |
| Routing, slice/hook conventions, feature flags | `codebase-patterns.md` |
| Quick facts about the project | `MEMORY.md` Quick Facts section |

## Merge Conflicts

When conflicts occur on memory files, consolidate both sides: deduplicate,
merge overlapping entries, leave the file leaner than either branch had it.

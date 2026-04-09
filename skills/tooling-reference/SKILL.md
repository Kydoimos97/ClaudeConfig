---
name: tooling-reference
description: >
  Reference for integrated tooling: PowerShell modules, database access,
  AWS secrets, command guard, and knowledge sources. Read when you first
  need project tooling or context.
---

# Tooling Reference

## PowerShell Commands

Run `usePwsh7` with no args to list all available commands with safety icons.

Key commands:

| Command | What it does |
|---------|-------------|
| `usePwsh7 Invoke-WrenchProdDb "<sql>"` | Read-only prod DB |
| `usePwsh7 Invoke-WrenchDevDb "<sql>"` | Read-only dev DB (default — use this) |
| `usePwsh7 Invoke-WrenchQaDb "<sql>"` | Read-only QA DB |
| `usePwsh7 Aws-GetSecret "name" prod\|dev` | Fetch secret from AWS |
| `usePwsh7 Aws-SecretFind "filter" prod\|dev` | Discover secrets matching filter |
| `usePwsh7 Aws-Show` | Show current AWS credentials |
| `usePwsh7 Git-DailySummary` | GitHub activity summary for standup |

DB access details: read `~/.claude/skills/wrench-rds/SKILL.md`.

## Command Guard

```bash
c-guard audit "<command>" --mode dontAsk
```

Pre-checks whether a command is allowed, auto-allowed, or blocked.
If blocked, the output includes a **hint** with the preferred alternative.
Follow the hint — do not work around the block.

## Knowledge Sources

Check these in order before speculating:

| Source | What it holds |
|--------|--------------|
| `~/.claude/` | Global preferences, skills, per-project memory in `projects/<id>/memory/` |
| In-repo docs | `docs/`, `README.md`, `CLAUDE.md`, `*.md` in root |
| `wrench-dna` repo | Cross-cutting architecture decisions, agent design patterns |
| PR history | `gh pr list`, `gh pr view <n>`, `gh pr diff <n>` |
| Closed issues | `gh issue list --state closed` |

Local repos: `C:\Users\willem\Documents\WrenchProjects\`

Prefer reading local files directly over `gh api` calls for code exploration.

## Slack Channels

Available via Slack MCP:

| Channel | Purpose |
|---------|---------|
| `#claude-box` (C0ALG6HQNM) | Agent coordination, casual status |
| `#notes` (C05E80TPJ9F) | Important findings, owner-facing notes |
| `#pr-reviews` | PR activity |
| `#bug-reports` | Bug intake |
| `#platform-metrics` | System health |
| `#agent-feedback` | Agent behavior feedback |
| `#assistant-alerts` | AI assistant alerts |

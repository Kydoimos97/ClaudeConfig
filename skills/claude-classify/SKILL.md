---
name: claude-classify
description: >
  Classify or route a small in-context task without external retrieval.
  Use for deciding task type, risk category, likely owner, or which delegate
  should handle the work.
---

# Claude Classify

Use this skill for cheap local routing and categorization work.

## Use when

- deciding whether a task is retrieval, coding, or synthesis
- classifying work as bug, refactor, feature, or cleanup
- identifying likely risk level from a short description
- choosing between Kiro, Codex, and main for a bounded task
- grouping a short list into categories

## Do not use when

- code inspection across files is needed
- repository search is needed
- logs or diffs are large
- external lookup is needed

## Routing model

Research and retrieval layer:
- Kiro: web search, file reads, log triage, API inspection, output analysis

Implementation layer:
- Codex: code generation, refactoring, patch creation, diff review

Orchestration layer:
- Main: decisions, planning, tool invocation, quality gating, anything requiring judgment

## Output contract

Return:

## Classification
Type: <bug|feature|refactor|research|triage|rewrite|review|config|other>

## Recommended delegate
<kiro|codex|main>

## Reason
<one to three short sentences>

Keep it concise.

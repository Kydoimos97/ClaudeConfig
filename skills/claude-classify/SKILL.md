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
- choosing between Claude, Codex, and Kiro for a bounded task
- grouping a short list into categories

## Do not use when

- code inspection across files is needed
- repository search is needed
- logs or diffs are large
- external lookup is needed

## Routing model

Thinking layer (decisions and reasoning):
- Socrates: complex decisions, conflicting results, judgment calls requiring deep analysis

Execution layer (action and retrieval):
1. Mini: tiny in-context rewrite, summarization, classification, .claude config edits
2. Codex: code implementation, code review, refactoring, technical code judgment
3. Kiro: retrieval, search, fetch, broad exploration, long-output triage

## Output contract

Return:

## Classification
Type: <bug|feature|refactor|research|triage|rewrite|review|config|other>

## Recommended delegate
<mini|codex|kiro|socrates>

## Reason
<one to three short sentences>

Keep it concise.
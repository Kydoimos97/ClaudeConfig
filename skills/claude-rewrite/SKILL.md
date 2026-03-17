---
name: claude-rewrite
description: >
  Rewrite or tighten short in-context text without external retrieval.
  Use for concise rewrites, tone adjustment, shortening, wording cleanup,
  and small formatting changes when all source text is already present.
---

# Claude Rewrite

Use this skill only for small, bounded text transformations where all required
context is already in the conversation.

## Use when

- rewriting a short paragraph
- tightening a message
- changing tone
- shortening text
- improving clarity
- converting text into a cleaner format
- rewording a short PR note, Slack message, commit message, or explanation

## Do not use when

- repo search is needed
- web search is needed
- logs need summarization
- code generation is needed
- large documents need transformation
- multiple files need to be inspected

Those should go to Kiro or Codex.

## Rules

- Stay strictly within the provided text.
- Do not add new facts.
- Do not introduce new scope.
- Preserve technical meaning unless the user explicitly asks to change it.
- Prefer concise output.
- Return only the rewritten result unless brief variants are clearly useful.

## Output contract

Return one of:
- a single rewritten version
- two to three short variants if the caller asked for options

Do not include explanations unless explicitly requested.
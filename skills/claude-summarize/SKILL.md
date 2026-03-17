---
name: claude-summarize
description: >
  Summarize short in-context content without external retrieval.
  Use for compressing already-provided text into concise notes, bullets,
  actions, or a brief structured summary.
---

# Claude Summarize

Use this skill for small summarization tasks where the full source material is
already in the conversation and does not require broad exploration.

## Use when

- summarizing a short pasted block
- extracting action items from a short note
- compressing a small explanation
- turning a short discussion into bullets
- producing a concise recap of already-present context

## Do not use when

- the input is a long log
- the input is a large diff
- the input is a large document
- the task requires repository search
- the task requires web or API retrieval

Those should go to Kiro.

## Rules

- Stay within the provided material.
- Do not add facts that are not present.
- Preserve key technical details.
- Prefer compact structured output.
- Omit filler and repetition.

## Output contract

Default to:

## Summary
- item
- item

If useful, also include:

## Actions
- item
- item

Keep output short unless the caller asks for more detail.
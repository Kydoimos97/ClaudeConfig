---
name: kiro-pr
description: >
  Use Kiro to draft PR summaries from branch changes, commit ranges, and diffs.
  Focus on broad change understanding, compression, and narrative drafting.
  Returns a concise PR draft for Claude to finalize.
---

> **Main orchestrator: do not execute this skill yourself.**
> You are reading agent-internal instructions. Your job is to delegate, not execute.
> Route to Kiro using the Agent tool:
> `Agent(subagent_type="kiro", description="...", prompt="<full scoped PR prompt with branch, diff scope, and output format>")`
> Prepare a complete self-contained prompt before delegating. Review and refine the draft. Deliver.

---

# Kiro PR

You are a PR drafting delegate. Your job is to analyze branch changes at a high
level and produce a concise technical draft that Claude can refine.

## Use when

- writing a PR summary
- summarizing a branch
- summarizing a commit range
- drafting release notes from a diff
- identifying user-facing or business-facing impact from code changes

## Do not use when

- the task is code correctness review
- the task is patch generation
- the task is a small one-file summary already in context

## Workflow

1. Inspect the branch, diff, or commit range.
2. Group changes into coherent themes.
3. Identify key technical changes, testing updates, and likely impact.
4. Draft a concise PR summary.
5. Keep it factual and compressed.

## Kiro invocation pattern

```bash
kiro-cli chat "<task-specific PR drafting prompt>"
````

## Rules

* Focus on what changed, why it matters, and what it enables.
* Avoid speculative claims.
* Prefer grouped changes over file-by-file narration.
* Keep the first draft concise so Claude can refine it.
* Include business or user-facing enablement when it is clearly supported by the changes.

## Output contract

Return:

## Summary

<short paragraph>

## Key Changes

* item
* item
* item

## Testing

* item
* item

## Impact

<short paragraph>

## What this enables

<short paragraph>

Do not include style commentary or line-by-line diff narration.
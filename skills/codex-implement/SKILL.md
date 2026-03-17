---
name: codex-implement
description: >
  Use Codex as the primary coding engine for implementation, refactoring,
  patch generation, and code-focused changes. Returns a concise implementation
  summary, not a verbose transcript.
---

> **Main orchestrator: do not execute this skill yourself.**
> You are reading agent-internal instructions. Your job is to delegate, not execute.
> Route to Codex using the Agent tool:
> `Agent(subagent_type="codex", description="...", prompt="<full scoped implementation prompt with files, scope, and rules>")`
> Prepare a complete self-contained prompt before delegating. Review the output. Deliver.

---

# Codex Implement

You are a coding delegate. Your job is to ask Codex to produce a focused
implementation plan or code change for the scoped task.

## Use when

- implementing a new feature
- fixing a bug
- refactoring code
- updating tests with a code change
- generating a patch from a clear request
- making targeted code edits

## Do not use when

- the task is broad repository exploration
- external retrieval is needed
- the task is primarily PR drafting
- the task is primarily long-output triage

## Workflow

1. Determine the smallest code scope needed.
2. Gather only the files or diff required for the task.
3. Invoke Codex with a focused prompt.
4. Ask for implementation output or a concise change plan.
5. Return a compressed result.

## Codex invocation pattern

Adapt the exact flags to the installed Codex CLI version. Example shape:

```bash
codex exec \
  --sandbox workspace-write \
  --output-last-message /tmp/beebop-codex-implement.txt \
  "<task-specific implementation prompt>"
````

## Rules

* Keep prompts tightly scoped.
* Prefer implementation summaries and changed-file lists over long transcripts.
* Do not ask Codex to review the whole repository unless explicitly required.
* If tests should be updated, ask for that explicitly.

## Output contract

Return:

## Implementation Summary
* change
* change

## Files affected
* path
* path

## Commands fired
<integer count>

## Summary of Changes
<what was changed and why>

## Relevant Context
<anything Beebop needs to understand the state after this change>

## Concerns
<error signals, unexpected findings, or anything warranting Beebop's attention — omit if none>

If Codex fails, return the failure clearly and stop.
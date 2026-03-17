---
name: codex-review
description: >
  Use Codex as a focused code review delegate for diffs and scoped technical
  analysis. Returns actionable findings only, with style nits suppressed by
  default.
---

> **Main orchestrator: do not execute this skill yourself.**
> You are reading agent-internal instructions. Your job is to delegate, not execute.
> Route to Codex using the Agent tool:
> `Agent(subagent_type="codex", description="...", prompt="<full scoped review prompt with diff, file paths, and quality bar>")`
> Prepare a complete self-contained prompt before delegating. Review the findings. Deliver.

---

# Codex Review

You are a code review delegate. Your job is to run Codex on a focused diff or
code change and return only actionable findings.

## Use when

- reviewing current changes
- checking a diff for bugs
- looking for regressions
- identifying edge cases
- validating refactor safety
- getting a second opinion on code changes

## Do not use when

- there are no code changes
- the task is broad repo exploration
- the task is primarily external research
- the task is just PR drafting

## Workflow

1. Check whether there are reviewable changes.
2. Generate the smallest relevant diff.
3. Invoke Codex in read-only mode.
4. Ask for bugs, regressions, risky assumptions, edge cases, and test-impact issues.
5. Suppress style-only comments by default.
6. Return structured findings.

## Review scope

Focus on:
- logic bugs
- regressions
- unsafe assumptions
- missing edge cases
- test impact
- performance issues when material

Skip:
- formatting
- naming nits
- style preferences
- low-value churn suggestions

## Codex invocation pattern

Adapt flags to the installed Codex CLI version. Example shape:

```bash
codex exec \
  --sandbox read-only \
  --output-last-message /tmp/beebop-codex-review.txt \
  "<task-specific review prompt>"
````

## Output contract

Return:

## Review Summary
Actionable findings: <count>

## Findings
1. [P0|P1] path:line — issue
2. [P0|P1] path:line — issue

## Skipped
* style-only items
* non-actionable suggestions

## Commands fired
<integer count>

## Relevant Context
<anything Beebop needs to understand the review findings in context>

## Concerns
<unexpected findings, edge cases, or anything warranting Beebop's attention — omit if none>

If there are no actionable findings, say:
Codex found no actionable issues.
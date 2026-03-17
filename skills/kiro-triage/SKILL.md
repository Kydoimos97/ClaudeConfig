---
name: kiro-triage
description: >
  Use Kiro to compress and triage large outputs such as test failures, CI logs,
  linter output, Terraform plans, Datadog traces, and long command results.
  Returns concise findings only.
---

> **Main orchestrator: do not execute this skill yourself.**
> You are reading agent-internal instructions. Your job is to delegate, not execute.
> Route to Kiro using the Agent tool:
> `Agent(subagent_type="kiro", description="...", prompt="<full scoped triage prompt with the raw output, what to collapse, and root-cause focus>")`
> Prepare a complete self-contained prompt before delegating. Review the findings. Deliver.

---

# Kiro Triage

You are a bulk-output triage delegate. Your job is to reduce noisy output into
a small set of actionable findings.

## Use when

- summarizing pytest failures
- summarizing CI logs
- compressing Ruff or Ty output
- summarizing Terraform plan output
- triaging ECS, Datadog, or application logs
- summarizing long command output
- identifying likely root cause from noisy output

## Do not use when

- the task is primarily code generation
- the task is primarily code review
- the task is a tiny in-context summary
- the task requires broad web retrieval rather than output analysis

## Workflow

1. Identify the command output, log block, or report to analyze.
2. Use Kiro to inspect the material.
3. Extract only the most relevant errors, warnings, and likely causes.
4. Group duplicate or cascading failures together.
5. Return compressed findings and recommended next focus.

## Kiro invocation pattern

```bash
kiro-cli chat "<task-specific triage prompt>"
````

## Rules

* Prefer root causes over symptom lists.
* Collapse duplicate failures.
* Suppress raw noise, repetition, stack trace spam, and secondary fallout.
* Preserve exact file names, test names, endpoints, resources, and error types when relevant.

## Output contract

Return:

## Triage Summary
Primary issue: <one line>

## Findings
1. issue
2. issue
3. issue

## Likely cause
<short paragraph>

## Commands fired
<integer count>

## Concerns
<secondary signals, partial data, or anything warranting Beebop's attention — omit if none>

Do not return full logs unless explicitly requested.

---
name: kiro-research
description: >
  Use Kiro for broad research, architecture understanding, documentation lookup,
  and large-context analysis that should not consume Claude context directly.
  Returns compressed findings only.
---

> **Main orchestrator: do not execute this skill yourself.**
> You are reading agent-internal instructions. Your job is to delegate, not execute.
> Route to Kiro using the Agent tool:
> `Agent(subagent_type="kiro", description="...", prompt="<full scoped research prompt with the question, constraints, and output format>")`
> Prepare a complete self-contained prompt before delegating. Review the findings. Deliver.

---

# Kiro Research

You are a research delegate. Your job is to gather and compress information from
documentation, repository context, and other large text sources.

## Use when

- understanding a subsystem
- researching a framework or library
- comparing approaches from docs or existing code
- summarizing architecture across many modules
- understanding unfamiliar areas of a repository
- gathering background before implementation or review

## Do not use when

- the task is primarily code generation
- the task is primarily code review
- the task is a trivial in-context question
- the task is just a short rewrite

## Workflow

1. Clarify the research target.
2. Use Kiro to gather relevant information.
3. Extract the most relevant facts, patterns, and constraints.
4. Compress the result into a concise summary.
5. Return only findings useful for the next step.

## Kiro invocation pattern

```bash
kiro-cli chat "<task-specific research prompt>"
````

## Rules

* Prefer concise findings over broad essays.
* Highlight constraints, caveats, and implications.
* Distinguish confirmed facts from inferred conclusions.
* Avoid raw source dumps.

## Output contract

Return:

## Research Findings
* fact
* fact
* fact

## Constraints
* item
* item

## Commands fired
<integer count>

## Relevance
<short paragraph>

## Concerns
<gaps, conflicting sources, or anything warranting Beebop's attention — omit if none>
---
name: kiro-discovery
description: >
  Use Kiro for repository exploration, symbol discovery, and large-scale codebase
  tracing. Use when broad search or architecture discovery would otherwise waste
  Claude context.
---

> **Main orchestrator: do not execute this skill yourself.**
> You are reading agent-internal instructions. Your job is to delegate, not execute.
> Route to Kiro using the Agent tool:
> `Agent(subagent_type="kiro", description="...", prompt="<full scoped discovery prompt with target symbol, repo context, and output format>")`
> Prepare a complete self-contained prompt before delegating. Review the findings. Deliver.

---

# Kiro Discovery

You are a repository exploration delegate. Your job is to locate definitions,
trace usages, identify entry points, and summarize subsystem structure without
dumping large volumes of code into Claude.

## Use when

- finding where a symbol is defined
- tracing call paths
- identifying entry points
- mapping module relationships
- locating where a feature or permission flow lives
- summarizing unfamiliar subsystems

## Do not use when

- a specific code edit is already scoped and ready
- the task is primarily code generation
- the task is primarily code review on a focused diff

## Workflow

1. Identify the search target.
2. Use Kiro to explore the repository.
3. Collect definitions, key usages, and relevant file paths.
4. Summarize the module purpose and relationship graph.
5. Return compressed findings only.

## Kiro invocation pattern

```bash
kiro-cli chat "<task-specific repository discovery prompt>"
````

## Output contract

Return:

## Discovery
Target: <symbol or topic>

## Definitions
* path:line
* path:line

## Key usages
* path:line
* path:line

## Related modules
* module
* module

## Commands fired
<integer count>

## Relevance
<one short paragraph>

## Concerns
<access blocks, gaps, or anything warranting Beebop's attention — omit if none>

Do not return full file contents unless explicitly requested.
---
name: kiro-fetch
description: >
  Use Kiro for external retrieval and compression of fetched results.
  Use for web search, documentation lookup, curl requests, API calls,
  and broad information gathering that should not consume Claude context.
---

> **Main orchestrator: do not execute this skill yourself.**
> You are reading agent-internal instructions. Your job is to delegate, not execute.
> Route to Kiro using the Agent tool:
> `Agent(subagent_type="kiro", description="...", prompt="<full scoped fetch prompt with URL/source, what to extract, and output format>")`
> Prepare a complete self-contained prompt before delegating. Review the findings. Deliver.

---

# Kiro Fetch

You are a retrieval delegate. Your job is to use Kiro to gather information,
compress it, and return only the most relevant findings.

## Use when

- web search is needed
- documentation lookup is needed
- curl or API inspection is needed
- external references need to be checked
- multiple sources need to be scanned and condensed

## Do not use when

- the task is primarily code writing
- the task is primarily code review
- the task is tiny and already fully in context

## Retrieval policy

Prefer Kiro over direct Claude retrieval for:
- web search
- docs lookup
- HTTP fetches
- API response inspection
- long external outputs

## Workflow

1. Determine the smallest set of retrieval actions needed.
2. Use Kiro CLI to perform the lookup or fetch.
3. Extract only relevant facts.
4. Compress noisy output aggressively.
5. Return a structured result.

## Kiro invocation pattern

Adapt the command to the task, but keep the result concise. Example shape:

```bash
kiro-cli chat "<task-specific retrieval prompt>"
````

## Output contract

Return:

## Findings
* fact
* fact

## Sources
* source
* source

## Commands fired
<integer count>

## Relevance
<one short paragraph>

## Concerns
<access blocks, partial results, or anything warranting Beebop's attention — omit if none>

Do not dump raw HTML, raw JSON, or long fetched content unless explicitly requested.
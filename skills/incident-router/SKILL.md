---
name: incident-router
description: >
  Incident router skill for Datadog Incident Management. Runs in two modes:
  ai-queue (returns unassigned todos as the AI work queue) and triage-queue
  (returns prioritized incidents needing triage, stall flags, and merge candidates).
---

# Incident Router Skill

Returns what the incident manager needs to act: the AI task queue, stalled stable
incidents, merge candidates, and a prioritized triage queue.

## Input Contract

Required:
- `mode`: `ai-queue` or `triage-queue`

Optional:
- `time_window`: lookback window for incident fetch (default: "6h")
- `limit`: max incidents to fetch (default: 100)

## Output Contract

### ai-queue mode

A list of unassigned todos from all open incidents, in order:

```
AI Task Queue — <N> pending tasks

<incident_title> ([https://us5.datadoghq.com/incidents/<numeric_id>])
  - <todo text> (todo_id: <id>)
  - <todo text> (todo_id: <id>)

<incident_title> (...)
  - ...
```

If no unassigned todos: output `AI Task Queue — empty. No pending AI work.`

### triage-queue mode

Three sections:

```
## Stalled Stable — Decision Required
<incident_title> | https://us5.datadoghq.com/incidents/<id> | SEV-N | stable Xd | reason: <why stalled or new signal>

## Merge Candidates
Group A: <incident_title_1> + <incident_title_2> — shared: <root cause / service / error type>

## Triage Queue
P0 | https://us5.datadoghq.com/incidents/<id> | <title> | active | SEV-1/2
P1 | https://us5.datadoghq.com/incidents/<id> | <title> | active | SEV-3+
P2 | https://us5.datadoghq.com/incidents/<id> | <title> | new | any

## Summary
Total open: <N>
AI queue: <N> pending tasks
Stalled stable: <N>
Merge candidates: <N> groups
To triage: <N>
Skipped (no change): <N>
Feature requests filtered: <N>
```

## Workflow

### Step 1: Fetch all open incidents

```bash
uv run puppy incident list --limit <limit> --format json
```

Extract for each: incident ID (numeric), title, status, severity, created timestamp,
assigned team, commander, responders.

Build the full Datadog URL for each: `https://us5.datadoghq.com/incidents/<numeric_id>`

### Step 2 (ai-queue mode only): Fetch unassigned todos

For each open incident:

```bash
uv run puppy incident todo list <incident_id>
```

Collect all todos with no assignee. These are pending AI tasks from previous runs.

Return them grouped by incident. Include todo IDs so the incident manager can mark
them complete after execution.

Exit after returning the queue. Do not proceed to Steps 3-7.

### Step 3: Read previous report

Look for the most recent report at: `~/.puppy-kit/reports/incident-report-*.md`

Extract:
- Incident IDs already triaged and their last-known status
- Incidents marked stable with their stable-since date
- Incidents resolved in previous runs

### Step 4: Filter feature requests

Remove incidents with titles containing "Feature:", "[FR]", "feature request",
or "enhancement". Bucket by team for the report. Count them in summary.

### Step 5: Detect stalled stable incidents

For each incident in stable status:

Calculate days stable: `today - stable_since_date` (from previous report or incident timestamps).

Mark as stalled if:
- Stable >72h AND root cause listed as "Requires investigation" or similar — no confirmed fix
- Stable >72h AND no completed todos since it went stable
- A new error signal matching this incident's service/error type appeared in the last run

For stalled incidents: include in "Stalled Stable" section with reason.

For stable incidents with zero recurrence for >48h: flag as "recommend resolve" in output.

### Step 6: Detect merge candidates

Group remaining incidents by:
- Same service AND same error type (e.g., two UniqueViolation incidents on the same table)
- Same root cause description (significant text overlap)
- Same internal caller IP or service identity
- Time-correlated creation (within 30 min of each other, same service)

For each group with 2+ incidents: include in merge candidates section with the shared attribute.

### Step 7: Skip already-triaged unchanged incidents

For each remaining non-stalled stable incident:
- If ID was in previous report AND status has not changed AND no new AI todos pending: skip
- If active: always include

### Step 8: Prioritize triage queue

Sort:
1. P0: Active, SEV-1 or SEV-2
2. P1: Active, SEV-3 or higher
3. P2: New (not in previous report), any severity

Stalled stable incidents are handled separately in Step 5 and returned in their own section,
not in the triage queue — the incident manager decides whether to re-triage or force-close them.

### Step 9: Build output

Construct the triage-queue output as specified in the Output Contract.

Always use full numeric Datadog URLs. Never use short hash IDs.

## Error Handling

If `puppy incident list` returns no results:
- Output: "No open incidents."
- Return empty queue

If todo fetch fails for a specific incident: note it, continue with others.

If previous report not found: output "No previous report — treating all incidents as new."

## Key Rules

- Always use full Datadog URLs: `https://us5.datadoghq.com/incidents/<numeric_id>`
- Unassigned todos = AI work queue — return them all in ai-queue mode
- Stalled stable incidents get their own section — not mixed into the triage queue
- Feature requests are bucketed for the report, not triaged
- Merge candidates are surfaced for the incident manager to act on, not resolved here
- Stable >48h zero recurrence: flag as recommend-resolve, do not silently carry forward

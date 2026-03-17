---
name: incident-report
description: >
  Incident report skill for Datadog Incident Management. Produces a focused standup brief
  and writes context files for the next run. No work log. Todos scoped to active and changed
  incidents only. Full Datadog URLs as hyperlinks. Stores report and context in ~/.puppy-kit/.
---

# Incident Report Skill

Produces the standup brief and writes context for the next run.
This is not a work log. The reader needs to know: what is on fire, what is stalling,
and what needs doing today.

## Input Contract

Required:
- `triage_schemas`: list of completed 13-field triage schemas from this run
- `ai_tasks_completed`: list of AI todo IDs marked complete this run
- `incidents_resolved`: list of incident IDs resolved this run with one-line root cause
- `incidents_merged`: list of merge pairs (duplicate_id → canonical_id)
- `stalled_stable`: list of stalled incident schemas passed through from router

Optional:
- `date_time`: report timestamp (default: current time)
- `output_path`: override default path

## Output Contract

Two files written:

1. `~/.puppy-kit/reports/incident-report-<YYYYMMDD-HHmmss>.md` — standup brief
2. `~/.puppy-kit/context/run-context-<YYYYMMDD-HHmmss>.md` — context for next run

Output message:
```
Report: ~/.puppy-kit/reports/incident-report-<timestamp>.md
Context: ~/.puppy-kit/context/run-context-<timestamp>.md
Active: <N> | Action required: <N> | Monitoring: <N> | Resolved: <N>
```

## Report Format

```markdown
# Incident Report — YYYY-MM-DD HH:MM UTC

## Summary
<2-3 sentences: active count, dominant issues, overall system health>

## Active — Needs Immediate Attention

- **[Title](https://us5.datadoghq.com/incidents/<id>)** (SEV-N) — open Xh
  - Impact: <blast radius and user impact>
  1. [HUMAN] <specific next step>
  2. [AI] <specific next step if any>

(If none: "No active incidents.")

## Stable — Action Required

Stable incidents that are stalled (no confirmed progress in >72h) or where a new
signal was detected this run. Requires a human decision: close or escalate.

- **[Title](https://us5.datadoghq.com/incidents/<id>)** (SEV-N) — stable Xd
  - Blocking: <what is preventing resolution>
  - Recommended: <close | escalate | specific action>

(Omit section if none.)

## Stable — Under Monitoring

| Incident | Sev | Stable Since | Blast Radius | Monitor Until |
|---|---|---|---|---|
| [Title](URL) | SEV-N | YYYY-MM-DD | internal-only | condition |

Incidents marked "recommend close" have been stable >48h with zero recurrence.

(Omit section if none.)

## Resolved This Run

- **[Title](URL)** — <root cause one-liner>

(If none: "None.")

## Todo

Active and changed incidents only. Stable incidents with no change are in the tables above.

### Backend
- [HUMAN] **[Title](URL)** — specific action required

### Frontend
- [HUMAN] **[Title](URL)** — specific action required

### Backlog
- [FEATURE] <description> (from: [Title](URL))

## Stats

| Metric | Count |
|---|---|
| Active | N |
| Stable — Action Required | N |
| Stable — Monitoring | N |
| Resolved this run | N |
| Merged (duplicates closed) | N |
| AI tasks executed | N |
| Skipped (no change) | N |
```

## Context File Format

Written to `~/.puppy-kit/context/run-context-<timestamp>.md`:

```markdown
# Run Context — YYYY-MM-DD HH:MM UTC

## Active Incidents
- <id> | <title> | SEV-N | open Xh | next check: <what to verify>

## Stable — Pending Recurrence Check
- <id> | <title> | stable since YYYY-MM-DD | check: zero recurrence for >48h → resolve
- <id> | <title> | stable since YYYY-MM-DD | check: <specific condition>

## Stalled — Needs Decision
- <id> | <title> | stable Xd | blocking: <what is unresolved>

## AI Task Queue
Written to: ~/.puppy-kit/context/ai-queue-<timestamp>.md

## Resolved This Run
- <id> | <title> | resolved: <root cause>

## Merged This Run
- <duplicate_id> → <canonical_id> | reason: <shared root cause>

## Notes for Next Run
<anything the agent should remember: known patterns, in-progress fixes, context
that is not captured in Datadog but is relevant to the next triage>
```

## AI Queue File Format

Written to `~/.puppy-kit/context/ai-queue-<timestamp>.md`:

```markdown
# AI Task Queue — YYYY-MM-DD HH:MM UTC

## Pending Tasks

### <incident_title> (https://us5.datadoghq.com/incidents/<id>)
- todo_id: <id> | <task description>
- todo_id: <id> | <task description>

### ...

## Recurrence Checks Due
- <id> | <title> | stable since <date> | check: <log query or condition>

## Notes
<any context needed to execute these tasks>
```

## Workflow

### Step 1: Classify incidents by status

From triage_schemas + stalled_stable:
- Active: status = active
- Stalled stable: in stalled_stable list
- Routine stable: stable, not stalled, no change this run
- Resolved: status = resolved, or in incidents_resolved list

### Step 2: Build summary (2-3 sentences)

State active count, what the dominant issue is if any, and overall health.
Do not list every incident — that is what the sections below are for.

### Step 3: Build Active section

For each active incident: title as hyperlink, SEV, duration open, blast radius,
top 2 next steps only (not all next steps).

### Step 4: Build Stable — Action Required section

From stalled_stable list: include incidents with no confirmed progress in >72h
or new signal detected. Include what is blocking resolution and a concrete recommendation.

### Step 5: Build Stable — Monitoring table

For each routine stable incident: compact table row with title as hyperlink, SEV,
stable since date, blast radius, and monitor-until condition.

Flag "recommend close" if stable >48h with zero recurrence confirmed.

### Step 6: Build Resolved section

From incidents_resolved: title as hyperlink and one-line root cause with evidence.

### Step 7: Build Todo section

Extract Next Steps from active and changed incidents only.
Do not extract todos from carried-forward stable incidents.

For each step:
- [HUMAN] steps only — [AI] steps do not appear in the report todo section
- Include incident title as hyperlink next to each task so the reader knows the context
- Sort by team: Backend, Frontend, Sales
- Feature requests in Backlog subsection

### Step 8: Write report file

```bash
mkdir -p ~/.puppy-kit/reports/
```

Write the report markdown to `~/.puppy-kit/reports/incident-report-<YYYYMMDD-HHmmss>.md`

### Step 9: Write context file

```bash
mkdir -p ~/.puppy-kit/context/
```

Write run context to `~/.puppy-kit/context/run-context-<YYYYMMDD-HHmmss>.md`

Include in the context file:
- All active incidents with what to verify on next run
- All stable incidents with their recurrence check condition
- All stalled incidents with the blocking reason
- Notes for next run: anything not captured in Datadog (in-progress fixes, known patterns)

### Step 10: Write AI queue file

Write AI task queue to `~/.puppy-kit/context/ai-queue-<YYYYMMDD-HHmmss>.md`

Include:
- All unassigned todos currently open across all incidents
- Recurrence checks due (stable incidents that need zero-recurrence verification)
- Any context needed to execute these tasks efficiently

### Step 11: Output confirmation

Print the output message with report path, context path, and counts.

## Key Rules

- Report is for a human reader — no internal bookkeeping (no "updates applied", no "previous run diff")
- [AI] todos never appear in the report Todo section — they are in the AI queue file
- [HUMAN] todos always include the incident title as a hyperlink for context
- All incident references use full Datadog URLs as hyperlinks
- Stable >48h zero recurrence: flag "recommend close" in monitoring table
- Stalled stable gets its own section with a concrete recommendation, not just a table row
- Context files use timestamped names so the agent can identify the most recent one
- Notes for next run capture institutional knowledge not stored in Datadog

---
name: dashboard-gap-analysis
description: >
  Recurring dashboard health check. Queries the Platform Health Dashboard's key signals
  for the last 1 week, checks current state, and surfaces any actively anomalous signals
  that have no open incident. Creates SEV-3 or SEV-4 incidents for uncovered active issues.
  Monitor gap analysis is a separate one-time exercise — this skill is the ongoing review.
---

# Dashboard Health Review Skill

Checks whether the Platform Health Dashboard is showing any active signals not covered
by an open incident. This is the recurring review — run daily or whenever you want a
platform health snapshot.

## Tool Execution Model

Main runs puppy and gh. Kiro handles git and source code review.

`uv run puppy` and `gh` are Windows-only — Kiro cannot run them. For every puppy command:

1. Main runs via Bash: `uv run puppy <cmd> > /tmp/puppy_out.txt 2>&1`
2. Check size: `ls -lh /tmp/puppy_out.txt`
3. Small (<20KB): invoke summarizer with the file path to compress findings
4. Large (>=20KB): invoke Kiro with the file path for full triage

Kiro CAN run git directly against Windows repos:
`env GIT_DISCOVERY_ACROSS_FILESYSTEM=1 git -C /mnt/c/<repo-path> <subcommand>`

Use Kiro for all source code review, git log, and file reads via `/mnt/c/` paths.

## Inputs

| Input | Default | Description |
|---|---|---|
| `dashboard_id` | `d7y-q4z-dye` | Datadog dashboard ID |
| `lookback` | `1w` | Metric query window for trend context |
| `active_window` | `1h` | Window for "is it firing right now" check |
| `dry_run` | false | Print findings without creating incidents |

## Workflow

### Step 1: Fetch open incidents

```bash
uv run puppy incident list --limit 100 --format json
```

Build a set of open incident titles and services. This is used in Step 4 to check
whether an active signal already has a declared incident.

### Step 2: Query current metric state

For each key signal group, query current values using the Datadog metrics API
(raw requests with auth from `load_config()`). Use `active_window` for current state,
`lookback` for baseline context.

**AI-Axis signals:**
- `sum:trace.fastapi.request.errors{service:ai-axis,env:prod}.as_count()` — error count
- `sum:trace.fastapi.request.errors{service:ai-axis,env:prod}.as_count() / sum:trace.fastapi.request{service:ai-axis,env:prod}.as_count()` — error rate
- `p95:ml_obs.span.duration{span_kind:llm,env:prod}` — LLM p95 latency

**Infrastructure signals:**
- `sum:aws.lambda.errors{!functionname:datadog*}.as_count()` — Lambda errors
- `sum:aws.states.executions_failed{*}.as_count()` — Step Functions failures
- `sum:aws.apigateway.5xxerror{*}.as_count()` — API Gateway 5xx
- `avg:aws.rds.cpuutilization{engine:postgres}` — RDS CPU

**LLM Observability:**
- `sum:ml_obs.span.error{env:prod}.as_count() / sum:ml_obs.span{env:prod}.as_count()` — LLM error rate
- `sum:ml_obs.span.error{env:prod,span_kind:tool}.as_count()` — tool error count

**Frontend:**
- `sum:rum.measure.session.frustration{*}.as_count()` — frustration events
- Log query: `source:wrench-frontend status:error` via `uv run puppy logs search`

For each signal, compute from the 1-week window:
- `mean`, `p95`, `max`, `latest` value
- `stddev`

Determine current state:
- **healthy**: `latest` within `mean + 1*stddev`
- **elevated**: `latest > mean + 1*stddev`
- **anomalous**: `latest > mean + 2*stddev` OR sustained error rate > 3% for > 30 min

### Step 3: Check logs for active error volume

```bash
uv run puppy logs search "status:error" --from 1h --limit 20
```

Note any services generating significant error volume that may not surface in metrics.

### Step 4: Cross-reference against open incidents

For each signal in state `elevated` or `anomalous`:

1. Check if any open incident covers this service + error type
   - Match on: service name in incident title or triage findings
   - Match on: error type keywords (e.g. "lambda", "step functions", "ai-axis", "llm")
2. Mark as:
   - **COVERED** — open incident exists for this signal
   - **UNCOVERED** — no open incident, needs one

Skip `healthy` signals entirely — no action needed.

### Step 5: Create incidents for uncovered active signals

For each `UNCOVERED` signal in `elevated` or `anomalous` state:

**Severity:**
- `anomalous` → SEV-3 (active degradation, no incident declared)
- `elevated` → SEV-4 (worth tracking, not yet critical)

```bash
uv run puppy incident create \
  --title "<Signal name> showing elevated values — no incident declared" \
  --severity <SEV-3|SEV-4>
```

Then update with structured fields:
```bash
uv run puppy incident update <id> \
  --summary "Dashboard health review detected <signal> in <group> is <elevated|anomalous> with no open incident. Latest: <value>, mean: <value>, p95: <value>." \
  --root-cause "Unknown — detected by dashboard health review. Requires investigation." \
  --triage-findings "1-week stats: mean=<v>, p95=<v>, max=<v>, latest=<v>, stddev=<v>. State: <elevated|anomalous>. No matching open incident found at time of review." \
  --needs-monitoring yes \
  --needs-human-attention yes \
  --triage-completed no \
  --teams <development|front-end> \
  --services <service>
```

Add todo:
```bash
uv run puppy incident todo add <id> \
  --content "Investigate <signal> — dashboard health review flagged elevated values with no declared incident. Check logs and spans for root cause." \
  --assignee "@willem@wrench.ai"
```

### Step 6: Output health report

```
Dashboard Health Review — <timestamp>
======================================

Dashboard: Platform Health Dashboard (d7y-q4z-dye)
Window: last 1h vs 1w baseline
Open incidents checked: <N>

Signal state:
  Healthy:   <N>
  Elevated:  <N>
  Anomalous: <N>

Coverage:
  Covered by open incident:   <N>
  UNCOVERED — needs attention: <N>

Uncovered signals:
  - <signal>: <state> (latest=<v>, mean=<v>) — incident <id> created
  - <signal>: <state> — already covered by incident <id>

All healthy signals: OK
```

## Key Rules

- Only flag `elevated` or `anomalous` signals — do not create incidents for healthy metrics
- Always check open incidents before creating — do not duplicate
- `triage-completed: no` on these incidents — they need real investigation, not just a gap note
- Do not specify notification channels in any output — that is a human decision
- If all signals are healthy and covered: output "Platform health: all clear" and stop
- Dry run: print the health report without creating any incidents

## When to Run

- Daily as part of standup prep (gives you a platform health snapshot)
- After any deployment (check for new signals)
- When a PagerDuty or Slack alert fires (run to get full context)
- On demand: "check dashboard for active issues"

---
name: datadog-triage
description: >
  Single-incident triage skill for Datadog Incident Management. Investigates one incident
  using Datadog logs, traces, monitors, and GitHub source code review. Produces a complete
  13-field triage schema including blast radius, duplicate assessment, and stable-since timestamp.
---

# Datadog Triage Skill

Investigates a single Datadog incident. Uses Datadog data and GitHub source code together.
Produces a complete 13-field schema. Does not speculate beyond available evidence.

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

## Input Contract

Required:
- `incident_id`: Datadog incident numeric ID

Optional:
- `time_window`: lookback window for logs and spans (default: "6h")
- `known_incidents`: list of other open incident IDs and titles (for duplicate detection)

## Output Contract

A complete 13-field triage schema in markdown format.

## Workflow

### Step 1: Fetch incident details

```bash
uv run puppy incident get <incident_id>
```

Extract: title, status, severity, description, affected services, created timestamp,
stable-since timestamp (if available), commander, responders.

**Extract the full Datadog URL**: `https://us5.datadoghq.com/incidents/<numeric_id>`

Use the numeric ID from the URL, not the hash. This URL is the canonical reference
for this incident throughout the schema.

### Step 2: Check for existing todos and prior triage

```bash
uv run puppy incident todo list <incident_id>
```

If there are completed todos: read them to understand what was already tried and confirmed.
If there are unassigned (AI) todos: note them — they may contain prior findings.

### Step 3: Investigate LLM traces

```bash
uv run puppy llm traces --limit 500 --from <time_window> --mode error
```

If empty:
```bash
uv run puppy llm traces --limit 500 --from <time_window> --mode irrelevant
```

Extract: error count, tool names, error types, service names, time clustering.
Note whether errors are bursting, sporadic, or have stopped entirely.

### Step 4: Search logs

For each affected service:
```bash
uv run puppy logs search "service:<service_name> status:error" --from <time_window> --limit 20
```

Extract: error patterns, total count, timestamps, rate (errors per hour), 4xx vs 5xx,
stack traces, caller IPs, user IDs if present.

**Blast radius assessment from logs:**
- Single internal IP or service → "internal only, single caller"
- Specific user IDs → "N affected users"
- No user context, burst and stopped → "isolated burst, no confirmed user impact"
- Widespread errors across sessions → "broad user impact, estimate N affected"

### Step 5: Check monitors

```bash
uv run puppy monitor list --state Alert --limit 20
```

Extract monitors matching the incident's service and error type. Note if monitors
have since recovered (indicates the issue may have resolved itself).

### Step 6: GitHub source code review

Search the relevant repository for the affected service (wrench-frontend, web-app-api,
ai-axis, cloud-api) for:

1. Recent commits or PRs touching the code path in the error stack trace
2. Known fixes or guard conditions related to the error type (e.g., ON CONFLICT guards,
   null checks, permission validation)
3. Any TODO, FIXME, or known issue comments near the failing code
4. Whether the fix already exists in a branch or PR that has not been deployed

```bash
# Recent commits to the affected service
uv run puppy github commits <repo> --since <time_window> --service <affected_service>
```

Or search GitHub directly for the error class / method name in the relevant repo.

Note: if a fix exists but is not deployed, that changes the Next Steps significantly
(human merges PR vs human writes fix).

### Step 7: Assess blast radius and determine SEV

**Blast radius first, then SEV:**

Blast radius categories:
- `internal-only`: errors from internal services, no user-facing impact
- `single-user`: one user or one session affected
- `small`: <10 users or <1% of traffic
- `moderate`: 10-100 users or 1-10% of traffic
- `large`: >100 users or >10% of traffic or critical path down

SEV mapping:
- **SEV-1**: Large blast radius, critical path down, all or most users affected
- **SEV-2**: Moderate blast radius, major feature broken for a significant user segment
- **SEV-3**: Small blast radius, feature degraded for a limited set of users
- **SEV-4**: Internal-only or single-user, workarounds exist, or burst that has stopped
- **SEV-5**: Cosmetic, no functional impact
- **UNKNOWN**: Insufficient data to assess

A burst of 14 errors from one internal IP that stopped 65h ago is SEV-4, not SEV-3.
A JWT error affecting a single user is SEV-4, not an auth system incident.
Do not inflate SEV based on error presence alone — blast radius is the primary signal.

### Step 8: Check for duplicates

Compare this incident's root cause, error type, and affected service against
the `known_incidents` list (if provided) and any recently resolved incidents.

An incident is a duplicate if:
- Same service, same error type, same root cause as an open incident
- Same internal caller IP or service identity as another incident
- Clearly a sub-symptom of a broader open incident

If duplicate: mark schema `Is Duplicate: yes`, reference the canonical incident URL.
Do not continue full triage — return the duplicate assessment and canonical reference.

If the canonical incident is resolved: this is NOT a duplicate — it is a new occurrence.
Proceed with full triage.

### Step 9: Determine root cause

**Client errors (4xx)**: "Client misconfiguration — caller <name> sending invalid requests" → resolved

**ToolNotRelevantException**: "Tool logic flagged input as irrelevant" → stable

**Burst that has stopped, no recurrence**:
- Check how long ago the last error was
- If >48h clean: root cause may be self-resolved or transient; status → resolved or stable
- Note the burst characteristics (single caller, scheduled job pattern, etc.)

**Timeout/degradation**: check GitHub for recent deployment, check monitors for saturation

**Hard errors (5xx)**: exception type from stack trace if visible

**If inconclusive**: "Requires investigation — <specific what is unknown>" → stable

### Step 10: Build triage findings

Summarize with numbers: total error count, rate, affected services, caller identity if
known, peak timestamps, when errors stopped (if they did), GitHub findings.

Must be specific enough to justify the severity and root cause assignments.

### Step 11: Determine status

- **resolved**: errors stopped, blast radius confirmed small or zero, root cause known
- **stable**: errors stopped but root cause unconfirmed, or fix deployed but not yet verified
- **active**: errors ongoing or blast radius significant and unresolved

If stable: set Stable Since to the timestamp when errors stopped or when the incident
was last declared stable.

### Step 12: Build Next Steps

Rules:
- [AI] steps: recurrence checks, log monitoring, auto-resolution after N hours clean
- [HUMAN] steps only for: merging a PR, deploying a fix, making a product decision,
  granting access, creating a separate incident, external communication
- Do not assign [HUMAN] to investigation tasks — those are [AI] work
- Maximum 3 next steps total; if the incident is resolved, 0-1 steps

If a code fix exists in a branch: [HUMAN] merge + deploy, then [AI] monitor and resolve.
If no fix exists and it is an internal-only low-blast burst: [AI] monitor and auto-resolve.
If root cause requires code investigation: [AI] checks the code, not [HUMAN].

### Step 13: Output 13-field schema

```
Title:             <clean title, no status prefix>
User Impact:       <specific: who, what they cannot do, or "no user-facing impact">
Blast Radius:      <internal-only | single-user | small N | moderate N | large N | unknown>
Github URLs:       <PR/commit URLs or "none">
Datadog URL:       https://us5.datadoghq.com/incidents/<numeric_id>
Team:              <development | front-end>
Status:            <active | stable | resolved>
Severity:          <SEV-1 through SEV-5 or UNKNOWN>
Root Cause:        <specific — not "unknown" for resolved>
Affected Services: <comma-separated>
Triage Findings:   <counts, rates, timeline, source code findings>
Needs Monitoring:  <yes — what to watch and for how long | no>
Next Steps:        <numbered, [AI] or [HUMAN], 3 max, specific>
Stable Since:      <YYYY-MM-DD HH:MM UTC | N/A>
```

## Error Handling

- 404 on incident get: "Incident not found — check incident ID"
- All outputs empty: mark resolved, root cause "Service appears healthy, no errors found"
- GitHub unreachable: note in findings, continue with Datadog data only
- No LLM traces: note in findings, rely on log and monitor data

## Key Rules

- Blast radius determines SEV — not error presence or monitor state alone
- User Impact is never blank — minimum is "no confirmed user-facing impact"
- Source code review is mandatory for active and stable incidents
- Duplicate check before full triage — saves work if it's already covered
- Burst that stopped >48h ago with no recurrence → resolved unless root cause is unconfirmed
- [HUMAN] todos only for actions a human must physically take
- No speculative next steps — only steps justified by evidence

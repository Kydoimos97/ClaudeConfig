---
name: handle-single-incident
description: >
  Full handling of one Datadog incident: execute any pending AI todos, run investigation,
  apply behavioral decision rules, merge duplicates, and apply updates. Returns a concise
  outcome summary. Beebop orchestrates the loop across all incidents — this skill handles
  exactly one but is cross-incident aware for merging and deduplication.
---

# Handle Single Incident Skill

You own this incident. Your job is to drive it to its correct final state — resolved,
stable with a clear owner and next step, or merged into a canonical incident. You are
not a reporter. You do not list. You decide and act.

Target state across the full run: 0 active, 1-3 stable. Every incident you touch should
move closer to that state. If it can be resolved — resolve it. If it can be merged — merge
it. If it genuinely needs human action — figure out exactly what that action is from git
before assigning it.

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
- `known_incidents`: list of other open incident IDs, titles, services, and error types
  for duplicate detection and merge candidates — provide this whenever other incidents exist
- `merge_candidates`: specific incident IDs that the router flagged as likely related to
  this one — check these first before full investigation
- `time_window`: lookback for logs and traces (default: `6h`)

## Output Contract

```
Incident <id> — <title>
Decision:   <resolved | stable | active | merged into #<id> | duplicate of #<id>>
SEV:        <SEV-N or UNKNOWN>
Blast:      <blast radius category>
Root Cause: <one sentence — specific, no "requires investigation" for resolved>
AI Todos:   <N> completed this run | <N> pending for next run
Human Todo: <specific fix identified from git — or "none">
Action:     <exactly what was applied in Datadog>
```

## Workflow

### Step 1: Handle feature requests immediately

Check the incident type and title. If this is a feature request (`[FR]`, "Feature:",
"feature request", "enhancement", or incident type `feature_request`):

```bash
uv run puppy incident update <incident_id> \
  --status resolved \
  --severity SEV-5 \
  --summary "Feature request — not an incident. Tracked separately."
```

Mark all open todos complete. Return outcome summary. Stop — do not proceed.

Feature requests are not incidents. Close them on contact.

### Step 2: Check merge candidates first

If `merge_candidates` was provided, check each one before doing any investigation:

```bash
uv run puppy incident get <candidate_id>
uv run puppy incident todo list <candidate_id>
```

Two incidents should be merged if they share:
- Same service AND same error type or exception class
- Same internal caller IP or service identity
- Same root cause (significant description overlap)
- Time-correlated creation (within 30 minutes, same service)

**If this incident should be merged into a candidate:**

Designate the older or more complete incident as canonical. Resolve this incident as
a duplicate of the canonical:

```bash
uv run puppy incident update <incident_id> \
  --status resolved \
  --is-duplicate yes \
  --summary "Merged into canonical: https://us5.datadoghq.com/incidents/<canonical_id> — same root cause: <reason>"
```

Mark all open todos on this incident complete. Transfer any unique findings or todos
to the canonical incident before closing. Return outcome summary. Stop.

**If the candidate should be merged into this incident instead:**

This incident becomes canonical. Note the candidate ID — Beebop will handle the
candidate when it processes that incident in the loop.

### Step 3: Execute pending AI todos

```bash
uv run puppy incident todo list <incident_id>
```

Find all unassigned todos. These are pending AI tasks from prior runs. Execute each
one fully — do not skip, do not defer:

- **Recurrence check**: search logs for the error pattern since the todo was created.
  If zero recurrence: mark complete with "no recurrence confirmed since <date>."
  If recurrence found: note count, timestamps, and rate. Mark complete with findings.
- **Resolution confirmation**: check if symptoms are still present in logs and traces.
- **Duplicate verification**: confirm canonical incident is still open and unresolved.
  If canonical is resolved: this is a new occurrence, not a duplicate — re-triage.
- **Log/trace check**: run the exact query described in the todo text. Return findings.
- **Code investigation**: search GitHub for the error class, method, or stack trace.

Mark each todo complete after executing it:

```bash
uv run puppy incident todo complete <incident_id> --todo-id <todo_id>
```

If zero recurrence confirmed for >48h across all pending checks: flag for resolution.
Confirm with fresh triage in Step 4, then resolve in Step 6.

### Step 4: Investigate

Run the full `datadog-triage` workflow for this incident.

Pass `known_incidents` for duplicate detection during investigation.
Use `time_window` for log and trace lookback.

**Git check is mandatory for any active or stable incident.** Before completing
the investigation, search the relevant GitHub repository for:

1. Recent commits or PRs touching the code path in the error stack trace
2. Known fixes, guard conditions, or ON CONFLICT clauses related to the error type
3. Any branch or PR with a fix that has not been deployed yet
4. TODO, FIXME, or known issue comments near the failing code

```bash
uv run puppy github commits <repo> --since 7d
```

Or search GitHub directly for the exception class or failing method name.

If a fix exists in a branch that is not deployed: the [HUMAN] todo is "merge and deploy
PR #<N>" — not "investigate the issue." The AI has already done the investigation.

If no fix exists: the [HUMAN] todo must describe exactly what code change is needed,
which file, and what the fix should do. "Investigate X" is not a valid human todo.

Produces a complete 13-field triage schema.

If confirmed duplicate during triage: go to Step 7 (duplicate resolution).

### Step 5: Apply behavioral decision rules

Given the triage schema and git findings, determine the final action:

**Resolve immediately:**
- Zero recurrence confirmed for >48h (from Step 3 or fresh triage)
- Burst stopped, single internal caller, no user-facing impact, root cause identified
- Status already resolved in Datadog and no new errors detected
- Client misconfiguration (4xx errors from a single caller) — close as client-side issue

**Stable (monitoring period):**
- Fix deployed but not yet verified — set stable, schedule [AI] recurrence check in 24h
- Root cause identified but fix not yet in a PR — set stable, [HUMAN] create fix
- Errors stopped but root cause genuinely unconfirmed and blast radius was non-trivial

**Escalate to active:**
- New errors detected since it went stable
- Blast radius is larger than previously assessed
- AI todo found recurrence during Step 3

**Force-close:**
- Stable >72h, root cause unresolved, no action taken, no recurrence — stop carrying it
  Resolution note: "Force-closed: stable >72h, no recurrence confirmed, no action needed."
- Todos from previous runs never executed and incident has had no errors for >72h — same

**SEV rules:**
- Blast radius is the primary signal — not error presence, not monitor state alone
- `internal-only` or `single-user` burst that stopped = SEV-4 at most
- Do not inflate SEV because a monitor fired or the error message looks scary

**[HUMAN] todo rules — strict:**
- Only for: merge a PR, deploy a fix, make a product decision, grant access, external action
- Every [HUMAN] todo must include the specific action: file, PR number, or exact change needed
- "Investigate", "check", "monitor", "look at" are never [HUMAN] — those are [AI] work
- Before creating a [HUMAN] todo: git check is done and the fix is identified

**[AI] todo rules:**
- Recurrence checks, log monitoring, auto-resolution after N hours clean
- Code investigation before a fix can be identified
- Verification after a human action is taken
- Maximum 2 [AI] todos — if you need more, the incident is not specific enough

### Step 6: Apply updates

Run the `incident-updater` workflow with the triage schema and Step 5 decisions.

Includes:
- Bot account reassignment: `dataengineering@wrench.ai` → `willem@wrench.ai` first
- Title formatting: `[Resolved]`, `[Stable]`, or clean for active
- Core fields: status, severity
- Structured fields: root cause, blast radius, triage findings, todos, impacts, attachments
- Todo deduplication: never create a todo that already exists with the same action and target
- Validate all existing todos: if a todo was created by a previous run and has never been
  executed and the incident is being resolved — mark it complete before closing

### Step 7: Duplicate resolution

If this incident is confirmed a duplicate of an open canonical incident:

```bash
uv run puppy incident update <incident_id> \
  --status resolved \
  --is-duplicate yes \
  --summary "Resolved as duplicate of https://us5.datadoghq.com/incidents/<canonical_id> — <shared root cause in one sentence>"
```

Transfer any unique triage findings or todos to the canonical incident that aren't
already there. Mark all open todos on this incident complete. Do not create new todos.

### Step 8: Return outcome summary

Return the Output Contract block. One block per incident. No narration. No lists of
things you noticed. If you have a concern about the canonical data quality or a pattern
across incidents that Beebop should know about, add one line: `Note: <specific concern>`.

## Key Rules

- You own the incident — drive it to its correct state, do not describe it
- Feature requests are closed on contact, not triaged
- Merge candidates are resolved before full investigation — save the work
- Execute all pending AI todos before investigating — prior work runs first
- Git check is mandatory before any [HUMAN] todo is created
- [HUMAN] todos require a specific identified fix — not investigation tasks
- Blast radius drives SEV — not error presence or monitor state alone
- Stable >48h zero recurrence = resolve, do not defer to next run
- Stalled stable >72h with no action = force-close with explanation
- Existing todos from prior runs that were never executed: validate them on contact,
  mark stale ones complete if the incident is being closed
- [AI] todos are always unassigned — they are the next-run task queue, not human tasks
- Bot account reassignment is always the first update applied
- Target state: 0 active, 1-3 stable — every action should move toward this

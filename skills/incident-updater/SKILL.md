---
name: incident-updater
description: >
  Incident updater skill for Datadog Incident Management. Takes a completed 13-field triage
  schema and applies it to Datadog. Deduplicates todos before creating, reassigns bot account
  items, handles duplicate incident resolution, and keeps AI todos unassigned.
---

# Incident Updater Skill

Applies a triage schema to Datadog cleanly. Deduplicates, reassigns bot items,
handles merges, and never creates [AI] todos as assigned human tasks.

## Input Contract

Required:
- `incident_id`: Datadog incident numeric ID
- `triage_schema`: Complete 13-field triage output (markdown format)

Optional:
- `duplicate_of`: numeric incident ID if this incident is being resolved as a duplicate
- `mark_todos_complete`: list of todo IDs to mark complete before adding new ones

## Output Contract

```
Incident <id> updated.

Fields:    OK
Todos:     <N> created, <N> skipped (duplicate), <N> marked complete
Impacts:   <N> created | skipped
Attachments: <N> created

Verification: verified | failed — <reason>
```

## Workflow

### Step 1: Handle duplicate resolution

If `duplicate_of` is provided:

```bash
uv run puppy incident update <incident_id> \
  --status resolved \
  --is-duplicate yes \
  --summary "Resolved as duplicate of https://us5.datadoghq.com/incidents/<duplicate_of>"
```

Mark all existing open todos on this incident as complete. Do not create new todos.
Output confirmation and stop — do not proceed with remaining steps.

### Step 2: Validate triage schema

Parse and extract all 13 fields.

**Information gates — reject if any fail:**
- Title must be non-empty
- Status must be one of: `active`, `stable`, `resolved`
- Severity must be one of: `SEV-1` through `SEV-5` or `UNKNOWN`
- If status is `resolved`: Root Cause must not contain "unknown", "unclear", or "requires investigation"
- User Impact must be non-empty
- Blast Radius must be non-empty
- Next Steps must be non-empty unless status is resolved with no follow-up needed

If any gate fails: output failure and stop. Do not apply partial updates.

### Step 3: Mark completed AI tasks

If `mark_todos_complete` list is provided:

```bash
uv run puppy incident todo complete <incident_id> --todo-id <todo_id>
```

Mark each listed todo as complete before proceeding.

### Step 4: Fetch existing todos (deduplication check)

```bash
uv run puppy incident todo list <incident_id>
```

Store the text of all existing todos. Use this to skip creating new todos that are
substantially identical to existing ones (same action, same target, same condition).

Similarity check: if an existing todo contains the same key verb + target
(e.g., "monitor cloud-api logs for PermissionError") — skip the new todo, do not duplicate.

### Step 5: Check and fix bot account assignment

```bash
uv run puppy incident get <incident_id>
```

If incident commander is `dataengineering@wrench.ai`:
```bash
uv run puppy incident update <incident_id> --commander willem@wrench.ai
```

If incident is unassigned or assigned to `dataengineering@wrench.ai`:
```bash
uv run puppy incident update <incident_id> --assignee willem@wrench.ai
```

### Step 6: Format title

Keep clean — root cause goes in the `root_cause` field, not the title.

- resolved: `[Resolved] <title>`
- stable: `[Stable] <title>` (only if not already prefixed)
- active: `<title>` (strip any existing prefix)

### Step 7: Update core fields

```bash
uv run puppy incident update <incident_id> \
  --title "<formatted_title>" \
  --status <status> \
  --severity <severity>
```

### Step 8: Update structured fields

```bash
uv run puppy incident update <incident_id> \
  --summary "<user_impact> | Blast radius: <blast_radius>" \
  --root-cause "<root_cause>" \
  --triage-findings "<triage_findings>" \
  --detection-method <monitor|customer|employee|unknown> \
  --needs-monitoring <yes|no> \
  --needs-human-attention <yes if any [HUMAN] steps | no> \
  --triage-completed yes \
  --is-duplicate no \
  --teams <team_lowercase> \
  --services <each_affected_service>
```

If GitHub URLs present:
```bash
uv run puppy incident update <incident_id> --github-refs "<urls>"
```

### Step 9: Create todos

For each Next Step, check deduplication list first (Step 4). Skip if substantially identical.

**[AI] steps — unassigned (no --assignee flag)**:
```bash
uv run puppy incident todo add <incident_id> \
  --content "<step text>"
```

**[HUMAN] steps — assigned to willem**:
```bash
uv run puppy incident todo add <incident_id> \
  --content "<step text>" \
  --assignee "@willem@wrench.ai"
```

[AI] todos have no assignee. This marks them as the AI's task queue for the next run.
Never assign [AI] todos to a human.

### Step 10: Create attachments

For each GitHub URL:
```bash
uv run puppy incident attachment add <incident_id> \
  --url "<url>" --title "<PR/commit title>" --type link
```

For each Datadog URL (not the incident URL itself):
```bash
uv run puppy incident attachment add <incident_id> \
  --url "<url>" --title "<descriptive title>" --type link
```

### Step 11: Create impact record

Only create if User Impact describes real end-user disruption — not internal-only,
not single-request, not a burst that stopped with no user-facing consequences.

If Blast Radius is `internal-only` or `single-user` with no functional user impact: skip.

If customer-impacted:
```bash
uv run puppy incident impact add <incident_id> \
  --description "<user_impact>" \
  --start "<detected timestamp>" \
  --end "<resolved timestamp if resolved>"
```

### Step 12: Verify

```bash
uv run puppy incident get <incident_id>
uv run puppy incident todo list <incident_id>
```

Confirm title, status, severity match schema. Confirm todos were created as expected.

## Error Handling

- Rate limit (429): stop, output "Rate limited — retry in 60 seconds"
- Not found (404): stop, output "Incident <id> not found"
- Auth failure: stop, output "Authentication failed"
- Gate failure: stop before any API calls, output which gate failed and why
- Todo/attachment failure: log and continue with remaining items (non-fatal)

## Key Rules

- Deduplicate todos before creating — never add a todo that already exists
- [AI] todos are always unassigned — they are the AI task queue, not human assignments
- [HUMAN] todos only for genuine human actions (merge, deploy, decide, external)
- Bot account (`dataengineering@wrench.ai`) is always reassigned before any other update
- Duplicate incidents are resolved immediately with a reference to the canonical
- User Impact and Blast Radius always go into the summary field together
- All-or-nothing on gate validation — partial updates are not applied

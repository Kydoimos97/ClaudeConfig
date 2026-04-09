---
name: update-notion
description: >
  Cross-reference completed GitHub work against the Projects & Priorities
  Notion database. Finds matching projects, audits status and GitHub
  references, proposes updates (with user approval per project), executes
  approved changes, and posts a summary of all changes to the #notes Slack
  channel.
---

# Update Notion Skill

Keeps the Projects & Priorities Notion database in sync with completed GitHub work.

## Trigger

User says anything like:
- "update notion"
- "sync notion with my work"
- "update project statuses in notion"
- "add my PRs to notion"

## Context Required

This skill operates on work already established in the conversation — either
from a standup summary run earlier in the session, or from GitHub PR data the
user has described. If neither is present, ask the user to run the standup
summary skill first or describe what was done.

## Notion Database

- Database URL: https://www.notion.so/wrench-ai/9a835b1b37f749a39732e44453af83ed
- Data Source ID: `collection://a00de035-0465-403e-a479-0ff6ffe798cb`
- User: Willem van der Schans — `user://d278f4c3-48c6-43b8-941a-e430e58ed0b4`

## Slack Channel

- #notes channel ID: `C05E80TPJ9F`

---

## Procedure

### Step 1 — Establish work context

Collect the list of PRs and changes from the current session. If `AgentMemory.md`
or a standup summary from this session already captures the work, use that
first. Otherwise, run:

```
usePwsh7 Git-DailySummary
```

Extract: repo, PR number, PR title, state (merged/open), and a one-line
description of what it does.

---

### Step 2 — Find matching Notion projects

For each distinct theme in today's work (e.g. billing, frontend feature,
backend migration, internal cleanup), search Notion:

```
notion-search  query="<theme keywords>"  data_source_url="collection://a00de035-0465-403e-a479-0ff6ffe798cb"
```

Use 2-4 keyword searches to cover all areas. Prefer recently updated pages
(timestamp "Past day" or "1 day ago") as the most likely matches.

For each candidate page, fetch its full state:

```
notion-fetch  id="<page_url_or_id>"
```

Note for each project:
- Current `Project Status`
- Existing GitHub URLs or PR references in the body
- Date range (`date:Dates:start` / `date:Dates:end`) — is it stale?
- Whether a sub-task would better represent in-flight progress

---

### Step 3 — Audit and build proposal

For each project matched, determine what needs updating. Apply these rules:

**Status:**
- PR merged → status should be `In Progress` (if more work remains) or `Done`
  (if the project is complete). Use judgment based on PR scope vs project scope.
- PR open → status should be `In Progress`. Do not change to Done.
- Never downgrade a status (e.g. do not set In Progress → Backlog).

**GitHub references:**
- If the page body has no GitHub PR links for today's work, add them.
- Add links as a `## GitHub PRs` section at the top of the body, one bullet
  per PR: `- RepoName #number — title (STATE)\n  <url>`
- If a `## GitHub PRs` section already exists, append missing entries only.

**Dates:**
- If `date:Dates:end` is in the past and the project is still active, extend
  it by 30 days from today.
- Do not change start dates.

**Sub-tasks:**
- If a project is large and ongoing (e.g. billing, a multi-phase feature),
  and today's work represents meaningful progress on one slice of it, create
  a sub-page under the project page documenting:
  - What was done
  - Which PRs (with URLs)
  - A short prod verification checklist (if applicable)
- Title format: `<Theme> — YYYY-MM-DD`

---

### Step 4 — Present proposal and get approval

Present all proposed changes as a numbered list before making any edits.
Group by project. For each, state:
- Project name and ID
- What you propose to change and why
- Whether it's a property update, body edit, or new sub-page

Wait for the user to approve each item. The user may say "go ahead" for all,
or approve/decline individual items.

Do not make any Notion changes before receiving approval.

---

### Step 5 — Execute approved changes sequentially

For each approved change, execute one at a time and confirm success before
moving to the next.

**Updating page properties:**
```
notion-update-page  page_id="<id>"  command="update_properties"
  properties={"Project Status": "...", "date:Dates:end": "YYYY-MM-DD", ...}
```

**Adding GitHub PR references to body:**
```
notion-update-page  page_id="<id>"  command="update_content"
  content_updates=[{"old_str": "<existing anchor text>", "new_str": "<new section + original text>"}]
```

Always fetch the page first to get the exact `old_str` to match.

If a `## GitHub PRs` section already exists, append to it:
```
content_updates=[{"old_str": "- last existing PR bullet", "new_str": "- last existing PR bullet\n- NewRepo #N — title (STATE)\n  <url>"}]
```

**Creating a sub-page:**
```
notion-create-pages  parent={"type": "page_id", "page_id": "<parent_id>"}
  pages=[{"properties": {"title": "<Title — YYYY-MM-DD>"},
          "content": "## Summary\n...\n## PRs\n...\n## Status\n- [ ] ..."}]
```

---

### Step 6 — Post Slack summary to #notes

After all changes are complete, send a single message to #notes
(channel ID: `C05E80TPJ9F`) summarising what was updated.

Format:

```
*Notion updated — <today's date>*

<one bullet per project changed>
- *MAI-NNN — Project Name*: <what changed> — <Notion URL>

<one bullet per sub-page created>
- New sub-page: *<Sub-page Title>* under MAI-NNN — <Notion URL>
```

Keep it tight — one line per change. This is a log entry, not a narrative.

---

### Step 7 — Quality check

Before finishing, verify:
- Every PR from today's work that has a matching Notion project has a GitHub
  reference in that project's page.
- No project was left with a stale end date if it is still active.
- The Slack message was sent successfully (tool call returned a message link).
- No changes were made that the user did not approve.

If any project from the work list had no Notion match, report it explicitly
so the user can decide whether to create one or leave it without a project entry.

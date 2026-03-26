---
name: standup-summary
description: >
  Generate a structured daily standup summary from GitHub activity and any
  manually provided context. Runs Git-DailySummary via usePwsh7, deep-reads
  a sample of today's PRs from GitHub, and outputs a formatted brief with
  Main Points, Merged Work, Created PRs, Reviews, and Other sections plus
  a full URL index at the bottom. If no non-git context was provided,
  asks the user before finalising.
---

# Standup Summary Skill

Produces a next-day standup brief from today's GitHub activity.

## Trigger

User says anything like:
- "summarize my day"
- "write my standup"
- "standup summary"
- "what did i do today"

## Procedure

### Step 1 — Collect git activity

Run:

```
usePwsh7 Git-DailySummary
```

Capture the full output. Note the date it reports (top of output).

### Step 2 — Deep-read a sample of PRs

From the PRs Opened Today list, select up to 6 PRs that look most
substantive (prefer large line counts, prefer merged/closed over open).

For each selected PR, fetch the title and body from GitHub:

```
gh pr view <NUMBER> --repo <ORG/REPO> --json title,body,state,mergedAt,additions,deletions
```

Use the body text to enrich the summary — extract the actual feature
description, customer impact, or fix rationale. Do not quote the body
verbatim; synthesise it into one tight sentence per PR.

### Step 3 — Check for non-git context

If the user's message included non-git items (subscriptions, Datadog
connectors, tool configs, meetings, decisions, etc.) — incorporate them
directly into the Other section.

If the user did NOT mention any non-git items, ask exactly this before
proceeding:

> "Did you do anything today outside of GitHub — subscriptions, tool
> configs, meetings, decisions, or ops work?"

Wait for the answer. If they say no or nothing relevant, skip the Other
section. If they provide items, incorporate them.

### Step 4 — Output the standup

Use the format below. Do not add emoji. Keep bullets tight — one line each.
All PR titles should be truncated at ~60 chars if needed.

---

**Standup — [NEXT DAY DATE]**

**Main Points**
- [2-4 bullets capturing the highest-signal themes of the day — what
  moved the needle, what shipped, what is still in flight]

**Merged Work**
- `repo-name` — PR title (#number) [brief enriched sentence from PR body]

**Created PRs**
- `repo-name` — PR title (#number) — [OPEN / MERGED on merge]

**Reviews**
- `repo-name` #number — [APPROVED / CHANGES REQUESTED / COMMENTED]

**Other**
- [Non-git items, one per bullet. Omit section if empty.]

**Evaluation**
[3-5 sentences. Assess the day honestly across these dimensions:
output volume, focus (did work stay coherent or scatter?), quality
signals (test coverage, review feedback, clean merges vs messy PRs),
momentum (did things land or stall?), and anything that slowed progress.
If it was a strong day, say so plainly — do not manufacture caveats.
If there were real friction points, name them without dramatising.
Write in plain prose, not bullets.]

**URLs**
[Group by repo. One per line. Full GitHub URL.]

WrenchAI/repo-name:
  #number  https://github.com/WrenchAI/repo-name/pull/number
  ...

---

### Step 5 — Write the summary to disk

Target path:

```
C:\Users\willem\Documents\WrenchProjects\Notes\Standups\YYYY-MM-DD-work-summary.md
```

Where `YYYY-MM-DD` is **today's** date (the day being summarised, not tomorrow).

Before writing, use the Read tool to check whether the file already exists.

- **File does not exist** — use the Write tool to create it.
- **File exists** — use the Read tool to load the current contents, then use
  the Edit tool to merge changes in. Do not clobber existing content. Apply
  these merge rules:
  - New PRs, commits, or reviews not already listed → append to the
    relevant section.
  - Items already present → leave untouched; do not duplicate.
  - Other section items provided this session → append any that are not
    already listed.
  - Main Points → rewrite to reflect the full combined picture.
  - URLs section → add any missing entries; do not remove existing ones.

Confirm the file path and whether it was created or updated to the user after writing.

### Step 6 — Write the Evaluation section

After all other sections are complete, write the Evaluation section.
Use the PR bodies, commit list, line counts, and merge/review outcomes
from Steps 1–2 as evidence. Assess across these dimensions:

- **Volume** — how much shipped vs how much was opened and left in flight?
- **Focus** — did the day stay on a coherent theme or scatter across too many concerns?
- **Quality signals** — test coverage added, review feedback addressed, clean merges?
- **Momentum** — did work land or stall? Any blockers surface?
- **Friction** — anything that cost more time than it should have?

Be honest. A strong day should be called a strong day. A scattered day
should be named as such. Do not inflate or deflate — the Evaluation is
for personal reflection, not performance review.

Write 3-5 sentences of plain prose. No bullets.

If the file already exists and has an Evaluation section, rewrite it
to reflect the complete picture from this session's data.

### Step 7 — Quality check before emitting

- Main Points must reflect what actually happened, not just restate PR titles.
- Merged Work must use the enriched sentence from Step 2, not the raw PR title.
- Every PR that appeared in the git summary must appear in either Merged Work
  or Created PRs — none should be silently dropped.
- The URLs section must be complete and grouped by repo.
- The date in the header must be tomorrow's date (standup is read the next morning).

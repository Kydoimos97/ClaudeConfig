---
name: pull-request
description: >
  Manage an existing pull request, or create a new Pull request. For either monitor CI until completion, and address all review
  comments (Copilot and human) by either committing fixes or explaining
  non-applicability — leaving every thread resolved.
---

# Pull Request Skill

You own or inherit a PR from creation to green. Your job is to open it, keep it moving,
and drive every unresolved thread/comment to a resolved state. You do not stop at "PR
created." You're finished when CI is green and every review thread is resolved. 
While working on a pr mark it as a draft until you're done.

## Tool model

Main runs all `git` and `gh` commands directly via Bash.
Kiro handles diff reading, file exploration, and commit log analysis.
Ensure you checkout the correct branch when inheriting a PR before doing anything.
---

## Phase 1: Build the diff context

Before writing the PR body, gather the full picture.

```bash
git log --oneline origin/<base>..HEAD
git diff origin/<base>...HEAD --stat
```

Use Kiro to read the diff and extract:
- What changed (files, symbols, behaviour)
- Why it was needed (commit messages, issue links, prior context)
- How it was implemented (patterns used, key decisions made)
- What tests were added or modified — list them by name, not just count
- Any migration, env var, or deployment ordering requirement

Do not write the PR body until Kiro has returned its findings. The body must
reflect the actual diff, not a guess.

---

## Phase 2: Write the PR body

Write the body as a short narrative, not a form. Cover all five concerns
(what changed, why, how, tests, integration) but let them flow naturally
instead of living under rigid headers. The structure below is a guide, not
a template — adapt the shape to fit the size and complexity of the change.

**Opening paragraph** — Lead with the problem or motivation. What was broken,
missing, or needed? Ground the reader in *why this PR exists* before
describing what it does. Reference the issue, ticket, or prior PR inline
(e.g. "Closes #42" or "Follow-up to #38 which added …").

**The change itself** — Walk through what you did and how. Name the files,
functions, or APIs affected. Call out key design decisions and alternatives
you rejected. For small PRs this can be one paragraph. For larger ones,
use a short bulleted list or multiple paragraphs — but never a wall of text.

**Tests** — If tests were added or changed, weave them in naturally:
"Added `test_retry_on_timeout` and `test_max_backoff` to cover the new
retry logic." List by name, not count. If no tests were added, say why
and describe manual verification.

**Integration / deployment notes** — Only include this if there *are* steps:
migrations, env vars, deploy ordering, feature flags, dependent PRs. If
none, omit the section entirely — don't write "None."

**End-user impact** — Close with one sentence for a non-technical reader.
What does this enable or fix? If purely internal, say so: "No user-facing
change — internal refactor."

**References** — End the PR body with a `## References` section — a flat list of links to
anything related. This is the one section that always uses a header, because
reviewers scan for it. Include any of the following that exist:

- **Notion pages** — project briefs, specs, design docs, meeting notes
- **GitHub items** — issues, related PRs, discussions, prior failed attempts
- **Datadog** — Incidents, dashboards, monitors, error links, APM traces relevant to
  the change

Format as a simple list:
```
## References

- [Project brief — Retry overhaul](https://www.notion.so/...)
- #38 — prior PR that introduced the retry module
- [Datadog: timeout spike dashboard](https://app.datadoghq.com/...)
- Closes #42
```

Rules for references:
- Pull links from commit messages, the issue body, and Kiro's diff analysis.
  Don't guess — if no references exist, omit the section.
- Every `Closes #N` or `Depends on #N` that appears in the narrative should
  also appear here so there's one canonical list.
- Keep descriptions short — the link text should tell the reviewer what
  they'll find, not summarize the content.

### Anti-patterns to avoid
- Section headers like `## What`, `## Why`, `## How` — these read like a
  ticket template, not a description a human wrote.
- "This PR does various improvements…" — be specific or don't ship.
- Passive voice ("tests were added") — say who did what.
- Restating the title as the first sentence.
- An empty "Integration steps: None" section — if there's nothing to say,
  say nothing.
- Scattering links throughout the body with no central list — put them in
  References so reviewers find them in one place.
- Ensure each section is clearly demarked with a header and ended with a divider where applicable.

---

## Phase 3: Create the PR

```bash
gh pr create \
  --base <base-branch> \
  --draft \
  --head <current-branch> \
  --title "<conventional-commit-prefix>: <title under 70 chars>" \
  --body "$(cat <<'EOF'
<body>
EOF
)"
```

Capture the PR URL from the output. All subsequent steps reference this PR.



---

## Phase 4: Address review comments

After CI is green, fetch all unresolved review threads.

```bash
gh api repos/{owner}/{repo}/pulls/{pr-number}/comments
gh api repos/{owner}/{repo}/issues/{pr-number}/comments
```

For Copilot review threads, also check:
```bash
gh pr view <pr-number> --json reviews --jq '.reviews[] | {author: .author.login, state: .state, body: .body}'
```

For each unresolved thread, decide:

### Valid comment — code change required

1. Implement the fix.
2. Commit: `fix: address review comment — <short description>`
3. Push.
4. Reply to the comment thread:
   ```bash
   gh api --method POST repos/{owner}/{repo}/pulls/{pr-number}/comments/{comment-id}/replies \
     --field body="Fixed in <commit-sha>: <one sentence describing what changed>"
   ```
5. Resolve the thread/Comment via GraphQL:
   ```bash
   gh api graphql -f query='mutation {
     resolveReviewThread(input: { threadId: "<thread-node-id>" }) {
       thread { isResolved }
     }
   }'
   ```

### Not valid — comment does not apply

1. Reply to the thread with a clear explanation:
   - Why the suggestion does not apply to this context
   - What constraint, pattern, or decision makes the current code correct
   - Keep it factual — no dismissiveness
2. Resolve the thread (same GraphQL call as above).

### Copilot suggestions

Treat Copilot suggestions the same as human comments — evaluate on merit.
If the suggestion improves the code, apply it. If it does not fit the context,
explain why and resolve. Do not auto-accept or auto-dismiss.

---

## Phase 6: Mark PR as ready for review

## Phase 7: Re-check CI after fixes

Poll until all checks reach a terminal state (success, failure, skipped).

```bash
gh pr checks <pr-number> --watch
```

If `--watch` is unavailable or times out, poll manually:

```bash
gh pr checks <pr-number>
```

Wait 30 seconds between polls. Do not give up — CI can take several minutes.

**If a check fails:**

1. Identify the failing run:
   ```bash
   gh run list --branch <branch> --limit 5
   gh run view <run-id> --log-failed
   ```
2. Triage the failure via Kiro (pass the log file path).
3. If the fix is clear: implement it, commit with `fix: <description>`, push.
4. Return to the top of Phase 4 — a new run will have started.
5. If the failure is flaky or unrelated to this PR, note it and continue.

Do not mark CI as "passed" until every non-flaky check is green.

---

## Phase 8: Return outcome

```
PR: #<number> — <title>
URL: <pr-url>
Base: <base-branch>
CI: <green | failed: <check-name>>
Threads resolved: <N>
Fix commits: <N> (<list of SHAs if any>)
Integration steps: <restated from body, or "None">
```

If any thread could not be resolved (e.g. locked, requires maintainer action),
list it explicitly under `Blocked:` with the reason.

---

## Rules

- Never push directly to main or any protected branch — always use the PR branch.
- Never force-push after the PR is open — add commits instead.
- Every review comment gets a response before it is resolved — do not silently
  dismiss threads.
- The PR body is written from the diff, not from memory or assumptions.
- Integration steps are mandatory — if the diff touches migrations, schema,
  env vars, or multi-repo dependencies, they must appear in the body and in the
  Phase 7 output.
- If CI is still failing after three fix attempts on the same check, stop and
  report the failure — do not loop indefinitely.
- Resolved means the actual github status of the comment is resolved anything less is not sufficient.
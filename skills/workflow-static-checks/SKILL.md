---
name: workflow-static-checks
description: >
  Run the project's standard local validation workflow and return a compressed
  summary of failures, warnings, and likely next actions. Use for Ruff, Ty,
  pytest, and Taskfile-based checks.
---

# Workflow Static Checks

Run standard project checks and compress the output into a concise technical summary.

## Use when

- running Ruff, Ty, or targeted pytest
- running Taskfile validation tasks
- checking whether a branch passes local quality gates before a PR

## Preferred commands

Adapt to the repository. Prefer the project's established Taskfile workflow.

```bash
uv run ruff check .
uv run ty check
uv run pytest -q
task --list
task test
```

## Workflow

### Step 1 — Spawn CI watch as a background task

If a PR exists and CI is running, create a background polling task before doing anything else so you can work in parallel:

```
TaskCreate: "CI watch — <branch>"
prompt: |
  Poll `gh pr checks <pr-number> --repo <org/repo>` every 30 seconds until
  all checks reach a terminal state (success, failure, skipped).
  Loop:
    run: gh pr checks <pr-number> --repo <org/repo>
    if all terminal: exit 0 with summary of results
    else: sleep 30
  Report final check states on exit.
```

Do not wait for the task to complete. Continue to Step 2 immediately.

### Step 2 — Run local checks

Run checks and redirect output to a temp file — never load raw output into context:

```bash
uv run ruff check . > /tmp/checks_out.txt 2>&1
uv run ty check >> /tmp/checks_out.txt 2>&1
uv run pytest -q >> /tmp/checks_out.txt 2>&1
```

Check file size before reading:

```bash
ls -lh /tmp/checks_out.txt
```

- Under ~20KB: pass to Kiro to triage.
- 20KB or larger: pass to summarizer with the file path.

### Step 3 — Work on fixes

While CI runs in the background, action the local check findings:
- Fix Ruff and Ty errors first (fast, mechanical).
- Fix pytest failures in order of blast radius.
- Commit after each logical fix: `fix: <description>`.

### Step 4 — Poll CI task

Check the background CI task output:

```
TaskOutput: <task-id>
```

If checks are still running, continue local work and poll again after the next fix cycle.

When all CI checks reach terminal state:
- All green: mark PR ready if local checks also pass.
- Any failure: triage the failing run.

```bash
gh run list --branch <branch> --limit 3
gh run view <run-id> --log-failed > /tmp/ci_failure.txt 2>&1
```

Pass `/tmp/ci_failure.txt` to Kiro to triage. Fix, commit, push, return to Step 3.

### Step 5 — Stop the CI watch task

Once CI is confirmed green and local checks pass:

```
TaskStop: <task-id>
```

## Rules

- Always redirect check output to a file — never dump raw output into context.
- Always spawn the CI watch task first so local and remote checks run in parallel.
- Prefer existing Taskfile workflows when they match the requested scope.
- If checks are broad and noisy, use Kiro or summarizer to compress before reading.
- Do not mark CI green until every non-flaky check has passed.

## Output contract

## Check Summary

Ruff: <pass|fail — N errors>
Ty: <pass|fail — N diagnostics>
Pytest: <pass|fail — N failed / N passed>
CI: <green|running|failed: <check-name>>

## Findings

1. issue
2. issue

## Likely affected files

- path

## Next step

<short paragraph>

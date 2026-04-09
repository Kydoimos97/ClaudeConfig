---
name: behavioral-reference
description: >
  Quality standards, commit discipline, branch rules, and PR conventions.
  Read when you first need to commit, push, or create a PR.
---

# Behavioral Reference

## Commit Discipline

- One logical change per commit
- Conventional format: `feat:`, `fix:`, `refactor:`, `test:`, `chore:`
- Each commit leaves tests green
- Never amend existing commits — always new commits
- Push after every commit so work is visible

## Branch Rules

You own your feature branch. Commit and push freely.

**Off limits for direct commits:** `develop`, `qa`, `main`, `prod`.
Your work reaches them only through a reviewed and approved PR.

**Never merge env branches into your feature branch.** Always rebase:

```bash
git fetch origin
git rebase origin/develop
```

Resolve conflicts commit by commit.

## PR Conventions

Write the body as a short narrative, not a form. Cover: what changed, why,
how, tests, and integration/deployment notes (only if applicable).

End with a `## References` section — flat list of links to Notion pages,
related issues/PRs, Datadog items. Only include references that actually
exist.

Title format: `<conventional-prefix>: <description under 70 chars>`

## Quality Gate — Full Detail

Reject Worker output if:
- Types widened (`Any`, `dict`, `object`) instead of fixed
- `None` added to silence type errors
- Bare `except:` or `except Exception:` to hide bugs
- Warnings suppressed rather than resolved
- Unrelated files modified
- Tests skipped or disabled
- TODO comments added instead of fixing or reporting
- New dependencies added without authorization

Before accepting any result:
1. Does it solve the actual problem?
2. Is scope tight — no unrelated edits?
3. Is behavior explicit and maintainable?
4. Would you be comfortable merging this?

## Test Coverage

Patch coverage on new or modified code: **>= 90%** before PR is ready.

```bash
# Python
uv run pytest tests/unit --cov=<module> --cov-report=term-missing -q
```

Have Worker run coverage checks and report the number.

## Output Format

After every completed task:

**Result:** [one sentence — what was accomplished]
**Opinion:** [honest view on quality]
**Concerns:** [specific points, or omit if clean]

No raw diffs, full file dumps, or redundant narration.

---
name: session-memory
description: >
  AgentMemory.md format, update rules, and session lifecycle. Read at
  session start to restore context and establish the memory file.
---

# Session Memory

`AgentMemory.md` in the project root is your canonical memory across sessions
and compactions. Read it at session start. Update it continuously.

## Bootstrap

1. Check for `AgentMemory.md` in the working directory
2. If missing, create it with the template below
3. Read it fully to restore context
4. Proceed with the session

## Template

```markdown
## Todo
- [ ] item
- [x] completed item

---

## Global Notes
[YYYY-MM-DD HH:MM] Observation about project or architecture.

---

## Additional Guidance
[YYYY-MM-DD HH:MM] User said: explicit instruction to follow in this repo.

---

## Memories
[YYYY-MM-DD HH:MM] Tried X — failed because Y. Switched to Z.
```

## Update Rules

- **Always append, never replace** existing entries
- New entries prepend above older ones within each section
- Completed todos: check off (`[x]`), prune after two sessions
- **Additional Guidance** = permanent standing rules for this repo
- **Memories** = what was tried, what worked, what failed
- **Global Notes** = architecture observations, patterns found
- Include in commits when updated — it is a tracked project file
- Keep it lean — only what a fresh session genuinely needs

## What to Write

Write when something materially changes, not on a timer:
- User gives an explicit instruction → Additional Guidance
- An approach fails → Memories (include why it failed)
- A non-obvious decision is made → Memories
- Architecture insight discovered → Global Notes
- Task completed or added → Todo

## What NOT to Write

- Routine progress ("ran tests, they passed")
- Things already captured in commit messages
- Temporary state that won't matter after a restart

## Merge Conflicts

When conflicts occur on `AgentMemory.md`, consolidate both sides:
deduplicate, merge overlapping entries, leave the file leaner than
either branch had it.

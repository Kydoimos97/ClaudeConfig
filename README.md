# Claude Code Hooks Setup

This is a set of Claude Code hooks and agent instruction files that gate Bash commands before execution, fire desktop notifications, inject delegation reminders, track subagent usage, and log all activity.

## Requirements

**System dependencies:**
- Python 3.8 or later available as `python3` or `python` on PATH
- `uv` (preferred for managing Python in this setup)

**Python packages** (install once):
- `windows_toasts` — Windows desktop notifications (Windows only)
- `plyer` — Linux/macOS desktop notifications (non-Windows only)
- `tree-sitter` and `tree-sitter-bash` — command AST parsing (optional but recommended)

Install with:
```
uv pip install windows_toasts            # Windows
uv pip install plyer                     # Linux/macOS
uv pip install tree-sitter tree-sitter-bash  # all platforms (optional)
```

**Claude Code version:** Requires hook support (PreToolUse, PostToolUse, Stop, Notification, Elicitation events).

## Directory Structure

```
~/.claude/
├── README.md                          # this file
├── settings.json                      # hook wiring and permissions
├── agents/
│   ├── beebop.md                      # primary orchestrator instructions
│   ├── kiro.md                        # retrieval agent instructions
│   ├── codex.md                       # coding agent instructions
│   ├── mini.md                        # small task agent instructions
│   ├── socrates.md                    # reasoning advisor instructions
│   ├── codex-review.md
│   ├── fallback.md
│   └── incident_manager.md
└── hooks/
    ├── hook-dispatcher.sh / .py       # routes events to agent-specific instructions
    ├── claude-notify.sh / .py         # desktop notifications
    ├── command-guard.sh / .py         # Bash command gate
    ├── track-agent-tokens.sh / .py    # subagent usage logger
    ├── hook_utils.py                  # shared log utilities
    └── resources/
        ├── base_hooks.json            # default hook event config
        ├── beebop_hooks.json          # beebop-specific overrides
        ├── approved.conf              # command allowlist
        ├── blocked.conf               # command blocklist
        └── *.png                      # notification icons
```

**Logs written to:** `~/.claude/custom_logs/`
- `YYYY-MM-DD_commands.jsonl` — command-guard decisions
- `YYYY-MM-DD_tokens.jsonl` — agent delegation usage
- `YYYY-MM-DD_notif.jsonl` — notifications dispatched
- `hook_errors.jsonl` — hook errors (not rotated)

## Hooks

**hook-dispatcher** (PreToolUse / PostToolUse / Stop / Notification / Elicitation)

Reads the agent type from the hook payload and loads agent-specific instructions from `resources/{agent_type}_hooks.json` (falls back to `base_hooks.json`). If an instruction is defined for the event, it is output back to Claude Code. Currently active: Beebop's PreToolUse injects "are you sure this should be delegated?" before any tool call in a Beebop session.

**command-guard** (PreToolUse)

Gates every Bash command before execution:
1. Checks the command against `resources/blocked.conf` (regex patterns with reason text). Blocked commands are denied with the reason shown.
2. Checks against `resources/approved.conf` (plain prefixes). Fully approved commands are silently allowed.
3. Uses tree-sitter to parse compound commands and check each part individually.
4. Commands that match neither list pass through as CONTINUE (Claude Code decides).

Logs every decision to `commands.jsonl`.

**claude-notify** (Stop / PermissionRequest / Elicitation / Notification)

Shows a desktop toast notification:
- Stop → "Claude Finished" with session context
- PermissionRequest → "Approval Needed" with the tool/file/command being requested
- Elicitation → "Input Required" (MCP server waiting for user input)
- Notification → generic Claude notification

On Windows uses `windows_toasts` with a registered AUMID. On Linux/macOS uses `plyer`. Logs to `notif.jsonl`.

**track-agent-tokens** (PostToolUse — Agent tool only)

Fires when Beebop delegates to a subagent. Logs: subagent type, model, description, session ID, project path, token counts (input/output/cache read/cache creation), total tool use count, and duration in ms. Output goes to `tokens.jsonl`.

## Configuration

**approved.conf** — command allowlist

One command prefix per line. Any Bash command that starts with a listed prefix is auto-approved.

```
git
uv run
cat
ls
```

**blocked.conf** — command blocklist

One rule per line in format `pattern @@ reason`. Pattern is a Python regex matched against the full command.

```
rm\s+-rf\s+/ @@ deletes root filesystem
git push with force flag @@ force push not allowed
```

**Agent-specific hook instructions**

Create `resources/{agent_name}_hooks.json` modelled on `beebop_hooks.json`. The file maps hook event names to `{ "instruction": "text" }`. Set the instruction to `null` to disable.

Event names: `PreToolUse`, `PostToolUse`, `Stop`, `Notification`, `PermissionRequest`, `Elicitation`.

## Troubleshooting

- **No notifications on Windows:** Run `uv pip install windows_toasts`. Check `hook_errors.jsonl` for errors.
- **No notifications on Linux/macOS:** Run `uv pip install plyer`. Check `hook_errors.jsonl`.
- **command-guard not parsing compound commands:** Run `uv pip install tree-sitter tree-sitter-bash`. Without this, guard still works for simple commands.
- **Hook not firing:** Check that `settings.json` has the correct absolute path to the `.sh` wrapper for your OS.
- **All hook errors:** Check `~/.claude/custom_logs/hook_errors.jsonl`.

# Claude Code Hooks Setup

A set of Claude Code hooks and agent instruction files that gate Bash and tool calls before execution, fire desktop notifications, inject delegation reminders, and log all activity.

## Requirements

**System dependencies:**
- Python 3 available as `python3` or `python` on PATH (used by the `.sh` wrappers)

**Python packages** (install once):
- `windows_toasts` — Windows desktop notifications
- `plyer` — Linux/macOS desktop notifications

```
pip install windows_toasts   # Windows
pip install plyer            # Linux/macOS
```

**Claude Code version:** Requires hook support (PreToolUse, PostToolUse, Stop, Notification, Elicitation events).

## Directory Structure

```
~/.claude/
├── README.md
├── settings.json                      # hook wiring and permissions
├── agents/
│   └── *.md                           # agent instruction files
└── hooks/
    ├── command-guard.sh               # .sh wrapper; delegates to .py
    ├── command-guard.py               # Bash and tool permission gate
    ├── hook-dispatcher.sh
    ├── hook-dispatcher.py             # agent-aware event router
    ├── claude-notify.sh
    ├── claude-notify.py               # desktop notifications
    ├── track-agent-tokens.sh
    ├── track-agent-tokens.py          # subagent usage logger
    ├── guard-gap-analysis.py          # log analysis utility
    ├── guard-test.ps1                 # PowerShell test runner
    ├── test_hooks.py                  # hook unit tests
    ├── hook_utils.py                  # shared logging utilities
    └── resources/
        ├── commands.conf              # unified permission policy (source of truth)
        ├── commands.json              # compiled rule cache (auto-generated)
        ├── base_hooks.json            # default hook event config
        ├── beebop_hooks.json          # beebop-specific event overrides
        └── *.png                      # notification icons
```

**Logs written to:** `~/.claude/custom_logs/`
- `YYYY-MM-DD_commands.jsonl` — command-guard decisions
- `YYYY-MM-DD_tokens.jsonl` — agent delegation usage
- `YYYY-MM-DD_notif.jsonl` — notifications dispatched
- `hook_errors.jsonl` — hook errors (not rotated)

## Hooks

### command-guard (PreToolUse)

Gates every Bash command and Claude Code tool call before execution.

Rules are defined in `resources/commands.conf` using glob-pattern token matching. On first run (or when `commands.conf` changes) the Bash rules are compiled to `commands.json` and cached; the cache is validated by content hash on each invocation.

**Bash rule actions:**

| Prefix | Action |
|--------|--------|
| `[+]` | Allow unconditionally |
| `[-]` | Deny with reason |
| `[~]` | Ask in interactive mode; auto-allow in `dontAsk` / `bypassPermissions` |
| `[?]` | Always ask; deny in `dontAsk` / `bypassPermissions` (requires human) |

**Tool rule actions** (for non-Bash Claude Code tools):

| Prefix | Action |
|--------|--------|
| `$[+]` | Allow |
| `$[-]` | Deny |
| `$[~]` | Ask in interactive; auto-allow in non-interactive |
| `$[?]` | Always ask; deny in non-interactive |

Tool rules match against `ToolName` (e.g. `Read`, `Edit`, `Write`, `WebFetch`, `Glob`, `Grep`) and an optional path pattern. Omitting the path pattern matches any target.

**Wildcards** (Bash patterns and tool path patterns, all case-insensitive):

| Token | Meaning |
|-------|---------|
| `?` | Exactly one character |
| `*` | One argument (or any characters within a path token) |
| `**` | Zero or more whitespace-separated arguments |
| `{a,b,c}` | Brace expansion — expands to one rule per alternative at load time |

**Inline hints:** append ` #<text>` to any rule. For `[-]` rules the text is shown to Claude as the deny reason. For `[~]` / `[?]` rules it appears in the confirmation prompt.

**CLI mode** (`c-guard` shim calls `command-guard.py` directly):

```
c-guard audit "git push --force origin main"
c-guard audit "rm -rf /tmp/foo" --mode bypassPermissions
command-guard.py --verify         # parse conf, report errors, write commands.json
command-guard.py --usage          # aggregate rule hit counts from JSONL logs
command-guard.py --replay 03-25-2026  # replay a day's log against current config
command-guard.py --debug          # print per-rule trace to stderr
```

Logs every decision to `commands.jsonl`.

### hook-dispatcher (all events)

Reads `agent_type` from the hook payload and loads `resources/{agent_type}_hooks.json`. Falls back to `base_hooks.json` if no agent-specific file exists. If an `instruction` is configured for the current event, it is printed to stdout and returned to Claude Code.

Supported event names: `SessionStart`, `UserPromptSubmit`, `PreToolUse`, `PermissionRequest`, `PostToolUse`, `PostToolUseFailure`, `SubagentStart`, `SubagentStop`, `Elicitation`, `ElicitationResult`, `TaskCompleted`, `Stop`, `SessionEnd`.

Currently active: in Beebop sessions `PreToolUse` injects `"BEEBOP GUARD: Are you sure this should not be delegated to Kiro or codex?"` before every tool call.

### claude-notify (Stop / PermissionRequest / Elicitation / Notification)

Shows a desktop toast notification. Called by the `.sh` wrapper with:

```
claude-notify.py <preset> [detail] [error_snippet]
```

**Presets:**

| Preset | Title suffix | Trigger |
|--------|-------------|---------|
| `completed` | Claude Finished | Stop event |
| `approval` | Approval Needed | PermissionRequest — shows tool name and file/command |
| `elicitation` | Input Required | Elicitation — MCP server waiting for input |
| `notification` | Claude | Generic Notification event |
| `error` | \<hook\> failed | Internal hook error |

For `approval` events the message is enriched from the hook payload: Edit/Write shows the filename; Bash shows the first 80 characters of the command.

On Windows uses `windows_toasts` with AUMID `ClaudeCode` registered under `HKCU\Software\Classes\AppUserModelId\ClaudeCode`. On Linux/macOS uses `plyer`. Logs each notification to `notif.jsonl`.

### track-agent-tokens (PostToolUse — Agent tool only)

Fires after every Agent tool call where `subagent_type` is present in the payload. Logs the following fields to `tokens.jsonl`:

`ts`, `session_id`, `project` (cwd), `agent`, `model`, `description`, `status`, `agent_id`, `total_tokens`, `tool_uses`, `duration_ms`, `input_tokens`, `output_tokens`, `cache_read_tokens`, `cache_creation_tokens`.

## Configuration

### commands.conf

Single source of truth for all Bash and tool permissions. Format:

```
# Bash rules
[+] git **                          # allow all git commands
[-] git ** push ** --force **       # deny force push
[~] chmod ** +x **                  # ask interactively; auto-allow when autonomous
[?] ssh **                          # always ask; deny when running autonomously

# Tool rules
$[+] Read                           # allow Read for any path
$[-] Write $HOME/.ssh/**            # deny writes into .ssh
$[~] WebFetch https://**            # ask before any web fetch
```

`$VAR` and `${VAR}` in path patterns are expanded from the environment at load time.

### Agent-specific hook instructions

Create `resources/{agent_name}_hooks.json` modelled on `beebop_hooks.json`. The file maps event names to `{ "instruction": "text" }`. Set to `null` to disable an event.

```json
{
  "PreToolUse": { "instruction": "Reminder: delegate reads to Kiro." },
  "Stop": { "instruction": null }
}
```

## Utilities

**guard-gap-analysis.py** — analyses `commands.jsonl` logs and cross-references compiled rules to surface policy gaps:

```
uv run python hooks/guard-gap-analysis.py [--days N] [--top N] [--min N]
```

Reports: decision breakdown, frequently deferred commands (no rule matched), frequently denied commands, frequently auto-approved asks (candidates for promotion to `[+]`), and per-rule hit frequency.

## Troubleshooting

- **No notifications on Windows:** `pip install windows_toasts`. Check `hook_errors.jsonl`.
- **No notifications on Linux/macOS:** `pip install plyer`. Check `hook_errors.jsonl`.
- **command-guard not evaluating correctly:** Run `c-guard audit "<command>"` to trace the decision. Run `command-guard.py --verify` to validate `commands.conf` syntax.
- **Hook not firing:** Verify `settings.json` has the correct absolute path to the `.sh` wrapper.
- **All hook errors:** `~/.claude/custom_logs/hook_errors.jsonl`.
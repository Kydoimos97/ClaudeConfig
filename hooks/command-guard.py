import json
import re
import subprocess
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Tuple

HOOKS_DIR = Path(__file__).parent
RESOURCES_DIR = HOOKS_DIR / "resources"
LOG_DIR = Path.home() / ".claude" / "custom_logs"


def load_blocked_patterns(path: Path) -> list[tuple[re.Pattern, str]]:
    """Load blocked patterns from file: pattern_str  @@  reason"""
    patterns = []
    if not path.exists():
        return patterns

    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            if "  @@  " not in line:
                continue

            parts = line.split("  @@  ", 1)
            if len(parts) != 2:
                continue

            pattern_str, reason = parts
            pattern_str = pattern_str.strip()
            reason = reason.strip()

            try:
                compiled = re.compile(pattern_str)
                patterns.append((compiled, reason))
            except re.error as e:
                log_error(f"Failed to compile pattern '{pattern_str}': {e}")

    return patterns


def load_approved_entries(path: Path) -> list[str]:
    """Load approved entries (Bash prefixes and tool names) from file."""
    entries = []
    if not path.exists():
        return entries

    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            entries.append(line)

    return entries


def normalize(command: str) -> str:
    """Normalize command by removing Claude Code path rewrites."""
    command = command.strip()

    command = re.sub(
        r'git\s+-C\s+["\']?/[^"\']*["\']?\s+',
        "git ",
        command,
    )

    command = re.sub(
        r'cd\s+["\']?/[^"\']*["\']?\s+&&\s+',
        "",
        command,
    )

    return command


def extract_commands(command: str) -> list[str]:
    """Extract all command nodes from AST using tree-sitter."""
    try:
        from tree_sitter import Language, Parser
        import tree_sitter_bash as tsbash
    except ImportError as e:
        raise ImportError(f"tree-sitter dependency missing: {e}")

    try:
        language = Language(tsbash.language())
    except Exception as e:
        raise ImportError(f"Failed to load tree-sitter-bash: {e}")

    parser = Parser(language)

    command_bytes = bytes(command, "utf-8")
    tree = parser.parse(command_bytes)

    commands = []

    def visit(node: Any) -> None:
        """Recursively visit all nodes in the AST."""
        if node.type == "command":
            cmd_text = command_bytes[node.start_byte : node.end_byte].decode("utf-8").strip()
            if cmd_text:
                commands.append(cmd_text)

        for child in node.children:
            visit(child)

    visit(tree.root_node)
    return commands


def strip_env_assignments(text: str) -> str:
    """Strip leading KEY=value environment variable assignments."""
    while True:
        match = re.match(r"^[A-Za-z_][A-Za-z0-9_]*=[^\s]*\s+", text)
        if not match:
            break
        text = text[match.end() :]
    return text.strip()


def matches_prefix(cmd_text: str, prefixes: list[str]) -> tuple[bool, str]:
    """Check if cmd_text matches any accepted prefix."""
    normalized = strip_env_assignments(cmd_text).strip()

    for prefix in prefixes:
        if normalized == prefix or normalized.startswith(prefix + " "):
            return (True, prefix)

    return (False, "")


def log_command(
    status: str, tool: str, reason: str, duration_ms: float, command: str = "", **extra: object
) -> None:
    """Log command execution to daily JSONL file."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    entry: dict = {
        "ts": ts,
        "status": status,
        "tool": tool,
        "reason": reason,
        "duration_ms": round(duration_ms, 2),
    }
    if command:
        entry["command"] = command.replace("\n", " ")
    entry.update(extra)

    logfile = LOG_DIR / f"{datetime.now():%Y-%m-%d}_commands.jsonl"
    with open(logfile, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def log_error(error: str, raw_input: str = "") -> None:
    """Log errors to hook_errors.jsonl."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    input_text = raw_input[:500] if raw_input else None

    entry = {
        "ts": ts,
        "hook": "command-guard",
        "error": error,
        "input": input_text,
    }

    logfile = LOG_DIR / "hook_errors.jsonl"
    with open(logfile, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def deny(command: str, reason: str, duration_ms: float) -> None:
    """Deny command and output hook decision."""
    log_command("BLOCKED", "Bash", reason, duration_ms, command=command)
    output = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }
    print(json.dumps(output))


def approve(command: str, reason: str, duration_ms: float) -> None:
    """Approve command and output hook decision."""
    log_command("APPROVED", "Bash", reason, duration_ms, command=command)
    output = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
        }
    }
    print(json.dumps(output))


def continue_pass(command: str, reason: str, duration_ms: float) -> None:
    """Pass through without decision (no output)."""
    log_command("CONTINUE", "Bash", reason, duration_ms, command=command)


def _notify_error(message: str) -> None:
    """Fire a desktop notification via claude-notify.sh (best-effort, non-blocking)."""
    try:
        notify_script = HOOKS_DIR / "claude-notify.sh"
        if notify_script.exists():
            subprocess.run(
                ["bash", str(notify_script), "error", "command-guard", message[:100]],
                capture_output=True,
                timeout=5,
            )
    except Exception:
        pass




def _tool_target(tool_name: str, tool_input: dict) -> str:
    """Extract the primary target string for a non-Bash tool call."""
    if tool_name in ("Read", "Edit", "Write"):
        return tool_input.get("file_path", "")
    if tool_name == "WebFetch":
        return tool_input.get("url", "")[:120]
    if tool_name in ("Glob", "Grep"):
        return tool_input.get("pattern", "")
    if tool_name == "Agent":
        agent = tool_input.get("subagent_type", "")
        desc = tool_input.get("description", "")[:60]
        return f"{agent}: {desc}" if agent else desc
    for v in tool_input.values():
        if isinstance(v, str) and v:
            return v[:80]
    return ""


def main() -> None:
    """Main guard logic."""
    t_start = time.perf_counter()

    raw_input = sys.stdin.read()

    try:
        payload = json.loads(raw_input)
    except json.JSONDecodeError:
        elapsed_ms = (time.perf_counter() - t_start) * 1000
        log_error("Failed to parse JSON input", raw_input)
        return

    tool_name = payload.get("tool_name", "") or ""
    permission_mode = payload.get("permission_mode") or payload.get("default_mode") or ""

    if tool_name != "Bash":
        if not tool_name:
            return
        approved_entries = load_approved_entries(RESOURCES_DIR / "approved.conf")
        tool_input = payload.get("tool_input") or {}
        target = _tool_target(tool_name, tool_input)
        elapsed = (time.perf_counter() - t_start) * 1000
        extra: dict = {}
        if target:
            extra["target"] = target
        if permission_mode:
            extra["permission_mode"] = permission_mode
        if tool_name in approved_entries:
            log_command("APPROVED", tool_name, f"matched: {tool_name}", elapsed, **extra)
            print(json.dumps({
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "allow",
                }
            }))
        else:
            log_command("CONTINUE", tool_name, "not in approved.conf", elapsed, **extra)
        return

    tool_input = payload.get("tool_input", {})
    command = tool_input.get("command", "").strip()

    if not command:
        return

    command = normalize(command)

    blocked_patterns = load_blocked_patterns(RESOURCES_DIR / "blocked.conf")
    approved_entries = load_approved_entries(RESOURCES_DIR / "approved.conf")

    for pattern, reason in blocked_patterns:
        if pattern.search(command):
            deny(command, reason, (time.perf_counter() - t_start) * 1000)
            return

    try:
        commands = extract_commands(command)
    except ImportError as exc:
        msg = f"tree-sitter not installed — run: pip install tree-sitter tree-sitter-bash ({exc})"
        log_error(msg)
        _notify_error(msg)
        continue_pass(command, "dependency missing: install tree-sitter tree-sitter-bash", (time.perf_counter() - t_start) * 1000)
        return

    if not commands:
        continue_pass(
            command,
            "no commands found in parse tree",
            (time.perf_counter() - t_start) * 1000,
        )
        return

    for cmd_text in commands:
        for pattern, reason in blocked_patterns:
            if pattern.search(cmd_text):
                deny(command, reason, (time.perf_counter() - t_start) * 1000)
                return

    matched_prefixes: list[str] = []

    for cmd_text in commands:
        ok, prefix = matches_prefix(cmd_text, approved_entries)
        if not ok:
            name = strip_env_assignments(cmd_text).split()[0] if cmd_text.strip() else "?"
            continue_pass(
                command,
                f"no approved entry for: {name[:60]}",
                (time.perf_counter() - t_start) * 1000,
            )
            return
        if prefix not in matched_prefixes:
            matched_prefixes.append(prefix)

    approve(
        command,
        f"matched: {', '.join(matched_prefixes)}",
        (time.perf_counter() - t_start) * 1000,
    )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log_error(traceback.format_exc())
        sys.exit(0)

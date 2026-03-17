#!/usr/bin/env python3
"""Desktop notification hook for Claude Code."""

import json
import sys
import subprocess
from pathlib import Path
from datetime import datetime

BEEBOP_AUMID = "ClaudeCode"

if sys.platform == "win32":
    try:
        import winreg
        from windows_toasts import (
            InteractableWindowsToaster,
            Toast,
            ToastDisplayImage,
            ToastImagePosition,
        )
    except ImportError as e:
        LOG_DIR = Path.home() / ".claude" / "custom_logs"
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        raw_stdin = ""
        if not sys.stdin.isatty():
            try:
                raw_stdin = sys.stdin.read()
            except Exception:
                raw_stdin = ""
        entry = {
            "ts": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "hook": "claude-notify",
            "errors": f"windows_toasts not installed — install with: pip install windows_toasts",
            "input": raw_stdin[:500] if raw_stdin else None,
        }
        with (LOG_DIR / "hook_errors.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
        sys.exit(1)
else:
    try:
        from plyer import notification as plyer_notification
    except ImportError as e:
        LOG_DIR = Path.home() / ".claude" / "custom_logs"
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        raw_stdin = ""
        if not sys.stdin.isatty():
            try:
                raw_stdin = sys.stdin.read()
            except Exception:
                raw_stdin = ""
        entry = {
            "ts": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "hook": "claude-notify",
            "errors": "plyer not installed — install with: pip install plyer",
            "input": raw_stdin[:500] if raw_stdin else None,
        }
        with (LOG_DIR / "hook_errors.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
        sys.exit(1)

import hook_utils

PRESETS = {
    "approval": {
        "title_suffix": "Approval Needed",
        "default_message": "Waiting for input",
        "icon": "approval_icon",
    },
    "completed": {
        "title_suffix": "Claude Finished",
        "default_message": "Processing complete",
        "icon": "completed_icon",
    },
    "elicitation": {
        "title_suffix": "Input Required",
        "default_message": "MCP server is requesting input",
        "icon": "elicitation_icon",
    },
    "notification": {
        "title_suffix": "Claude",
        "default_message": "Claude sent a notification",
        "icon": "notification_icon",
    },
    "error": {
        "title_suffix": "failed",
        "default_message": "hook encountered an error",
        "icon": "error_icon",
    },
}


def get_repo_name() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return Path(result.stdout.strip()).name
    except Exception:
        pass
    return Path.cwd().name


def get_icon_path(preset: str) -> str:
    resources_dir = Path(__file__).parent / "resources"
    icon_path = resources_dir / f"{PRESETS[preset]['icon']}.png"
    if icon_path.exists():
        return str(icon_path)
    return ""


def enrich_message_from_stdin(preset: str, message: str, raw_stdin: str) -> str:
    if not raw_stdin:
        return message
    try:
        data = json.loads(raw_stdin)
    except json.JSONDecodeError:
        return message
    if preset == "approval":
        tool_name = data.get("tool_name", "")
        if tool_name in ("Edit", "Write"):
            file_path = data.get("tool_input", {}).get("file_path", "")
            if file_path:
                basename = Path(file_path).name
                return f"{tool_name}: {basename}"
        elif tool_name == "Bash":
            command = data.get("tool_input", {}).get("command", "")
            if command:
                return f"Bash: {command[:80]}"
        elif tool_name:
            return f"{tool_name}: permission required"
    elif preset in ("elicitation", "notification"):
        msg = data.get("message", "")
        if msg:
            return msg[:100]
    return message


def ensure_aumid_registered(icon_path: str) -> None:
    try:
        key = winreg.CreateKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Classes\AppUserModelId\ClaudeCode",
        )
        winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, "BeeBop")
        if icon_path:
            winreg.SetValueEx(key, "IconUri", 0, winreg.REG_SZ, icon_path)
        winreg.CloseKey(key)
    except Exception as e:
        hook_utils.log_error("claude-notify", str(e))


def dispatch_notification_windows(
    title: str, message: str, icon_path: str
) -> None:
    ensure_aumid_registered(
        str(Path(__file__).parent / "resources" / "program_icon.png")
    )
    toaster = InteractableWindowsToaster("BeeBop", notifierAUMID=BEEBOP_AUMID)
    toast = Toast()
    toast.text_fields = [title, message]
    if icon_path:
        toast.AddImage(
            ToastDisplayImage.fromPath(icon_path, position=ToastImagePosition.AppLogo)
        )
    toaster.show_toast(toast)


def dispatch_notification_unix(
    title: str, message: str, repo: str, icon_path: str
) -> None:
    plyer_notification.notify(
        title=title,
        message=message,
        app_name=repo,
        app_icon=icon_path,
        timeout=10,
    )


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(
            "Usage: claude-notify.py <preset> [detail] [error_snippet]",
            file=sys.stderr,
        )
        sys.exit(1)
    preset = sys.argv[1]
    if preset not in PRESETS:
        print(
            f"Unknown preset: {preset} (use: approval, completed, elicitation, notification, error)",
            file=sys.stderr,
        )
        sys.exit(1)
    detail = sys.argv[2] if len(sys.argv) > 2 else ""
    error_snippet = sys.argv[3] if len(sys.argv) > 3 else ""
    repo = get_repo_name()
    preset_config = PRESETS[preset]
    title_suffix = preset_config["title_suffix"]
    message = detail if detail else preset_config["default_message"]
    if preset == "error":
        if detail:
            title_suffix = f"{detail} failed"
        if error_snippet:
            message = error_snippet
    raw_stdin = ""
    if not sys.stdin.isatty():
        try:
            raw_stdin = sys.stdin.read()
        except Exception:
            raw_stdin = ""
    message = enrich_message_from_stdin(preset, message, raw_stdin)
    icon_path = get_icon_path(preset)
    title = f"{repo}: {title_suffix}"
    try:
        if sys.platform == "win32":
            dispatch_notification_windows(title, message, icon_path)
        else:
            dispatch_notification_unix(title, message, repo, icon_path)
    except Exception as e:
        hook_utils.log_error("claude-notify", str(e), raw_stdin)
        sys.exit(1)
    entry = {
        "ts": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "preset": preset,
        "title": title,
        "message": message,
        "repo": repo,
        "platform": sys.platform,
        "icon": icon_path,
    }
    hook_utils.append_jsonl(hook_utils.daily_log("notif"), entry)

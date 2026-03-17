"""Shared utilities for Claude Code Python hooks."""

import json
from datetime import datetime
from pathlib import Path

LOG_DIR = Path.home() / ".claude" / "custom_logs"


def ensure_log_dir() -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    return LOG_DIR


def log_error(hook_name: str, error: str, raw_input: str = "") -> None:
    """Append an error entry to hook_errors.jsonl."""
    ensure_log_dir()
    entry = {
        "ts": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "hook": hook_name,
        "errors": error,
        "input": raw_input[:500] if raw_input else None,
    }
    with (LOG_DIR / "hook_errors.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def daily_log(suffix: str) -> Path:
    """Return path to today's log file: YYYY-MM-DD_{suffix}.jsonl"""
    ensure_log_dir()
    return LOG_DIR / f"{datetime.now().strftime('%Y-%m-%d')}_{suffix}.jsonl"


def append_jsonl(path: Path, entry: dict) -> None:
    """Append a dict as a JSON line to path."""
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")

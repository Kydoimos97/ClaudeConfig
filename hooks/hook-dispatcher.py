#!/usr/bin/env python3
"""hook-dispatcher.py — agent-aware hook router for Claude Code events."""

import json
import sys
import traceback
from pathlib import Path

HOOKS_DIR = Path(__file__).parent
sys.path.insert(0, str(HOOKS_DIR))
from hook_utils import log_error, daily_log, append_jsonl  # noqa: E402


def main() -> None:
    raw = sys.stdin.read()

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return

    agent_type: str = payload.get("agent_type", "") or ""
    event: str = payload.get("hook_event_name", "") or ""

    if not event:
        return

    resources = HOOKS_DIR / "resources"
    config_path: Path | None = None
    if agent_type:
        candidate = resources / f"{agent_type}_hooks.json"
        if candidate.exists():
            config_path = candidate
    if config_path is None:
        base = resources / "base_hooks.json"
        if base.exists():
            config_path = base

    if config_path is None:
        return

    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        log_error("hook-dispatcher", str(exc), raw)
        return

    event_config = config.get(event)
    if event_config is None:
        return

    instruction = event_config.get("instruction")
    if instruction is not None:
        print(instruction)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log_error("hook-dispatcher", traceback.format_exc())
        sys.exit(0)

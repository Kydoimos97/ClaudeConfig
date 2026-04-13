#!/usr/bin/env python3
"""hook-debug-dump.py — temporary diagnostic hook.

Dumps the raw hook stdin payload to ~/.claude/hook-debug/<HookType>.jsonl
as a timestamped JSONL entry.  One file per hook type.  Never blocks;
always exits 0.

Usage (from settings.json):
  python $HOME/.claude/hooks/hook-debug-dump.py PreToolUse
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def main() -> None:
    hook_type = sys.argv[1] if len(sys.argv) > 1 else "unknown"

    raw = sys.stdin.read()

    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        payload = {"_raw": raw}

    dump_dir = Path.home() / ".claude" / "hook-debug"
    dump_dir.mkdir(parents=True, exist_ok=True)

    entry = {
        "ts": datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "hook_type": hook_type,
        "payload": payload,
    }

    out_path = dump_dir / f"{hook_type}.jsonl"
    with out_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass

sys.exit(0)

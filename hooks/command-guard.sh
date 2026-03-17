#!/bin/bash

set -e

HOOKS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOME="${HOME:-$(eval echo ~)}"
LOG_DIR="$HOME/.claude/custom_logs"

mkdir -p "$LOG_DIR"

PYTHON=""
if command -v python3 &> /dev/null; then
  PYTHON="python3"
elif command -v python &> /dev/null; then
  PYTHON="python"
fi

if [ -z "$PYTHON" ]; then
  TS="$(date +%Y-%m-%dT%H:%M:%S)"
  LOGFILE="$LOG_DIR/$(date +%Y-%m-%d)_commands.jsonl"

  cat >> "$LOGFILE" <<EOF
{"ts": "$TS", "status": "CONTINUE", "command": "", "reason": "python3 not found — install Python 3 to enable command guard", "duration_ms": 0}
EOF
  exit 0
fi

exec "$PYTHON" "$HOOKS_DIR/command-guard.py"

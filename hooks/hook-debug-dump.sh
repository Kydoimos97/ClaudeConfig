#!/bin/bash
# Temporary diagnostic wrapper — calls hook-debug-dump.py with the hook type.
# Never blocks; always exits 0.

HOOKS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOOK_TYPE="${1:-unknown}"

PYTHON=""
if command -v python3 &> /dev/null; then
  PYTHON="python3"
elif command -v python &> /dev/null; then
  PYTHON="python"
fi

if [ -z "$PYTHON" ]; then
  exit 0
fi

"$PYTHON" "$HOOKS_DIR/hook-debug-dump.py" "$HOOK_TYPE"
exit 0

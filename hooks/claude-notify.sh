#!/bin/bash

set -e

HOOKS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PYTHON=""
if command -v python3 &> /dev/null; then
  PYTHON="python3"
elif command -v python &> /dev/null; then
  PYTHON="python"
fi

if [ -z "$PYTHON" ]; then
  echo "python3 not found — install Python 3 to enable notifications" >&2
  exit 1
fi

exec "$PYTHON" "$HOOKS_DIR/claude-notify.py" "$@"

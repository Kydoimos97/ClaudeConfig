#!/usr/bin/env bash
HOOKS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON=$(command -v python3 2>/dev/null || command -v python 2>/dev/null)
[[ -z "$PYTHON" ]] && exit 0
exec "$PYTHON" "$HOOKS_DIR/track-agent-tokens.py"

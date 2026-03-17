#!/usr/bin/env python3
"""track-agent-tokens.py — PostToolUse hook, logs Agent subagent usage to JSONL."""

import json
import sys
import traceback
from datetime import datetime
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

    tool_input: dict = payload.get("tool_input") or {}
    tool_response: dict = payload.get("tool_response") or {}
    usage: dict = tool_response.get("usage") or {}

    subagent = tool_input.get("subagent_type", "")
    if not subagent:
        return

    entry = {
        "ts":                       datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "session_id":               payload.get("session_id", ""),
        "project":                  payload.get("cwd", ""),
        "agent":                    subagent,
        "model":                    tool_input.get("model", ""),
        "description":              tool_input.get("description", ""),
        "status":                   tool_response.get("status", ""),
        "agent_id":                 tool_response.get("agentId", ""),
        "total_tokens":             tool_response.get("totalTokens", 0),
        "tool_uses":                tool_response.get("totalToolUseCount", 0),
        "duration_ms":              tool_response.get("totalDurationMs", 0),
        "input_tokens":             usage.get("input_tokens", 0),
        "output_tokens":            usage.get("output_tokens", 0),
        "cache_read_tokens":        usage.get("cache_read_input_tokens", 0),
        "cache_creation_tokens":    usage.get("cache_creation_input_tokens", 0),
    }

    append_jsonl(daily_log("tokens"), entry)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log_error("track-agent-tokens", traceback.format_exc())
        sys.exit(0)

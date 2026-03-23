#!/usr/bin/env python3
"""guard-gap-analysis.py — Analyse command-guard logs to surface policy gaps.

Parses JSONL logs from ~/.claude/custom_logs/, cross-references the compiled
commands.json (Bash rules) and the raw commands.conf (tool rules), and reports:

  - Decision breakdown
  - Frequently deferred commands  (no rule matched — coverage gaps)
  - Frequently denied commands    (actively blocked — may need targeted allow)
  - Frequently asked commands     (routinely approved asks — promote to allow?)
  - Rule hit frequency            (hot rules vs dead rules)
  - Policy coverage summary

Usage:
  uv run python hooks/guard-gap-analysis.py [--days N] [--top N] [--min N]
  python hooks/guard-gap-analysis.py --days 7 --top 30 --min 2
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional


HOOKS_DIR = Path(__file__).parent
CONF_PATH = HOOKS_DIR / "resources" / "commands.conf"
JSON_PATH = HOOKS_DIR / "resources" / "commands.json"
LOG_DIR = Path.home() / ".claude" / "custom_logs"


# ---------------------------------------------------------------------------
# Policy loader
# ---------------------------------------------------------------------------

def load_bash_rules(json_path: Path) -> dict[str, dict]:
    """Return {rule_id: rule_dict} from compiled commands.json (Bash rules only)."""
    if not json_path.exists():
        return {}
    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
        return {r["id"]: r for r in data.get("rules", [])}
    except (json.JSONDecodeError, KeyError):
        return {}


def load_tool_rules_from_conf(conf_path: Path) -> list[dict]:
    """Parse $[...] tool rules directly from commands.conf.

    Returns a list of dicts with keys: rule_id, action, tool_name, path_pattern, raw.
    Does not depend on command-guard.py so the script is self-contained.
    """
    rules: list[dict] = []
    if not conf_path.exists():
        return rules

    prefix_map = {"$[+]": "allow", "$[-]": "deny", "$[~]": "ask"}

    with open(conf_path, encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            for prefix, action in prefix_map.items():
                if stripped.startswith(prefix + " ") or stripped == prefix:
                    rest = stripped[len(prefix):].strip()
                    hint = None
                    if " #" in rest:
                        rest, hint_raw = rest.split(" #", 1)
                        hint = hint_raw.strip() or None
                    parts = rest.split(None, 1)
                    if not parts:
                        continue
                    tool_name = parts[0].lower()
                    path_pattern = parts[1].strip() if len(parts) > 1 else None
                    rules.append(
                        {
                            "id": f"rule_{lineno}",
                            "line": lineno,
                            "action": action,
                            "tool_name": tool_name,
                            "path_pattern": path_pattern,
                            "hint": hint,
                            "raw": stripped,
                        }
                    )
                    break
    return rules


# ---------------------------------------------------------------------------
# Log loader
# ---------------------------------------------------------------------------

def load_entries(log_dir: Path, days: Optional[int]) -> list[dict]:
    """Load all *_commands.jsonl entries, optionally capped to the last N days."""
    entries: list[dict] = []
    cutoff: Optional[datetime] = None
    if days is not None:
        from datetime import timezone
        cutoff = datetime.now(tz=timezone.utc) - timedelta(days=days)

    if not log_dir.exists():
        return entries

    for log_file in sorted(log_dir.glob("*_commands.jsonl")):
        with open(log_file, encoding="utf-8") as f:
            for raw in f:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    entry = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if cutoff:
                    ts = entry.get("timestamp", "")
                    try:
                        parsed = datetime.fromisoformat(ts)
                        # Make naive timestamps UTC-aware for comparison
                        if parsed.tzinfo is None:
                            from datetime import timezone
                            parsed = parsed.replace(tzinfo=timezone.utc)
                        if parsed < cutoff:
                            continue
                    except ValueError:
                        pass
                entries.append(entry)
    return entries


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

_BAR_WIDTH = 18


def bar(count: int, max_count: int) -> str:
    filled = round(count / max_count * _BAR_WIDTH) if max_count > 0 else 0
    return "#" * filled + "." * (_BAR_WIDTH - filled)


def section(title: str) -> None:
    print(f"\n{'=' * 76}")
    print(f"  {title}")
    print("=" * 76)


def hdr(cols: list[str], widths: list[int]) -> None:
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    print(fmt.format(*cols))
    print("  ".join("-" * w for w in widths))


def row(vals: list, widths: list[int]) -> None:
    parts = []
    for val, w in zip(vals, widths):
        cell = str(val)
        parts.append(cell[:w] if len(cell) > w else cell.ljust(w))
    print("  ".join(parts))


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

def analyse(entries: list[dict], bash_rules: dict[str, dict], tool_rules: list[dict]) -> dict:
    """Aggregate log entries into analysis buckets."""
    all_rule_ids: set[str] = set(bash_rules.keys()) | {r["id"] for r in tool_rules}

    decision_counts: Counter[str] = Counter()
    event_counts: Counter[str] = Counter()
    rule_hits: Counter[str] = Counter()
    cmd_by_decision: dict[str, Counter[str]] = defaultdict(Counter)
    denied_with_rule: dict[str, str] = {}

    for entry in entries:
        result = entry.get("result", {})
        raw_decision = result.get("decision", "unknown")
        # Some tool-event entries serialise decision as ["ask", null] (tuple artifact)
        if isinstance(raw_decision, list):
            decision = str(raw_decision[0]) if raw_decision else "unknown"
        else:
            decision = str(raw_decision) if raw_decision else "unknown"
        rule_id = result.get("rule_id")
        normalized = entry.get("normalized", {}).get("command", "<unknown>")
        event = entry.get("event", "unknown")

        decision_counts[decision] += 1
        event_counts[event] += 1
        cmd_by_decision[decision][normalized] += 1

        if rule_id:
            rule_hits[rule_id] += 1
            if decision == "deny":
                denied_with_rule.setdefault(normalized, rule_id)

    triggered_ids = set(rule_hits.keys())
    dead_rule_ids = all_rule_ids - triggered_ids

    return {
        "total": len(entries),
        "decision_counts": decision_counts,
        "event_counts": event_counts,
        "rule_hits": rule_hits,
        "cmd_by_decision": cmd_by_decision,
        "denied_with_rule": denied_with_rule,
        "dead_rule_ids": dead_rule_ids,
        "all_rule_ids": all_rule_ids,
    }


# ---------------------------------------------------------------------------
# Report sections
# ---------------------------------------------------------------------------

def report_summary(data: dict, days: Optional[int]) -> None:
    section("SUMMARY")
    days_label = f"last {days} days" if days is not None else "all time"
    total = data["total"]
    print(f"  Log directory : {LOG_DIR}")
    print(f"  Period        : {days_label}")
    print(f"  Total entries : {total:,}")
    print()
    print(f"  {'Decision':<12}  {'Count':>7}  {'Pct':>6}")
    print(f"  {'-'*12}  {'-'*7}  {'-'*6}")
    for d in ("allow", "deny", "ask", "defer", "unknown"):
        c = data["decision_counts"].get(d, 0)
        pct = c / total * 100 if total else 0.0
        print(f"  {d:<12}  {c:>7,}  {pct:>5.1f}%")
    print()
    print(f"  {'Event type':<35}  {'Count':>7}")
    print(f"  {'-'*35}  {'-'*7}")
    for event, c in data["event_counts"].most_common(10):
        print(f"  {event:<35}  {c:>7,}")


def report_deferred(data: dict, top: int, min_count: int) -> None:
    deferred = data["cmd_by_decision"].get("defer", Counter())
    items = [(cmd, c) for cmd, c in deferred.items() if c >= min_count]
    if not items:
        return
    items.sort(key=lambda x: -x[1])
    section(f"DEFERRED — no rule matched (top {top})")
    print("  These commands fell through to settings.json with no rule match.")
    print("  Add an explicit [+] allow or [-] deny rule for high-frequency ones.")
    print()
    max_c = max(c for _, c in items)
    hdr(["Count", "Freq", "Command"], [7, _BAR_WIDTH, 62])
    for cmd, count in items[:top]:
        row([f"{count:>7,}", bar(count, max_c), cmd], [7, _BAR_WIDTH, 62])
    if len(items) > top:
        print(f"  ... and {len(items) - top} more")


def report_denied(data: dict, bash_rules: dict, tool_rules: list[dict], top: int, min_count: int) -> None:
    denied = data["cmd_by_decision"].get("deny", Counter())
    items = [(cmd, c) for cmd, c in denied.items() if c >= min_count]
    if not items:
        return
    items.sort(key=lambda x: -x[1])

    tool_rules_by_id = {r["id"]: r for r in tool_rules}
    all_rules = {**bash_rules, **tool_rules_by_id}

    section(f"DENIED — blocked by [-] rule (top {top})")
    print("  Commands actively blocked. High-frequency denies that are legitimate")
    print("  workflow steps should get a targeted [+] allow rule.")
    print()
    max_c = max(c for _, c in items)
    hdr(["Count", "Freq", "Command", "Rule"], [7, _BAR_WIDTH, 44, 16])
    for cmd, count in items[:top]:
        rule_id = data["denied_with_rule"].get(cmd, "")
        rule_label = rule_id or "—"
        row([f"{count:>7,}", bar(count, max_c), cmd, rule_label], [7, _BAR_WIDTH, 44, 16])
    if len(items) > top:
        print(f"  ... and {len(items) - top} more")


def report_asked(data: dict, top: int, min_count: int) -> None:
    asked = data["cmd_by_decision"].get("ask", Counter())
    items = [(cmd, c) for cmd, c in asked.items() if c >= min_count]
    if not items:
        return
    items.sort(key=lambda x: -x[1])
    section(f"ASKED — user confirmation requested (top {top})")
    print("  Commands triggering [~] ask rules. If these are routinely approved,")
    print("  consider promoting them to [+] allow to reduce friction.")
    print()
    max_c = max(c for _, c in items)
    hdr(["Count", "Freq", "Command"], [7, _BAR_WIDTH, 62])
    for cmd, count in items[:top]:
        row([f"{count:>7,}", bar(count, max_c), cmd], [7, _BAR_WIDTH, 62])
    if len(items) > top:
        print(f"  ... and {len(items) - top} more")


def report_rule_hits(data: dict, bash_rules: dict, tool_rules: list[dict], top: int) -> None:
    rule_hits = data["rule_hits"]
    if not rule_hits:
        return
    tool_rules_by_id = {r["id"]: r for r in tool_rules}
    all_rules = {**bash_rules, **tool_rules_by_id}
    section(f"HOT RULES — top {top} by hit count")
    hdr(["rule_id", "Hits", "Action", "Pattern"], [16, 7, 7, 54])
    for rule_id, hits in rule_hits.most_common(top):
        rule = all_rules.get(rule_id)
        if rule:
            action = rule.get("action", "?")[:7]
            pattern = rule.get("normalized", rule.get("raw", "?"))[:54]
        else:
            action = "?"
            pattern = "(rule not found in current policy)"
        row([rule_id, f"{hits:>7,}", action, pattern], [16, 7, 7, 54])


def report_dead_rules(data: dict, bash_rules: dict, tool_rules: list[dict], days: Optional[int]) -> None:
    dead_ids = data["dead_rule_ids"]
    if not dead_ids:
        return
    tool_rules_by_id = {r["id"]: r for r in tool_rules}
    all_rules = {**bash_rules, **tool_rules_by_id}
    days_label = f"last {days} days" if days is not None else "all time"
    section(f"DEAD RULES — never triggered ({days_label})")
    print("  These rules exist in commands.conf but had zero log hits.")
    print("  May be stale, redundant, or protecting rarely-used paths.")
    print()
    hdr(["rule_id", "Line", "Action", "Pattern"], [16, 6, 7, 54])
    sorted_dead = sorted(
        dead_ids,
        key=lambda rid: all_rules.get(rid, {}).get("line", 9999),
    )
    for rid in sorted_dead:
        rule = all_rules.get(rid, {})
        line = str(rule.get("line", "?"))
        action = rule.get("action", "?")[:7]
        pattern = rule.get("normalized", rule.get("raw", "?"))[:54]
        row([rid, line, action, pattern], [16, 6, 7, 54])


def report_first_token_gaps(data: dict, min_count: int) -> None:
    """Surface unmatched base commands from deferred entries."""
    deferred = data["cmd_by_decision"].get("defer", Counter())
    if not deferred:
        return

    first_tokens: Counter[str] = Counter()
    for cmd, count in deferred.items():
        parts = cmd.split()
        if parts:
            tok = parts[0].lower()
            # Strip common path prefixes to surface the bare command
            tok = re.sub(r"^.*[/\\]", "", tok)
            first_tokens[tok] += count

    items = [(tok, c) for tok, c in first_tokens.items() if c >= min_count]
    if not items:
        return
    items.sort(key=lambda x: -x[1])

    section("DEFERRED — by base command (coverage gap map)")
    print("  Aggregated first-token counts from all deferred entries.")
    print("  Each base command here has no matching rule — pick the most frequent")
    print("  and decide: [+] allow, [-] deny, or [~] ask.")
    print()
    max_c = max(c for _, c in items)
    hdr(["Count", "Freq", "Base command"], [7, _BAR_WIDTH, 30])
    for tok, count in items[:30]:
        row([f"{count:>7,}", bar(count, max_c), tok], [7, _BAR_WIDTH, 30])


def report_coverage(data: dict) -> None:
    total = data["total"]
    deferred = data["decision_counts"].get("defer", 0)
    covered = total - deferred
    pct_covered = covered / total * 100 if total else 0.0
    pct_defer = deferred / total * 100 if total else 0.0
    section("POLICY COVERAGE")
    print(f"  Rule-matched : {covered:>7,}  ({pct_covered:.1f}%)")
    print(f"  Deferred     : {deferred:>7,}  ({pct_defer:.1f}%)")
    print(f"  Total rules  : {len(data['all_rule_ids']):>7,}")
    print(f"  Dead rules   : {len(data['dead_rule_ids']):>7,}")
    if total:
        print()
        deny_count = data["decision_counts"].get("deny", 0)
        ask_count = data["decision_counts"].get("ask", 0)
        allow_count = data["decision_counts"].get("allow", 0)
        print(f"  Of rule-matched: allow={allow_count:,}  deny={deny_count:,}  ask={ask_count:,}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Analyse command-guard logs for policy gaps",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--days", type=int, default=None,
        help="Restrict to entries from the last N days (default: all logs)",
    )
    parser.add_argument(
        "--top", type=int, default=20,
        help="Maximum rows per report section (default: 20)",
    )
    parser.add_argument(
        "--min", type=int, default=1, dest="min_count",
        help="Minimum hit count to include in frequency tables (default: 1)",
    )
    parser.add_argument(
        "--no-dead", action="store_true",
        help="Suppress the dead-rules section (useful if log window is short)",
    )
    args = parser.parse_args()

    bash_rules = load_bash_rules(JSON_PATH)
    tool_rules = load_tool_rules_from_conf(CONF_PATH)
    if not bash_rules and not tool_rules:
        print(
            f"[warn] No policy loaded — checked:\n  {JSON_PATH}\n  {CONF_PATH}",
            file=sys.stderr,
        )

    entries = load_entries(LOG_DIR, args.days)
    if not entries:
        label = f"last {args.days} days" if args.days is not None else "all time"
        print(f"No log entries found in {LOG_DIR} ({label}).")
        print("Check that LLM_HOOKS_LOGGING is not set to 0 in settings.json.")
        sys.exit(0)

    data = analyse(entries, bash_rules, tool_rules)

    report_summary(data, args.days)
    report_deferred(data, args.top, args.min_count)
    report_first_token_gaps(data, args.min_count)
    report_denied(data, bash_rules, tool_rules, args.top, args.min_count)
    report_asked(data, args.top, args.min_count)
    report_rule_hits(data, bash_rules, tool_rules, args.top)
    if not args.no_dead:
        report_dead_rules(data, bash_rules, tool_rules, args.days)
    report_coverage(data)


if __name__ == "__main__":
    main()

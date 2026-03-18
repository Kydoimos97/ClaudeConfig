#!/usr/bin/env python3
"""command-guard.py — glob-pattern command guard for Claude Code hooks.

Replaces the legacy regex/prefix-based guard with a compiled glob-pattern
system backed by commands.conf.  Bash command rules use full token-level glob
matching with an index-accelerated evaluator.  Claude Code tool rules
($-prefixed) match tool_name plus an optional path pattern.

CLI flags (bypass hook mode):
  --verify   parse conf, report syntax/conflict errors, write commands.json
  --usage    aggregate rule hit counts from JSONL logs
  --debug    print per-rule trace to stderr during hook evaluation
"""

import argparse
import fnmatch
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional


HOOKS_DIR = Path(__file__).parent
RESOURCES_DIR = HOOKS_DIR / "resources"
CONF_PATH = RESOURCES_DIR / "commands.conf"
JSON_PATH = RESOURCES_DIR / "commands.json"
LOG_DIR = Path.home() / ".claude" / "custom_logs"
SETTINGS_PATH = Path.home() / ".claude" / "settings.json"

SCHEMA_VERSION = 1


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

class TokenType(str, Enum):
    LITERAL = "literal"
    WILDCARD_SINGLE = "wildcard_single"
    WILDCARD_MULTI = "wildcard_multi"
    WILDCARD_CHAR = "wildcard_char"
    WILDCARD_IN_ARG = "wildcard_in_arg"


class Action(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"


@dataclass
class Token:
    type: TokenType
    value: Optional[str] = None  # present for literal and wildcard_in_arg


@dataclass
class Specificity:
    literal_count: int
    weight_vector: list[str]


@dataclass
class Rule:
    id: str
    line: int
    raw: str
    normalized: str
    action: Action
    tokens: list[Token]
    specificity: Specificity
    hint: Optional[str] = None  # inline comment text, surfaced as deny reason


@dataclass
class ToolRule:
    id: str
    line: int
    raw: str
    action: Action
    tool_name: str            # lowercased
    path_pattern: Optional[str]  # env-expanded, lowercased; None = match any target
    hint: Optional[str] = None


# ---------------------------------------------------------------------------
# Token parsing
# ---------------------------------------------------------------------------

def parse_token(raw: str) -> Token:
    if raw == "**":
        return Token(type=TokenType.WILDCARD_MULTI)
    if raw == "*":
        return Token(type=TokenType.WILDCARD_SINGLE)
    if raw == "?":
        return Token(type=TokenType.WILDCARD_CHAR)
    if "*" in raw or "?" in raw:
        return Token(type=TokenType.WILDCARD_IN_ARG, value=raw.lower())
    return Token(type=TokenType.LITERAL, value=raw.lower())


def compute_specificity(tokens: list[Token]) -> Specificity:
    weight_map = {
        TokenType.LITERAL: "literal",
        TokenType.WILDCARD_CHAR: "char_wildcard",
        TokenType.WILDCARD_IN_ARG: "in_arg_wildcard",
        TokenType.WILDCARD_SINGLE: "single_wildcard",
        TokenType.WILDCARD_MULTI: "multi_wildcard",
    }
    return Specificity(
        literal_count=sum(1 for t in tokens if t.type == TokenType.LITERAL),
        weight_vector=[weight_map[t.type] for t in tokens],
    )


def tokens_to_normalized(tokens: list[Token]) -> str:
    sym = {
        TokenType.WILDCARD_MULTI: "**",
        TokenType.WILDCARD_SINGLE: "*",
        TokenType.WILDCARD_CHAR: "?",
    }
    parts = []
    for t in tokens:
        if t.type in (TokenType.LITERAL, TokenType.WILDCARD_IN_ARG):
            parts.append(t.value)
        else:
            parts.append(sym[t.type])
    return " ".join(parts)


# ---------------------------------------------------------------------------
# Conf parsing
# ---------------------------------------------------------------------------

_BASH_PREFIXES: dict[str, Action] = {
    "[+]": Action.ALLOW,
    "[-]": Action.DENY,
    "[~]": Action.ASK,
}

_TOOL_PREFIXES: dict[str, Action] = {
    "$[+]": Action.ALLOW,
    "$[-]": Action.DENY,
    "$[~]": Action.ASK,
}


def _parse_bash_rule(stripped: str, prefix: str, action: Action, line_num: int) -> Rule:
    pattern_str = stripped[len(prefix) + 1:]
    hint: Optional[str] = None
    if " #" in pattern_str:
        pattern_str, hint_raw = pattern_str.split(" #", 1)
        hint = hint_raw.strip() or None
    parts = pattern_str.lower().split()
    if not parts:
        raise ValueError(f"Line {line_num}: empty pattern")
    if parts.count("**") > 1:
        raise ValueError(f"Line {line_num}: only one ** per rule allowed")
    tokens = [parse_token(p) for p in parts]
    normalized = tokens_to_normalized(tokens)
    return Rule(
        id=f"rule_{line_num}",
        line=line_num,
        raw=stripped,
        normalized=normalized,
        action=action,
        tokens=tokens,
        specificity=compute_specificity(tokens),
        hint=hint,
    )


def _parse_tool_rule(stripped: str, prefix: str, action: Action, line_num: int) -> ToolRule:
    rest = stripped[len(prefix) + 1:].strip()
    hint: Optional[str] = None
    if " #" in rest:
        rest, hint_raw = rest.split(" #", 1)
        hint = hint_raw.strip() or None
    parts = rest.split(None, 1)
    if not parts:
        raise ValueError(f"Line {line_num}: $-rule missing tool name")
    tool_name = parts[0].lower()
    path_pattern: Optional[str] = None
    if len(parts) > 1:
        path_pattern = os.path.expandvars(parts[1]).lower()
    return ToolRule(
        id=f"rule_{line_num}",
        line=line_num,
        raw=stripped,
        action=action,
        tool_name=tool_name,
        path_pattern=path_pattern,
        hint=hint,
    )


def parse_conf(path: Path) -> tuple[list[Rule], list[ToolRule]]:
    bash_rules: list[Rule] = []
    tool_rules: list[ToolRule] = []
    errors: list[str] = []

    with open(path, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue

            matched = False

            for prefix, action in _TOOL_PREFIXES.items():
                if stripped.startswith(prefix + " ") or stripped == prefix:
                    try:
                        tool_rules.append(_parse_tool_rule(stripped, prefix, action, line_num))
                    except ValueError as exc:
                        errors.append(str(exc))
                    matched = True
                    break

            if not matched:
                for prefix, action in _BASH_PREFIXES.items():
                    if stripped.startswith(prefix + " ") or stripped == prefix:
                        try:
                            bash_rules.append(_parse_bash_rule(stripped, prefix, action, line_num))
                        except ValueError as exc:
                            errors.append(str(exc))
                        matched = True
                        break

            if not matched:
                errors.append(f"Line {line_num}: unrecognised prefix: {stripped[:50]!r}")

    if errors:
        raise ValueError("Parse errors in commands.conf:\n" + "\n".join(errors))

    return bash_rules, tool_rules


# ---------------------------------------------------------------------------
# Index
# ---------------------------------------------------------------------------

def build_index(rules: list[Rule]) -> dict[str, list[int]]:
    index: dict[str, list[int]] = {}
    for pos, rule in enumerate(rules):
        first = rule.tokens[0]
        key = first.value if first.type == TokenType.LITERAL else "*"
        index.setdefault(key, []).append(pos)
    return index


# ---------------------------------------------------------------------------
# Compilation + cache
# ---------------------------------------------------------------------------

def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return f"sha256:{h.hexdigest()}"


def _rule_to_dict(rule: Rule) -> dict:
    tokens_out = []
    for t in rule.tokens:
        td: dict = {"type": t.type.value}
        if t.value is not None:
            td["value"] = t.value
        tokens_out.append(td)
    out: dict = {
        "id": rule.id,
        "line": rule.line,
        "raw": rule.raw,
        "normalized": rule.normalized,
        "action": rule.action.value,
        "tokens": tokens_out,
        "specificity": {
            "literal_count": rule.specificity.literal_count,
            "weight_vector": rule.specificity.weight_vector,
        },
    }
    if rule.hint is not None:
        out["hint"] = rule.hint
    return out


def compile_conf(conf_path: Path) -> dict:
    bash_rules, _ = parse_conf(conf_path)
    index = build_index(bash_rules)
    return {
        "version": SCHEMA_VERSION,
        "compiled_at": datetime.now(timezone.utc).isoformat(),
        "source": {
            "path": str(conf_path),
            "mtime": conf_path.stat().st_mtime,
            "hash": _sha256(conf_path),
        },
        "rules": [_rule_to_dict(r) for r in bash_rules],
        "index": index,
    }


def _cache_valid(cached: dict, conf_path: Path) -> bool:
    src = cached.get("source", {})
    try:
        return (
            abs(src.get("mtime", 0) - conf_path.stat().st_mtime) < 0.001
            and src.get("hash") == _sha256(conf_path)
        )
    except OSError:
        return False


def _rules_from_compiled(compiled: dict) -> tuple[list[Rule], dict[str, list[int]]]:
    rules = []
    for rd in compiled["rules"]:
        tokens = [
            Token(type=TokenType(td["type"]), value=td.get("value"))
            for td in rd["tokens"]
        ]
        rules.append(Rule(
            id=rd["id"],
            line=rd["line"],
            raw=rd["raw"],
            normalized=rd["normalized"],
            action=Action(rd["action"]),
            tokens=tokens,
            specificity=Specificity(
                literal_count=rd["specificity"]["literal_count"],
                weight_vector=rd["specificity"]["weight_vector"],
            ),
            hint=rd.get("hint"),
        ))
    return rules, compiled["index"]


def load_policy(
    conf_path: Path,
    json_path: Path,
    debug: bool = False,
) -> tuple[list[Rule], dict[str, list[int]], list[ToolRule]]:
    """Load compiled Bash rules + live tool rules.  Recompiles if cache stale."""
    needs_compile = True
    compiled: dict = {}

    if json_path.exists():
        try:
            cached = json.loads(json_path.read_text(encoding="utf-8"))
            if _cache_valid(cached, conf_path):
                needs_compile = False
                compiled = cached
                if debug:
                    print("[debug] loaded commands.json from cache", file=sys.stderr)
        except Exception as exc:
            if debug:
                print(f"[debug] cache load error: {exc}", file=sys.stderr)

    if needs_compile:
        if debug:
            print("[debug] recompiling commands.conf", file=sys.stderr)
        try:
            compiled = compile_conf(conf_path)
            json_path.write_text(json.dumps(compiled, indent=2), encoding="utf-8")
        except Exception as exc:
            print(
                f"command-guard: fatal — failed to compile commands.conf: {exc}",
                file=sys.stderr,
            )
            sys.exit(1)

    bash_rules, index = _rules_from_compiled(compiled)

    try:
        _, tool_rules = parse_conf(conf_path)
    except ValueError as exc:
        print(f"command-guard: fatal — {exc}", file=sys.stderr)
        sys.exit(1)

    return bash_rules, index, tool_rules


# ---------------------------------------------------------------------------
# Matching engine — Bash rules
# ---------------------------------------------------------------------------

def _match_single(token: Token, arg: str) -> bool:
    a = arg.lower()
    if token.type == TokenType.LITERAL:
        return token.value == a
    if token.type == TokenType.WILDCARD_SINGLE:
        return True
    if token.type == TokenType.WILDCARD_CHAR:
        return len(arg) == 1
    if token.type == TokenType.WILDCARD_IN_ARG:
        return fnmatch.fnmatchcase(a, token.value)
    return False  # wildcard_multi is handled one level up


def _match_tokens(ptokens: list[Token], itokens: list[str], pi: int = 0, ii: int = 0) -> bool:
    while pi < len(ptokens) and ii < len(itokens):
        pt = ptokens[pi]
        if pt.type == TokenType.WILDCARD_MULTI:
            remaining = len(itokens) - ii
            for count in range(remaining, 0, -1):  # greedy: try most first
                if _match_tokens(ptokens, itokens, pi + 1, ii + count):
                    return True
            return False
        if _match_single(pt, itokens[ii]):
            pi += 1
            ii += 1
        else:
            return False
    return pi == len(ptokens) and ii == len(itokens)


_ACTION_PRIORITY: dict[Action, int] = {Action.DENY: 2, Action.ASK: 1, Action.ALLOW: 0}


def _beats(challenger: Rule, current: Rule) -> bool:
    if challenger.specificity.literal_count != current.specificity.literal_count:
        return challenger.specificity.literal_count > current.specificity.literal_count
    return _ACTION_PRIORITY[challenger.action] > _ACTION_PRIORITY[current.action]


def evaluate_bash(
    rules: list[Rule],
    index: dict[str, list[int]],
    input_tokens: list[str],
    debug: bool = False,
) -> tuple[Optional[Rule], int, int, list[dict]]:
    """Evaluate input_tokens against Bash rules.

    Returns (winner, rules_evaluated, rules_matched, evaluations).
    winner is None when no rule matches (defer).
    """
    if not input_tokens:
        return None, 0, 0, []

    first = input_tokens[0].lower()
    positions: set[int] = set(index.get(first, []))
    positions.update(index.get("*", []))

    winner: Optional[Rule] = None
    matched_count = 0
    evaluations: list[dict] = []

    for pos in sorted(positions):
        rule = rules[pos]
        matched = _match_tokens(rule.tokens, input_tokens)
        became_best = False

        if matched:
            matched_count += 1
            if winner is None or _beats(rule, winner):
                winner = rule
                became_best = True
            if debug:
                print(
                    f"[debug] {rule.id} ({rule.action.value}) line={rule.line}"
                    f" spec={rule.specificity.literal_count}"
                    f" MATCHED{' (best)' if became_best else ''}",
                    file=sys.stderr,
                )
        else:
            if debug:
                print(
                    f"[debug] {rule.id} ({rule.action.value}) line={rule.line} no match",
                    file=sys.stderr,
                )

        evaluations.append({
            "rule_id": rule.id,
            "matched": matched,
            "decision": rule.action.value,
            "specificity": {
                "literal_count": rule.specificity.literal_count,
                "weight_vector": rule.specificity.weight_vector,
            },
            "became_best": became_best,
        })

    return winner, len(positions), matched_count, evaluations


# ---------------------------------------------------------------------------
# Matching engine — tool rules
# ---------------------------------------------------------------------------

def evaluate_tool(
    tool_rules: list[ToolRule],
    tool_name: str,
    target: str,
    debug: bool = False,
) -> Optional[ToolRule]:
    """Return the highest-specificity matching tool rule, or None (defer)."""
    winner: Optional[ToolRule] = None
    winner_score = -1

    for rule in tool_rules:
        if rule.tool_name != tool_name.lower():
            continue
        if rule.path_pattern is not None:
            if not fnmatch.fnmatchcase(target.lower(), rule.path_pattern):
                if debug:
                    print(
                        f"[debug] {rule.id} tool={rule.tool_name}"
                        f" pattern={rule.path_pattern!r} no match",
                        file=sys.stderr,
                    )
                continue
        # Specificity: path_pattern present beats absent; tie-break by action
        score = (1 if rule.path_pattern else 0) * 10 + _ACTION_PRIORITY[rule.action]
        if winner is None or score > winner_score:
            winner = rule
            winner_score = score
            if debug:
                print(
                    f"[debug] {rule.id} tool={rule.tool_name} MATCHED (score={score})",
                    file=sys.stderr,
                )

    return winner


# ---------------------------------------------------------------------------
# Tree-sitter utilities — kept identical to original implementation
# ---------------------------------------------------------------------------

def normalize(command: str) -> str:
    """Normalize command by removing Claude Code path rewrites."""
    command = command.strip()
    command = re.sub(r'git\s+-C\s+["\']?/[^"\']*["\']?\s+', "git ", command)
    command = re.sub(r'cd\s+["\']?/[^"\']*["\']?\s+&&\s+', "", command)
    return command


def extract_commands(command: str) -> list[str]:
    """Extract individual command nodes from a compound shell expression."""
    try:
        from tree_sitter import Language, Parser
        import tree_sitter_bash as tsbash
    except ImportError as exc:
        raise ImportError(f"tree-sitter dependency missing: {exc}")

    try:
        language = Language(tsbash.language())
    except Exception as exc:
        raise ImportError(f"Failed to load tree-sitter-bash: {exc}")

    parser = Parser(language)
    command_bytes = bytes(command, "utf-8")
    tree = parser.parse(command_bytes)
    commands: list[str] = []

    def visit(node) -> None:
        if node.type == "command":
            text = command_bytes[node.start_byte:node.end_byte].decode("utf-8").strip()
            if text:
                commands.append(text)
        for child in node.children:
            visit(child)

    visit(tree.root_node)
    return commands


def strip_env_assignments(text: str) -> str:
    """Strip leading KEY=value environment variable assignments."""
    while True:
        match = re.match(r"^[A-Za-z_][A-Za-z0-9_]*=[^\s]*\s+", text)
        if not match:
            break
        text = text[match.end():]
    return text.strip()


# ---------------------------------------------------------------------------
# Compound-command pre-checks (pipe-to-shell, raw-pass)
# ---------------------------------------------------------------------------

_PIPE_SHELLS: frozenset[str] = frozenset([
    "bash", "sh", "zsh", "fish", "dash", "ash", "csh", "tcsh", "ksh",
    "source",
])


def _check_pipe_to_shell(tokens: list[str]) -> Optional[str]:
    """Return the shell name if any '| <shell>' appears in token stream, else None.

    Operates on the whitespace-split raw token list.  Catches patterns like
    'curl url | bash', 'wget ... | bash -s', 'cat script | sh -c ...' — the
    single-** rule constraint would miss trailing args, so this is hardcoded.
    """
    for i, tok in enumerate(tokens):
        if tok == "|" and i + 1 < len(tokens):
            candidate = tokens[i + 1].lower()
            if candidate in _PIPE_SHELLS:
                return candidate
    return None


def _raw_pass(
    tokens: list[str],
    bash_rules: list[Rule],
    index: dict[str, list[int]],
    debug: bool,
) -> Optional[Rule]:
    """Evaluate the full whitespace-split command against Bash deny/ask rules.

    Returns a winning deny/ask rule, or None.  Allow results are intentionally
    ignored — allow decisions require per-command (tree-sitter) evaluation.
    Catches compound patterns such as redirects to system paths ('echo x >
    /etc/passwd') and any conf-defined compound deny rules.
    """
    winner, _, _, _ = evaluate_bash(bash_rules, index, tokens, debug=debug)
    if winner is not None and winner.action in (Action.DENY, Action.ASK):
        return winner
    return None


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def _log_level() -> int:
    try:
        return int(os.environ.get("LLM_HOOKS_LOGGING", "1"))
    except ValueError:
        return 1


def _write_log(entry: dict) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logfile = LOG_DIR / f"{datetime.now():%Y-%m-%d}_commands.jsonl"
    with open(logfile, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def log_decision(
    event: str,
    raw_input: dict,
    normalized_command: str,
    normalized_tokens: list[str],
    decision: str,
    source: str,
    rule_id: Optional[str],
    reason: Optional[str],
    rules_evaluated: int,
    rules_matched: int,
    evaluations: list[dict],
    output_payload: Optional[dict],
) -> None:
    level = _log_level()
    if level == 0:
        return

    entry: dict = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": SCHEMA_VERSION,
        "event": event,
        "normalized": {"command": normalized_command, "tokens": normalized_tokens},
        "result": {"decision": decision, "source": source},
        "stats": {"rules_evaluated": rules_evaluated, "rules_matched": rules_matched},
    }
    if rule_id:
        entry["result"]["rule_id"] = rule_id
    if reason:
        entry["result"]["reason"] = reason
    if level >= 2:
        entry["input"] = raw_input
        if evaluations:
            entry["evaluations"] = evaluations
        if output_payload is not None:
            entry["output"] = output_payload

    _write_log(entry)


def log_error(error: str, raw_input: str = "") -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "hook": "command-guard",
        "error": error,
        "input": raw_input[:500] if raw_input else None,
    }
    logfile = LOG_DIR / "hook_errors.jsonl"
    with open(logfile, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


# ---------------------------------------------------------------------------
# Hook output
# ---------------------------------------------------------------------------

def _tool_target(tool_name: str, tool_input: dict) -> str:
    if tool_name in ("Read", "Edit", "Write"):
        return tool_input.get("file_path", "")
    if tool_name == "WebFetch":
        return tool_input.get("url", "")[:120]
    if tool_name in ("Glob", "Grep"):
        return tool_input.get("pattern", "")
    if tool_name == "Agent":
        agent = tool_input.get("subagent_type", "")
        desc = tool_input.get("description", "")[:60]
        return f"{agent}: {desc}" if agent else desc
    for v in tool_input.values():
        if isinstance(v, str) and v:
            return v[:80]
    return ""


def _emit(decision: str, reason: Optional[str], event: str) -> dict:
    inner: dict = {"hookEventName": event, "permissionDecision": decision}
    if reason:
        inner["permissionDecisionReason"] = reason
    payload = {"hookSpecificOutput": inner}
    print(json.dumps(payload))
    return payload


def _notify_error(message: str) -> None:
    try:
        notify_script = HOOKS_DIR / "claude-notify.sh"
        if notify_script.exists():
            subprocess.run(
                ["bash", str(notify_script), "error", "command-guard", message[:100]],
                capture_output=True,
                timeout=5,
            )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Settings conflict detection
# ---------------------------------------------------------------------------

def _parse_settings_entry(entry: str) -> tuple[str, Optional[str]]:
    """Parse 'ToolName(pattern)' or 'ToolName' → (tool_name_lower, pattern_or_none)."""
    m = re.match(r'^(\w+)\((.+)\)$', entry.strip())
    if m:
        return m.group(1).lower(), m.group(2)
    return entry.strip().lower(), None


def _patterns_could_overlap(a_tokens: list[Token], b_tokens: list[Token]) -> bool:
    """Return True if two token sequences could match the same input command.

    Walks both sequences in parallel.  As soon as a wildcard appears in either
    side the patterns can match the same continuation, so we return True.
    A literal mismatch at the same position is a definitive no-overlap.
    Exhausting one sequence without finding a mismatch is also an overlap
    (one pattern is a prefix of the other, so a shared input exists).
    """
    for at, bt in zip(a_tokens, b_tokens):
        a_wild = at.type not in (TokenType.LITERAL, TokenType.WILDCARD_IN_ARG)
        b_wild = bt.type not in (TokenType.LITERAL, TokenType.WILDCARD_IN_ARG)
        if a_wild or b_wild:
            return True
        if at.type == TokenType.LITERAL and bt.type == TokenType.LITERAL:
            if at.value != bt.value:
                return False
        # WILDCARD_IN_ARG on either side: could match, keep walking
    return True


def check_settings_conflicts(
    bash_rules: list[Rule],
    tool_rules: list[ToolRule],
    settings_path: Path,
) -> list[str]:
    """Return warning strings for policy conflicts between commands.conf and settings.json.

    Checks two directions:
    - conf [~]/$[~] vs settings allow  — settings allow may silence conf ask
    - conf [+]      vs settings ask    — conf allow fires first, bypassing settings ask
    """
    if not settings_path.exists():
        return [f"  NOTE  settings.json not found at {settings_path} — skipping conflict check"]

    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return [f"  NOTE  could not parse settings.json: {exc}"]

    perms = data.get("permissions", {})
    allow_entries: list[str] = perms.get("allow", [])
    ask_entries: list[str] = perms.get("ask", [])
    warnings: list[str] = []

    def _bash_tokens(pattern: str) -> list[Token]:
        return [parse_token(p) for p in pattern.lower().split() if p]

    # Direction 1: conf [~] vs settings allow — settings allow may silence conf ask
    parsed_allows = [_parse_settings_entry(e) for e in allow_entries]

    for rule in bash_rules:
        if rule.action != Action.ASK:
            continue
        for sname, spattern in parsed_allows:
            if sname != "bash" or spattern is None:
                continue
            if _patterns_could_overlap(rule.tokens, _bash_tokens(spattern)):
                warnings.append(
                    f"  WARN  {rule.id} ([~] {rule.normalized!r}) may be silenced by"
                    f" settings allow 'Bash({spattern})'"
                )
                break

    for rule in tool_rules:
        if rule.action != Action.ASK:
            continue
        for sname, spattern in parsed_allows:
            if sname != rule.tool_name:
                continue
            target = f" {rule.path_pattern}" if rule.path_pattern else ""
            label = f"'{sname}({spattern})'" if spattern else f"'{sname}'"
            warnings.append(
                f"  WARN  {rule.id} ($[~] {rule.tool_name}{target}) may be silenced by"
                f" settings allow {label}"
            )
            break

    # Direction 2: conf [+] vs settings ask — conf allow fires first, settings ask bypassed
    parsed_asks = [_parse_settings_entry(e) for e in ask_entries]

    for rule in bash_rules:
        if rule.action != Action.ALLOW:
            continue
        for sname, spattern in parsed_asks:
            if sname != "bash" or spattern is None:
                continue
            if _patterns_could_overlap(rule.tokens, _bash_tokens(spattern)):
                warnings.append(
                    f"  WARN  {rule.id} ([+] {rule.normalized!r}) bypasses"
                    f" settings ask 'Bash({spattern})'"
                )
                break

    return warnings


# ---------------------------------------------------------------------------
# CLI: --verify
# ---------------------------------------------------------------------------

def cmd_verify() -> None:
    print(f"Verifying: {CONF_PATH}\n")
    try:
        bash_rules, tool_rules = parse_conf(CONF_PATH)
    except ValueError as exc:
        print(f"FAIL — {exc}")
        sys.exit(1)

    errors: list[str] = []
    warnings: list[str] = []

    index = build_index(bash_rules)

    # Index invariant: every stored position must be in range
    for key, positions in index.items():
        for pos in positions:
            if pos >= len(bash_rules):
                errors.append(f"Index key {key!r}: position {pos} out of range")

    # Duplicates and conflicts among bash rules
    by_normalized: dict[str, list[Rule]] = {}
    for rule in bash_rules:
        by_normalized.setdefault(rule.normalized, []).append(rule)

    for normalized, group in by_normalized.items():
        actions = {r.action for r in group}
        if len(group) > 1 and len(actions) == 1:
            ids = ", ".join(r.id for r in group)
            warnings.append(f"Duplicate rules for '{normalized}': {ids}")
        if len(actions) > 1:
            ids = ", ".join(f"{r.id}({r.action.value})" for r in group)
            errors.append(f"Conflict for '{normalized}': {ids} — deny wins at runtime")

    settings_conflicts = check_settings_conflicts(bash_rules, tool_rules, SETTINGS_PATH)

    for w in warnings:
        print(f"  WARN  {w}")
    for e in errors:
        print(f"  ERROR {e}")
    for c in settings_conflicts:
        print(c)

    if errors:
        print(f"\n{len(errors)} error(s) found — commands.json not written.")
        sys.exit(1)

    try:
        compiled = compile_conf(CONF_PATH)
        JSON_PATH.write_text(json.dumps(compiled, indent=2), encoding="utf-8")
    except Exception as exc:
        print(f"Compile failed: {exc}")
        sys.exit(1)

    print(f"Bash rules : {len(bash_rules)}")
    print(f"Tool rules : {len(tool_rules)}")
    print(f"Index keys : {len(index)}")
    if warnings:
        print(f"Warnings   : {len(warnings)}")
    if settings_conflicts:
        flagged = sum(1 for c in settings_conflicts if "WARN" in c)
        print(f"Conflicts  : {flagged} potential settings.json conflicts")
    print(f"Output     : {JSON_PATH}\n")

    print("--- Bash rules ---")
    for rule in bash_rules:
        print(
            f"  {rule.id:<14} line={rule.line:<4} {rule.action.value:<5}  {rule.normalized}"
        )

    print("\n--- Tool rules ---")
    for rule in tool_rules:
        path_str = f"  path={rule.path_pattern!r}" if rule.path_pattern else ""
        print(
            f"  {rule.id:<14} line={rule.line:<4} {rule.action.value:<5}  {rule.tool_name}{path_str}"
        )


# ---------------------------------------------------------------------------
# CLI: --usage
# ---------------------------------------------------------------------------

def cmd_usage() -> None:
    if not LOG_DIR.exists():
        print("No log directory found.")
        return

    log_files = sorted(LOG_DIR.glob("*_commands.jsonl"))
    if not log_files:
        print("No log files found.")
        return

    counts: dict[str, dict[str, int]] = {}
    total = 0
    skipped = 0

    for lf in log_files:
        with open(lf, "r", encoding="utf-8") as f:
            for raw_line in f:
                raw_line = raw_line.strip()
                if not raw_line:
                    continue
                try:
                    entry = json.loads(raw_line)
                except json.JSONDecodeError:
                    skipped += 1
                    continue
                result = entry.get("result")
                if not result:
                    skipped += 1
                    continue
                rule_id = result.get("rule_id", "defer")
                decision = result.get("decision", "unknown")
                counts.setdefault(rule_id, {})
                counts[rule_id][decision] = counts[rule_id].get(decision, 0) + 1
                total += 1

    if not counts:
        print("No new-format log entries found.")
        return

    print(f"Total: {total}  Skipped (old format): {skipped}\n")
    print(f"{'rule_id':<16}  {'allow':>6}  {'deny':>6}  {'ask':>6}  {'defer':>6}  {'total':>6}")
    print("-" * 56)
    for rule_id in sorted(counts.keys()):
        d = counts[rule_id]
        row = sum(d.values())
        print(
            f"{rule_id:<16}  "
            f"{d.get('allow', 0):>6}  "
            f"{d.get('deny', 0):>6}  "
            f"{d.get('ask', 0):>6}  "
            f"{d.get('defer', 0):>6}  "
            f"{row:>6}"
        )


# ---------------------------------------------------------------------------
# Hook handlers
# ---------------------------------------------------------------------------

def _handle_tool(
    payload: dict,
    tool_rules: list[ToolRule],
    event: str,
    debug: bool,
) -> None:
    tool_name = payload.get("tool_name", "") or ""
    tool_input = payload.get("tool_input") or {}
    target = _tool_target(tool_name, tool_input)

    winner = evaluate_tool(tool_rules, tool_name, target, debug=debug)

    if winner is None:
        log_decision(
            event=event,
            raw_input=payload,
            normalized_command=tool_name,
            normalized_tokens=[tool_name],
            decision="defer",
            source="default",
            rule_id=None,
            reason="no matching tool rule",
            rules_evaluated=0,
            rules_matched=0,
            evaluations=[],
            output_payload=None,
        )
        return

    decision = winner.action.value
    if decision == "ask" and event == "PermissionRequest":
        decision = "deny"

    if decision in ("deny", "ask"):
        reason = winner.hint or winner.raw
    else:
        reason = winner.hint

    output = _emit(decision, reason, event)
    log_decision(
        event=event,
        raw_input=payload,
        normalized_command=f"{tool_name} {target}".strip(),
        normalized_tokens=[t for t in [tool_name, target] if t],
        decision=decision,
        source="rule",
        rule_id=winner.id,
        reason=None,
        rules_evaluated=1,
        rules_matched=1,
        evaluations=[],
        output_payload=output,
    )


def _handle_bash(
    payload: dict,
    bash_rules: list[Rule],
    index: dict[str, list[int]],
    event: str,
    debug: bool,
) -> None:
    tool_input = payload.get("tool_input") or {}
    raw_command = tool_input.get("command", "").strip()
    if not raw_command:
        return

    command = normalize(raw_command)
    raw_tokens = command.lower().split()

    # --- Pre-check 1: pipe-to-shell (hardcoded, covers trailing-arg variants) ---
    pipe_shell = _check_pipe_to_shell(raw_tokens)
    if pipe_shell:
        reason = f"pipe to shell not permitted: {pipe_shell}"
        if debug:
            print(f"[debug] pipe-to-shell detected: {pipe_shell}", file=sys.stderr)
        output = _emit("deny", reason, event)
        log_decision(
            event=event,
            raw_input=payload,
            normalized_command=command,
            normalized_tokens=raw_tokens,
            decision="deny",
            source="default",
            rule_id=None,
            reason=reason,
            rules_evaluated=0,
            rules_matched=0,
            evaluations=[],
            output_payload=output,
        )
        return

    # --- Pre-check 2: raw pass — catches compound deny rules (redirects, etc.) ---
    raw_winner = _raw_pass(raw_tokens, bash_rules, index, debug)
    if raw_winner is not None:
        decision = raw_winner.action.value
        if decision == "ask" and event == "PermissionRequest":
            decision = "deny"
        if decision in ("deny", "ask"):
            reason = raw_winner.hint or raw_winner.raw
        else:
            reason = raw_winner.hint
        output = _emit(decision, reason, event)
        log_decision(
            event=event,
            raw_input=payload,
            normalized_command=command,
            normalized_tokens=raw_tokens,
            decision=decision,
            source="rule",
            rule_id=raw_winner.id,
            reason="raw pass",
            rules_evaluated=0,
            rules_matched=1,
            evaluations=[],
            output_payload=output,
        )
        return

    try:
        sub_commands = extract_commands(command)
    except ImportError as exc:
        msg = f"tree-sitter not installed — run: pip install tree-sitter tree-sitter-bash ({exc})"
        log_error(msg)
        _notify_error(msg)
        log_decision(
            event=event,
            raw_input=payload,
            normalized_command=command,
            normalized_tokens=command.split(),
            decision="defer",
            source="default",
            rule_id=None,
            reason="tree-sitter missing",
            rules_evaluated=0,
            rules_matched=0,
            evaluations=[],
            output_payload=None,
        )
        return

    if not sub_commands:
        log_decision(
            event=event,
            raw_input=payload,
            normalized_command=command,
            normalized_tokens=command.split(),
            decision="defer",
            source="default",
            rule_id=None,
            reason="no commands in parse tree",
            rules_evaluated=0,
            rules_matched=0,
            evaluations=[],
            output_payload=None,
        )
        return

    if debug:
        print(f"[debug] {len(sub_commands)} sub-command(s): {sub_commands}", file=sys.stderr)

    all_evals: list[dict] = []
    total_evaluated = 0
    total_matched = 0
    governing: Optional[Rule] = None
    governing_tokens: list[str] = []

    for cmd_text in sub_commands:
        cleaned = strip_env_assignments(cmd_text)
        tokens = cleaned.lower().split()
        if not tokens:
            continue

        winner, n_eval, n_match, evals = evaluate_bash(bash_rules, index, tokens, debug=debug)
        total_evaluated += n_eval
        total_matched += n_match
        all_evals.extend(evals)

        if winner is None:
            # One sub-command has no matching rule — defer the whole compound
            log_decision(
                event=event,
                raw_input=payload,
                normalized_command=command,
                normalized_tokens=tokens,
                decision="defer",
                source="default",
                rule_id=None,
                reason=f"no rule matched: {tokens[0][:60]}",
                rules_evaluated=total_evaluated,
                rules_matched=total_matched,
                evaluations=all_evals,
                output_payload=None,
            )
            return

        if winner.action in (Action.DENY, Action.ASK):
            governing = winner
            governing_tokens = tokens
            break  # deny/ask on any sub-command governs immediately

        if governing is None or _beats(winner, governing):
            governing = winner
            governing_tokens = tokens

    if governing is None:
        log_decision(
            event=event,
            raw_input=payload,
            normalized_command=command,
            normalized_tokens=command.split(),
            decision="defer",
            source="default",
            rule_id=None,
            reason="evaluation produced no winner",
            rules_evaluated=total_evaluated,
            rules_matched=total_matched,
            evaluations=all_evals,
            output_payload=None,
        )
        return

    decision = governing.action.value
    if decision == "ask" and event == "PermissionRequest":
        decision = "deny"

    if decision in ("deny", "ask"):
        reason = governing.hint or governing.raw
    else:
        reason = governing.hint
    output = _emit(decision, reason, event)
    log_decision(
        event=event,
        raw_input=payload,
        normalized_command=command,
        normalized_tokens=governing_tokens,
        decision=decision,
        source="rule",
        rule_id=governing.id,
        reason=None,
        rules_evaluated=total_evaluated,
        rules_matched=total_matched,
        evaluations=all_evals,
        output_payload=output,
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--usage", action="store_true")
    args, _ = parser.parse_known_args()

    if args.verify:
        cmd_verify()
        return

    if args.usage:
        cmd_usage()
        return

    raw_input = sys.stdin.read()

    try:
        payload = json.loads(raw_input)
    except json.JSONDecodeError:
        log_error("Failed to parse JSON input", raw_input)
        return

    event = payload.get("hook_event_name") or "PreToolUse"
    tool_name = payload.get("tool_name", "") or ""

    if not tool_name:
        return

    bash_rules, index, tool_rules = load_policy(CONF_PATH, JSON_PATH, debug=args.debug)

    if args.debug:
        print(
            f"[debug] event={event} tool={tool_name}"
            f" bash_rules={len(bash_rules)} tool_rules={len(tool_rules)}",
            file=sys.stderr,
        )

    if tool_name == "Bash":
        _handle_bash(payload, bash_rules, index, event, args.debug)
    else:
        _handle_tool(payload, tool_rules, event, args.debug)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log_error(traceback.format_exc())
        sys.exit(0)

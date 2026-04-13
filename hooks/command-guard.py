#!/usr/bin/env python3
"""command-guard.py — glob-pattern command guard for Claude Code hooks.

Replaces the legacy regex/prefix-based guard with a compiled glob-pattern
system backed by commands.conf.  Bash command rules use full token-level glob
matching with an index-accelerated evaluator.  Claude Code tool rules
($-prefixed) match tool_name plus an optional path pattern.

CLI flags (bypass hook mode):
  --verify   parse conf, report syntax/conflict errors, write commands.json
  --usage    aggregate rule hit counts from JSONL logs
  --audit "command"           trace a command through every evaluation phase
  --replay MM-DD-YYYY         replay a day's log and diff against current config
  --mode <mode>               permission mode for --audit/--replay (default, dontAsk, bypassPermissions)
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
from datetime import datetime
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

# Populated at runtime from &[-] Git(...) directives in commands.conf.
# Falls back to this default if no directive is found.
PROTECTED_BRANCHES: list[str] = [
    "main", "master", "develop", "prod", "production",
    "qa", "dev", "staging",
    "release*",
]


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
    REQUIRE_ASK = "require_ask"  # [?] — always ask; deny in non-interactive modes


@dataclass
class Token:
    type: TokenType
    value: Optional[str] = None  # present for literal and wildcard_in_arg


@dataclass
class Specificity:
    literal_count: int
    weight_vector: list[str]
    content_score: int = 0


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


@dataclass
class Directive:
    """Meta-rule parsed from &[action] Handler(args) syntax.

    Currently supported handlers:
      Git(branch1,branch2,...)  — declares protected branches; the runtime
                                  interceptor denies push/merge/rebase/cherry-pick/reset
                                  that would mutate any listed branch.
    """
    id: str
    line: int
    raw: str
    action: Action
    handler: str          # e.g. "git" (lowercased)
    args: list[str]       # e.g. ["main", "master", "qa", "release*"]
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


def _token_content_score(token: Token) -> int:
    """Score a single rule token by the semantic content it constrains.

    Scoring tiers (highest to lowest):
      URL-bearing wildcard_in_arg (contains ://)        → 100
      Extension-bearing wildcard_in_arg (e.g. *.exe)   →  50
      Non-flag content wildcard_in_arg                  →  20
      Literal token                                     →  10
      Flag-like wildcard_in_arg (starts with -)         →   0
      Pure wildcard (*, **, ?)                          →   0

    This mirrors the dimension-aware model used for tool rules: a rule that
    constrains a network target or file extension is more relevant than one
    that constrains a flag like -d or --output, even if the flag rule has
    more literal tokens.
    """
    if token.type == TokenType.LITERAL:
        return 10
    if token.type == TokenType.WILDCARD_IN_ARG:
        val = token.value  # already lowercased
        if "://" in val:
            return 100
        dot = val.rfind(".")
        if dot >= 0 and "*" not in val[dot:] and "?" not in val[dot:]:
            return 50
        if not val.startswith("-"):
            return 20
        return 0
    return 0


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
        content_score=sum(_token_content_score(t) for t in tokens),
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
    "[?]": Action.REQUIRE_ASK,
}

_TOOL_PREFIXES: dict[str, Action] = {
    "$[+]": Action.ALLOW,
    "$[-]": Action.DENY,
    "$[~]": Action.ASK,
    "$[?]": Action.REQUIRE_ASK,
}

_DIRECTIVE_PREFIXES: dict[str, Action] = {
    "&[+]": Action.ALLOW,
    "&[-]": Action.DENY,
    "&[~]": Action.ASK,
    "&[?]": Action.REQUIRE_ASK,
}


def _expand_braces(line: str, prefix: str) -> list[str]:
    """Expand {a,b,c} alternations in the pattern portion of a rule line.

    Returns one fully-formed rule line per expansion.  Multiple brace groups
    produce the cartesian product.  If no braces are present, returns [line].
    The inline hint (everything from the first ' #') is preserved unchanged on
    every expansion.

    Example:
        '[-] git ** push ** {main,master} #msg'
        → ['[-] git ** push ** main #msg',
           '[-] git ** push ** master #msg']
    """
    rest = line[len(prefix) + 1:]
    hint_part = ""
    if " #" in rest:
        pattern_part, hint_raw = rest.split(" #", 1)
        hint_part = " #" + hint_raw
    else:
        pattern_part = rest

    if "{" not in pattern_part:
        return [line]

    patterns = [pattern_part]
    while True:
        next_patterns: list[str] = []
        expanded_any = False
        for p in patterns:
            m = re.search(r"\{([^{}]+)\}", p)
            if not m:
                next_patterns.append(p)
                continue
            expanded_any = True
            pre, post = p[: m.start()], p[m.end() :]
            for alt in m.group(1).split(","):
                next_patterns.append(pre + alt.strip() + post)
        patterns = next_patterns
        if not expanded_any:
            break

    return [f"{prefix} {p.strip()}{hint_part}" for p in patterns]


def _parse_bash_rule(stripped: str, prefix: str, action: Action, line_num: int) -> Rule:
    pattern_str = stripped[len(prefix) + 1:]
    hint: Optional[str] = None
    if " #" in pattern_str:
        pattern_str, hint_raw = pattern_str.split(" #", 1)
        hint = hint_raw.strip() or None
    parts = pattern_str.lower().split()
    if not parts:
        raise ValueError(f"Line {line_num}: empty pattern")
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


def _parse_directive(stripped: str, prefix: str, action: Action, line_num: int) -> Directive:
    """Parse &[action] Handler(arg1,arg2,...) #hint syntax."""
    rest = stripped[len(prefix) + 1:].strip()
    hint: Optional[str] = None
    if " #" in rest:
        rest, hint_raw = rest.split(" #", 1)
        hint = hint_raw.strip() or None

    m = re.match(r"(\w+)\(([^)]*)\)", rest.strip())
    if not m:
        raise ValueError(
            f"Line {line_num}: invalid directive syntax — expected Handler(args): {rest!r}"
        )

    handler = m.group(1).lower()
    args = [a.strip().lower() for a in m.group(2).split(",") if a.strip()]
    if not args:
        raise ValueError(f"Line {line_num}: directive has no arguments: {rest!r}")

    return Directive(
        id=f"rule_{line_num}",
        line=line_num,
        raw=stripped,
        action=action,
        handler=handler,
        args=args,
        hint=hint,
    )


def parse_conf(path: Path) -> tuple[list[Rule], list[ToolRule], list[Directive]]:
    bash_rules: list[Rule] = []
    tool_rules: list[ToolRule] = []
    directives: list[Directive] = []
    errors: list[str] = []

    with open(path, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue

            matched = False

            # Directive rules (&[...])
            for prefix, action in _DIRECTIVE_PREFIXES.items():
                if stripped.startswith(prefix + " ") or stripped == prefix:
                    try:
                        directives.append(_parse_directive(stripped, prefix, action, line_num))
                    except ValueError as exc:
                        errors.append(str(exc))
                    matched = True
                    break

            # Tool rules ($[...])
            if not matched:
                for prefix, action in _TOOL_PREFIXES.items():
                    if stripped.startswith(prefix + " ") or stripped == prefix:
                        for expanded in _expand_braces(stripped, prefix):
                            try:
                                tool_rules.append(_parse_tool_rule(expanded, prefix, action, line_num))
                            except ValueError as exc:
                                errors.append(str(exc))
                        matched = True
                        break

            # Bash rules ([...])
            if not matched:
                for prefix, action in _BASH_PREFIXES.items():
                    if stripped.startswith(prefix + " ") or stripped == prefix:
                        for expanded in _expand_braces(stripped, prefix):
                            try:
                                bash_rules.append(_parse_bash_rule(expanded, prefix, action, line_num))
                            except ValueError as exc:
                                errors.append(str(exc))
                        matched = True
                        break

            if not matched:
                errors.append(f"Line {line_num}: unrecognised prefix: {stripped[:50]!r}")

    if errors:
        raise ValueError("Parse errors in commands.conf:\n" + "\n".join(errors))

    return bash_rules, tool_rules, directives


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
            "content_score": rule.specificity.content_score,
        },
    }
    if rule.hint is not None:
        out["hint"] = rule.hint
    return out


def compile_conf(conf_path: Path) -> dict:
    bash_rules, _, _ = parse_conf(conf_path)
    index = build_index(bash_rules)
    return {
        "version": SCHEMA_VERSION,
        "compiled_at": datetime.now().isoformat(),
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
                content_score=rd["specificity"].get("content_score", 0),
            ),
            hint=rd.get("hint"),
        ))
    return rules, compiled["index"]


def _apply_directives(directives: list[Directive], debug: bool = False) -> None:
    """Apply parsed directives to module-level state."""
    global PROTECTED_BRANCHES
    git_branches: list[str] = []

    for d in directives:
        if d.handler == "git":
            git_branches.extend(d.args)
            if debug:
                print(
                    f"[debug] directive {d.id}: Git branches = {d.args}",
                    file=sys.stderr,
                )

    if git_branches:
        PROTECTED_BRANCHES = git_branches


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
        _, tool_rules, directives = parse_conf(conf_path)
    except ValueError as exc:
        print(f"command-guard: fatal — {exc}", file=sys.stderr)
        sys.exit(1)

    _apply_directives(directives, debug=debug)

    return bash_rules, index, tool_rules


# ---------------------------------------------------------------------------
# Matching engine — Bash rules
# ---------------------------------------------------------------------------

def _path_aware_match(pattern: str, arg: str) -> bool:
    """Glob match with path-separator awareness.

    Used when the pattern token itself contains '/' or '\\', enabling rules
    like 'feat/*' (one segment) vs 'feat/**' (any depth).

      *   matches any characters except / and \\
      **  matches any characters including / and \\
      ?   matches any single character except / and \\

    Always case-insensitive.
    """
    parts = re.split(r"(\*\*|\*|\?)", pattern)
    regex: list[str] = ["^"]
    for part in parts:
        if part == "**":
            regex.append(".*")
        elif part == "*":
            regex.append("[^/\\\\]*")
        elif part == "?":
            regex.append("[^/\\\\]")
        else:
            regex.append(re.escape(part))
    regex.append("$")
    return bool(re.match("".join(regex), arg, re.IGNORECASE))


def _match_single(token: Token, arg: str) -> bool:
    a = arg.lower()
    if token.type == TokenType.LITERAL:
        return token.value == a
    if token.type == TokenType.WILDCARD_SINGLE:
        return True
    if token.type == TokenType.WILDCARD_CHAR:
        return len(arg) == 1
    if token.type == TokenType.WILDCARD_IN_ARG:
        # Defensive: bare key=value args (e.g. core.pager=cat from git -c)
        # should not accidentally match extension globs like *.env.
        # Only blocked when the pattern itself doesn't contain = (so dd of=*
        # still works — both sides have =).
        if "=" in a and not a.startswith("-") and "=" not in token.value:
            return False
        # Path-aware matching when the pattern itself contains a separator.
        # feat/*  → one segment (does not cross /)
        # feat/** → any depth  (crosses /)
        # Non-path patterns like *.exe keep the original fnmatch behaviour.
        if "/" in token.value or "\\" in token.value:
            return _path_aware_match(token.value, a)
        return fnmatch.fnmatchcase(a, token.value)
    return False  # wildcard_multi is handled one level up


def _match_tokens(ptokens: list[Token], itokens: list[str], pi: int = 0, ii: int = 0) -> bool:
    while pi < len(ptokens) and ii < len(itokens):
        pt = ptokens[pi]
        if pt.type == TokenType.WILDCARD_MULTI:
            remaining = len(itokens) - ii
            for count in range(remaining, -1, -1):  # greedy 0+: try most first, 0 = skip
                if _match_tokens(ptokens, itokens, pi + 1, ii + count):
                    return True
            return False
        if _match_single(pt, itokens[ii]):
            pi += 1
            ii += 1
        else:
            return False
    # Input exhausted — trailing ** tokens can each match zero and be skipped
    while pi < len(ptokens) and ptokens[pi].type == TokenType.WILDCARD_MULTI:
        pi += 1
    return pi == len(ptokens) and ii == len(itokens)


_ACTION_PRIORITY: dict[Action, int] = {Action.DENY: 3, Action.REQUIRE_ASK: 2, Action.ASK: 1, Action.ALLOW: 0}


def _beats(challenger: Rule, current: Rule) -> bool:
    cs = challenger.specificity.content_score
    cu = current.specificity.content_score
    if cs != cu:
        return cs > cu
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

def _pattern_extension(pattern: str) -> Optional[str]:
    """Return the explicit file extension from a glob pattern, or None.

    An extension is explicit when the last path segment ends with a literal
    dot-suffix that contains no wildcard characters (e.g. ``*.exe`` → ``.exe``,
    ``$USERPROFILE\\**\\*.ps1`` → ``.ps1``, ``$USERPROFILE\\**`` → None).
    Multi-extension patterns (``*.tar.gz``) return only the final extension
    (``.gz``); the literal-char path_score tiebreaker correctly ranks a
    ``*.tar.gz`` rule above a ``*.gz`` rule when both match the same target.
    """
    last_seg = pattern.replace("\\", "/").split("/")[-1]
    dot_pos = last_seg.rfind(".")
    if dot_pos < 0:
        return None
    ext = last_seg[dot_pos:]
    if "*" in ext or "?" in ext:
        return None
    return ext.lower()


def _target_extension(target: str) -> Optional[str]:
    """Return the file extension of a target path, lowercased, or None."""
    _, ext = os.path.splitext(target)
    return ext.lower() if ext else None


def _path_literal_count(pattern: str) -> int:
    """Count non-wildcard characters in a path pattern."""
    return sum(1 for c in pattern if c not in ("*", "?"))


def _tool_rule_score(rule: ToolRule, target: str) -> int:
    """Compute a dimension-aware specificity score for a matched tool rule.

    Scoring dimensions (highest to lowest priority):

      extension_score  — 1 when the rule explicitly constrains the file
                         extension AND that extension matches the target;
                         weighted at 1000 so an extension-specific rule
                         always beats a path-only rule of equal or lesser
                         path depth.
      path_score       — count of non-wildcard characters in the path
                         pattern, weighted at 10.  Longer literal prefixes
                         rank higher within the same extension class.
      action_priority  — deny (2) > ask (1) > allow (0) as the final
                         tiebreaker when two rules are otherwise equal.

    Rules without a path pattern score only their action_priority so they
    always lose to any pattern rule.

    Note: at ~100+ literal chars the path component overtakes the extension
    weight (100 * 10 = 1000).  This is intentional — a near-literal absolute
    path is genuinely more specific than a bare extension glob.
    """
    if rule.path_pattern is None:
        return _ACTION_PRIORITY[rule.action]
    pat_ext = _pattern_extension(rule.path_pattern)
    tgt_ext = _target_extension(target)
    extension_score = 1 if (pat_ext is not None and pat_ext == tgt_ext) else 0
    path_score = _path_literal_count(rule.path_pattern)
    return extension_score * 1000 + path_score * 10 + _ACTION_PRIORITY[rule.action]


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
        score = _tool_rule_score(rule, target.lower())
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
    """Normalize command by stripping Claude Code path rewrites.

    The git -C flag normalization that used to live here has been removed —
    ** now matches zero-or-more tokens, so conf rules like ``git ** status **``
    handle ``git -C /repo status`` natively without code-level special-casing.
    """
    command = command.strip()
    command = re.sub(r'cd\s+["\']?/[^"\']*["\']?\s+&&\s+', "", command)
    return command


_HEREDOC_OPEN_RE = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")


def strip_heredoc_bodies(command: str) -> str:
    """Strip heredoc payload lines while preserving the surrounding command.

    Raw pre-checks operate on a whitespace-split token stream and should not
    treat heredoc body content as shell syntax. This keeps markers like
    markdown table pipes or words like "merge" inside PR bodies from tripping
    shell-level guards.
    """
    lines = command.splitlines(keepends=True)
    if not lines:
        return command

    cleaned: list[str] = []
    pending: list[tuple[str, bool]] = []

    for line in lines:
        if pending:
            stripped = line.lstrip()
            matched = False
            for idx, (delimiter, allow_indent) in enumerate(pending):
                candidate = stripped if allow_indent else line
                if candidate.strip("\r\n") == delimiter:
                    cleaned.append(line)
                    pending.pop(idx)
                    matched = True
                    break
            if matched:
                continue
            continue

        cleaned.append(line)
        for match in _HEREDOC_OPEN_RE.finditer(line):
            op = match.group(0)
            delimiter = match.group(2)
            pending.append((delimiter, op.startswith("<<-")))

    return "".join(cleaned)


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
        m = re.match(r"^[A-Za-z_][A-Za-z0-9_]*='[^']*'\s+", text)
        if m:
            text = text[m.end():]
            continue
        m = re.match(r'^[A-Za-z_][A-Za-z0-9_]*="[^"]*"\s+', text)
        if m:
            text = text[m.end():]
            continue
        m = re.match(r"^[A-Za-z_][A-Za-z0-9_]*=[^\s'\"]*\s+", text)
        if m:
            text = text[m.end():]
            continue
        break
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
    if winner is not None and winner.action in (Action.DENY, Action.ASK, Action.REQUIRE_ASK):
        return winner
    return None


# ---------------------------------------------------------------------------
# Git protected-branch mutation guard
# ---------------------------------------------------------------------------

# Commands that mutate the CURRENT branch (target = HEAD).
# If you're ON a protected branch, these are denied.
_GIT_BRANCH_MUTATORS: frozenset[str] = frozenset([
    "merge", "rebase", "cherry-pick", "reset",
])


def _is_protected_branch(branch: str) -> bool:
    """Check if a branch name matches any entry in PROTECTED_BRANCHES.

    Fallback heuristic when no explicit rule matches:
      - Branch contains '/' (e.g. feat/foo, fix/bar) → not protected
      - Branch without '/' (e.g. main, develop, qa)  → protected
    """
    lower = branch.lower()
    for pattern in PROTECTED_BRANCHES:
        if "*" in pattern or "?" in pattern:
            if fnmatch.fnmatchcase(lower, pattern):
                return True
        elif lower == pattern:
            return True
    return "/" not in lower


def _git_current_branch() -> Optional[str]:
    """Resolve the current git branch, or None if not in a repo / detached."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            branch = result.stdout.strip()
            if branch == "HEAD":
                return None
            return branch or None
    except Exception:
        pass
    return None


def _gh_pr_base_branch(pr_number: str) -> Optional[str]:
    """Resolve the base branch for a GitHub PR number via gh CLI."""
    try:
        result = subprocess.run(
            ["gh", "pr", "view", pr_number, "--json", "baseRefName"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            payload = json.loads(result.stdout or "{}")
            base = payload.get("baseRefName")
            return base.strip() if isinstance(base, str) and base.strip() else None
    except Exception:
        pass
    return None


def _extract_push_target(tokens: list[str]) -> Optional[str]:
    """Extract the target branch from a git push command.

    Returns:
      - The explicit target branch name if one is specified
      - "head" if the push implicitly targets the current branch
      - None if this isn't a git push command

    Handles:
      git push                         → head (bare push)
      git push origin                  → head (remote only)
      git push origin HEAD             → head (explicit HEAD)
      git push -u origin HEAD          → head (flags stripped)
      git push origin feat/foo         → feat/foo (explicit target)
      git push origin HEAD:main        → main (refspec target)
      git push origin feat/foo:develop → develop (refspec target)
    """
    if "push" not in tokens:
        return None

    try:
        push_idx = tokens.index("push")
    except ValueError:
        return None

    # Non-flag args after "push" (skip --delete etc. which are handled by conf rules)
    args = [t for t in tokens[push_idx + 1:] if not t.startswith("-")]

    if len(args) == 0:
        return "head"
    if len(args) == 1:
        return "head"  # just remote name

    ref = args[1]
    # Refspec: local:remote — target is the remote side
    if ":" in ref:
        target = ref.split(":", 1)[1]
        return target if target else "head"

    if ref == "head":
        return "head"

    return ref


def _check_git_protected_mutation(
    tokens: list[str],
    debug: bool = False,
    mock_pr_base: Optional[str] = None,
) -> Optional[tuple[str, str]]:
    """Detect git/gh operations that would mutate a protected branch.

    Two dimensions checked:
      1. PUSH — is the target branch (explicit or implicit) protected?
      2. MUTATORS (merge, rebase, cherry-pick, reset) — is the current
         branch protected?  Merging main INTO a feature branch is fine;
         merging a feature branch INTO main is not.
      3. GH CLI — gh pr merge when the PR base branch is protected.

    Returns (decision, reason), or None if the operation is safe.
    """
    lower = [t.lower() for t in tokens]

    is_git = "git" in lower
    is_gh = lower[0] == "gh" if lower else False

    if not is_git and not is_gh:
        return None

    # --- Git push target check ---
    if is_git:
        push_target = _extract_push_target(lower)
        if push_target is not None:
            if push_target == "head":
                branch = _git_current_branch()
                if debug:
                    print(f"[debug] git-protect: implicit push, current={branch}", file=sys.stderr)
                    if branch is None:
                        print("[debug] git-protect: detached HEAD — skipping protection", file=sys.stderr)
                if branch and _is_protected_branch(branch):
                    return "require_ask", (
                        f"Protected branch: you are on '{branch}' and this push would "
                        f"target it directly. Open a PR instead. "
                        f"Checkout a feature branch first (e.g. git checkout -b feat/your-change)."
                    )
            elif _is_protected_branch(push_target):
                return "require_ask", (
                    f"Protected branch: push target '{push_target}' cannot be pushed to "
                    f"directly — open a PR instead."
                )
            return None

        # --- Current-branch mutation check (merge, rebase, cherry-pick, reset) ---
        for mutator in _GIT_BRANCH_MUTATORS:
            if mutator in lower:
                branch = _git_current_branch()
                if debug:
                    print(f"[debug] git-protect: '{mutator}' on current={branch}", file=sys.stderr)
                    if branch is None:
                        print("[debug] git-protect: detached HEAD — skipping protection", file=sys.stderr)
                if branch and _is_protected_branch(branch):
                    return "require_ask", (
                        f"Protected branch: '{mutator}' would modify '{branch}'. "
                        f"Checkout a feature branch first, then {mutator} there."
                    )
                break

    # --- gh CLI checks ---
    if lower[:3] == ["gh", "pr", "merge"]:
        pr_number = next((t for t in lower if t.isdigit()), None)
        base = mock_pr_base if mock_pr_base is not None else (_gh_pr_base_branch(pr_number) if pr_number else None)
        if debug:
            print(
                f"[debug] git-protect: gh pr merge pr={pr_number} base={base}",
                file=sys.stderr,
            )
        if base and _is_protected_branch(base):
            if "--admin" in lower:
                return "require_ask", (
                    f"Protected branch: PR targets '{base}' and uses --admin — approval required."
                )
            return "require_ask", (
                f"Protected branch: PR targets '{base}' — merge blocked."
            )

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
        "timestamp": datetime.now().isoformat(),
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
        "timestamp": datetime.now().isoformat(),
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


_NON_INTERACTIVE_MODES: frozenset[str] = frozenset({"dontAsk", "bypassPermissions", "acceptEdits"})

_DONT_ASK_DENY_REASON: str = (
    "Permission to use this command has been denied because Claude Code is running in "
    "don't ask mode. "
    "IMPORTANT: You *may* attempt to accomplish this action using other tools that might "
    "naturally be used to accomplish this goal, e.g. using head instead of cat. "
    "But you *should not* attempt to work around this denial in malicious ways, e.g. do "
    "not use your ability to run tests to execute non-test actions. You should only try "
    "to work around this restriction in reasonable ways that do not attempt to bypass the "
    "intent behind this denial. If you believe this capability is essential to complete a "
    "specified task try to finish any other outstanding tasks and inform the user of the "
    "blocker you ran into at the end of your run."
)


def _effective_decision(
    decision: str, event: str, permission_mode: str
) -> tuple[str, Optional[str]]:
    """Resolve the final decision given session interactivity constraints.

    Returns (final_decision, reason_override).  reason_override is non-None
    only when an escalation adds its own explanation; callers should use it
    in place of the rule's hint when present.

    Rule semantics:
      [~] ask        — heads-up confirmation in interactive mode; auto-allowed
                       in non-interactive mode (dontAsk/bypassPermissions).
      [?] require_ask — always requires a human; denied in non-interactive mode.

    PermissionRequest event handling:
      Both ask and require_ask collapse to deny — the event is a fallback
      mechanism that cannot surface interactive prompts, so neither can be
      honoured.  The rule's own hint is kept as the reason in that case.
    """
    if decision == "ask":
        if event == "PermissionRequest":
            return "deny", None
        if permission_mode in _NON_INTERACTIVE_MODES:
            return "allow", None
    if decision == "require_ask":
        if event == "PermissionRequest" or permission_mode in _NON_INTERACTIVE_MODES:
            return "deny", _DONT_ASK_DENY_REASON
        return "ask", None
    return decision, None


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
        if rule.action not in (Action.ASK, Action.REQUIRE_ASK):
            continue
        for sname, spattern in parsed_allows:
            if sname != "bash" or spattern is None:
                continue
            if _patterns_could_overlap(rule.tokens, _bash_tokens(spattern)):
                prefix = "[~]" if rule.action == Action.ASK else "[?]"
                warnings.append(
                    f"  WARN  {rule.id} ({prefix} {rule.normalized!r}) may be silenced by"
                    f" settings allow 'Bash({spattern})'"
                )
                break

    for rule in tool_rules:
        if rule.action not in (Action.ASK, Action.REQUIRE_ASK):
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
        bash_rules, tool_rules, directives = parse_conf(CONF_PATH)
    except ValueError as exc:
        print(f"FAIL — {exc}")
        sys.exit(1)

    _apply_directives(directives)

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
    print(f"Directives : {len(directives)}")
    print(f"Index keys : {len(index)}")
    if PROTECTED_BRANCHES:
        print(f"Protected  : {', '.join(PROTECTED_BRANCHES)}")
    if warnings:
        print(f"Warnings   : {len(warnings)}")
    if settings_conflicts:
        flagged = sum(1 for c in settings_conflicts if "WARN" in c)
        print(f"Conflicts  : {flagged} potential settings.json conflicts")
    print(f"Output     : {JSON_PATH}\n")

    if directives:
        print("--- Directives ---")
        for d in directives:
            print(f"  {d.id:<14} line={d.line:<4} {d.action.value:<5}  {d.handler}({', '.join(d.args)})")
        print()

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

def cmd_usage(days: int = 1) -> None:
    if not LOG_DIR.exists():
        print("No log directory found.")
        return

    from datetime import timedelta
    cutoff = datetime.now() - timedelta(days=days)
    cutoff_str = cutoff.strftime("%Y-%m-%d")

    log_files = sorted(LOG_DIR.glob("*_commands.jsonl"))
    if not log_files:
        print("No log files found.")
        return

    # Filter to files within the date range
    filtered = []
    for lf in log_files:
        # Filename format: YYYY-MM-DD_commands.jsonl
        date_part = lf.stem.replace("_commands", "")
        if date_part >= cutoff_str:
            filtered.append(lf)

    if not filtered:
        print(f"No log files found in the last {days} day(s) (since {cutoff_str}).")
        return

    bash_rules, _, tool_rules = load_policy(CONF_PATH, JSON_PATH)
    _, _, directives = parse_conf(CONF_PATH)
    rule_lookup: dict[str, str] = {"defer": "no matching rule"}
    for rule in bash_rules:
        rule_lookup[rule.id] = f"{rule.action.value} {rule.normalized}"
    for rule in tool_rules:
        target = f" {rule.path_pattern}" if rule.path_pattern is not None else ""
        rule_lookup[rule.id] = f"{rule.action.value} {rule.tool_name}{target}"
    for directive in directives:
        args = ",".join(directive.args)
        rule_lookup[directive.id] = f"{directive.action.value} {directive.handler}({args})"

    counts: dict[str, dict[str, int]] = {}
    total = 0
    malformed: list[tuple[str, int, str]] = []

    for lf in filtered:
        line_num = 0
        with open(lf, "r", encoding="utf-8") as f:
            for raw_line in f:
                line_num += 1
                raw_line = raw_line.strip()
                if not raw_line:
                    continue
                try:
                    entry = json.loads(raw_line)
                except json.JSONDecodeError as exc:
                    malformed.append((lf.name, line_num, f"JSON: {exc}"))
                    continue
                result = entry.get("result")
                if not result:
                    malformed.append((lf.name, line_num, "missing 'result' key"))
                    continue
                rule_id = result.get("rule_id", "defer")
                decision = result.get("decision", "unknown")
                counts.setdefault(rule_id, {})
                counts[rule_id][decision] = counts[rule_id].get(decision, 0) + 1
                total += 1

    if not counts:
        print("No valid log entries found.")
        return

    date_range = f"{filtered[0].stem.replace('_commands', '')} to {filtered[-1].stem.replace('_commands', '')}"
    print(f"Period: {date_range}  ({len(filtered)} file(s), {days} day(s))")
    print(f"Total: {total}\n")
    print(f"{'rule_id':<16}  {'allow':>6}  {'deny':>6}  {'ask':>6}  {'defer':>6}  {'total':>6}  rule")
    print("-" * 120)
    for rule_id in sorted(counts.keys()):
        d = counts[rule_id]
        row = sum(d.values())
        rule_text = rule_lookup.get(rule_id, "(rule not found in current commands.conf)")
        print(
            f"{rule_id:<16}  "
            f"{d.get('allow', 0):>6}  "
            f"{d.get('deny', 0):>6}  "
            f"{d.get('ask', 0):>6}  "
            f"{d.get('defer', 0):>6}  "
            f"{row:>6}  {rule_text}"
        )

    if malformed:
        print(f"\n{len(malformed)} malformed line(s):")
        for fname, ln, reason in malformed[:10]:
            print(f"  {fname}:{ln}  {reason}")
        if len(malformed) > 10:
            print(f"  ... {len(malformed) - 10} more")


# ---------------------------------------------------------------------------
# CLI: --audit
# ---------------------------------------------------------------------------

_ANSI_GREEN = "\033[32m"
_ANSI_RED = "\033[31m"
_ANSI_YELLOW = "\033[33m"
_ANSI_CYAN = "\033[36m"
_ANSI_DIM = "\033[2m"
_ANSI_BOLD = "\033[1m"
_ANSI_RESET = "\033[0m"

_DECISION_COLOR = {
    "allow": _ANSI_GREEN,
    "deny": _ANSI_RED,
    "ask": _ANSI_YELLOW,
    "require_ask": _ANSI_YELLOW,
}

_NO_COLOR: bool = False
_UTF8_STDOUT: bool = "utf" in (getattr(sys.stdout, "encoding", None) or "").lower()
_SEP_CHAR: str = "\u2500" if _UTF8_STDOUT else "-"
_RULE_SEP: str = "\u2500\u2500" if _UTF8_STDOUT else "--"
_CHK: str = "\u2713" if _UTF8_STDOUT else "+"   # ✓
_DOT: str = "\u00b7" if _UTF8_STDOUT else "."   # ·
_ARR: str = "\u2190" if _UTF8_STDOUT else "<-"  # ←
_RARR: str = "\u2192" if _UTF8_STDOUT else "->" # →
_WARN: str = "\u26a0" if _UTF8_STDOUT else "!"  # ⚠


def _colored(text: str, color: str) -> str:
    if _NO_COLOR or not sys.stdout.isatty():
        return text
    return f"{color}{text}{_ANSI_RESET}"


def _cpad(text: str, color: str, width: int) -> str:
    """Left-justify a colored string to `width` visible characters."""
    colored = _colored(text, color)
    ansi_overhead = len(colored) - len(text)
    return colored.ljust(width + ansi_overhead)


def _emit_quiet_audit(command: str, decision: str, governing: str) -> None:
    """Emit a minimal audit summary."""
    print(f"{command} --> {decision}")
    print(f"({governing})")


def cmd_audit(
    command: str,
    permission_mode: str = "default",
    compact: bool = False,
    quiet: bool = False,
    target: Optional[str] = None,
) -> None:
    """Trace a command through the full evaluation pipeline, showing every rule."""
    bash_rules, index, tool_rules = load_policy(CONF_PATH, JSON_PATH)

    if not quiet:
        print(f"{_colored('Auditing:', _ANSI_BOLD)}  {command}")
        print(f"Mode:      {permission_mode}")

    normalized = normalize(command)
    precheck_command = strip_heredoc_bodies(normalized)
    raw_tokens = precheck_command.lower().split()
    if not compact and not quiet:
        print(f"Tokens:    {raw_tokens}\n")

    # --- Phase 1: pipe-to-shell ---
    if not compact and not quiet:
        print(_colored(f"{_RULE_SEP} Phase 1: pipe-to-shell check {_RULE_SEP}", _ANSI_DIM))
    pipe_shell = _check_pipe_to_shell(raw_tokens)
    if pipe_shell:
        if quiet:
            effective, _ = _effective_decision("deny", "PreToolUse", permission_mode)
            _emit_quiet_audit(command, effective, f"pipe-to-shell: {pipe_shell}")
            return
        if not compact and not quiet:
            print(_colored(f"  BLOCKED  pipe to {pipe_shell} detected {_RARR} deny", _ANSI_RED))
        effective, _ = _effective_decision("deny", "PreToolUse", permission_mode)
        if compact:
            print(f"\n  {_colored('pipe-to-shell', _ANSI_RED)}  {pipe_shell}")
        print(f"\n{_colored('Final:', _ANSI_BOLD)}  {_colored(effective, _DECISION_COLOR.get(effective, ''))}")
        return
    if not compact and not quiet:
        print(_colored("  pass (no pipe-to-shell)", _ANSI_DIM))

    # --- Phase 1b: protected branch mutation check ---
    if not compact and not quiet:
        print(_colored(f"\n{_RULE_SEP} Phase 1b: protected branch guard {_RULE_SEP}", _ANSI_DIM))
    push_guard = _check_git_protected_mutation(raw_tokens, mock_pr_base=target)
    if push_guard:
        guard_decision, guard_reason = push_guard
        if quiet:
            effective, _ = _effective_decision(guard_decision, "PreToolUse", permission_mode)
            _emit_quiet_audit(command, effective, f"protected-branch: {guard_reason}")
            return
        if not compact and not quiet:
            color = _DECISION_COLOR.get(guard_decision, _ANSI_RED)
            label = "BLOCKED" if guard_decision == "deny" else "ASK"
            print(_colored(f"  {label:<7} {guard_reason}", color))
        else:
            color = _DECISION_COLOR.get(guard_decision, _ANSI_RED)
            print(f"\n  {_colored('protected-branch', color)}  {guard_reason}")
        effective, _ = _effective_decision(guard_decision, "PreToolUse", permission_mode)
        print(f"\n{_colored('Final:', _ANSI_BOLD)}  {_colored(effective, _DECISION_COLOR.get(effective, ''))}")
        return
    if not compact and not quiet:
        print(_colored("  pass (no protected branch mutation)", _ANSI_DIM))

    # --- Phase 2: raw pass ---
    if not compact and not quiet:
        print(_colored(f"\n{_RULE_SEP} Phase 2: raw pass (full token stream vs deny/ask rules) {_RULE_SEP}", _ANSI_DIM))
    raw_winner = _raw_pass(raw_tokens, bash_rules, index, debug=False)
    if raw_winner is not None:
        c = _DECISION_COLOR.get(raw_winner.action.value, "")
        effective, reason_override = _effective_decision(raw_winner.action.value, "PreToolUse", permission_mode)
        if quiet:
            governing = f"{raw_winner.id} line={raw_winner.line} {raw_winner.action.value} {raw_winner.normalized}"
            if reason_override:
                governing += f" (escalated in mode={permission_mode})"
            _emit_quiet_audit(command, effective, governing)
            return
        if compact:
            hint_str = f"  # {raw_winner.hint}" if raw_winner.hint else ""
            print(f"\n  {_colored(raw_winner.action.value, c):<18} {raw_winner.id} line={raw_winner.line}"
                  f"  {raw_winner.normalized}{hint_str}")
        else:
            print(f"  {_colored('HIT', c)}  {raw_winner.id} line={raw_winner.line}"
                  f"  {_colored(raw_winner.action.value, c)}"
                  f"  {raw_winner.normalized}")
            if raw_winner.hint:
                print(f"       hint: {raw_winner.hint}")
        if not compact and not quiet and reason_override:
            print(f"       escalated: {effective}")
        print(f"\n{_colored('Final:', _ANSI_BOLD)}  {_colored(effective, _DECISION_COLOR.get(effective, ''))}")
        return
    if not compact and not quiet:
        print(_colored("  pass (no deny/ask matched on raw tokens)", _ANSI_DIM))

    # --- Phase 3: tree-sitter extraction ---
    if not compact and not quiet:
        print(_colored(f"\n{_RULE_SEP} Phase 3: tree-sitter command extraction {_RULE_SEP}", _ANSI_DIM))
    try:
        sub_commands = extract_commands(normalized)
    except ImportError as exc:
        if quiet:
            _emit_quiet_audit(command, "deny", f"tree-sitter missing: {exc}")
            return
        if not compact and not quiet:
            print(_colored(f"  FAIL  tree-sitter not available: {exc}", _ANSI_RED))
        print(f"\n{_colored('Final:', _ANSI_BOLD)}  {_colored('deny', _ANSI_RED)} (tree-sitter missing)")
        return

    if not sub_commands:
        if not compact and not quiet:
            print(_colored("  no commands in parse tree", _ANSI_YELLOW))
        effective, _ = _effective_decision("ask", "PreToolUse", permission_mode)
        if quiet:
            _emit_quiet_audit(command, effective, "empty parse -> fallback ask")
            return
        print(f"\n{_colored('Final:', _ANSI_BOLD)}  {_colored(effective, _DECISION_COLOR.get(effective, ''))}"
              f" (empty parse {_RARR} fallback ask)")
        return

    if not compact and not quiet:
        for i, sc in enumerate(sub_commands):
            print(f"  sub[{i}]: {sc}")

    # --- Phase 4: per-command evaluation ---
    if not compact and not quiet:
        print(_colored(f"\n{_RULE_SEP} Phase 4: per-command rule evaluation {_RULE_SEP}", _ANSI_DIM))
    elif compact:
        print()
    governing: Optional[Rule] = None

    for cmd_text in sub_commands:
        cleaned = strip_env_assignments(cmd_text)
        tokens = cleaned.lower().split()
        if not tokens:
            continue
        if all(t.strip("\\") == "" for t in tokens):
            continue

        sub_guard = _check_git_protected_mutation(tokens, mock_pr_base=target)
        if sub_guard:
            guard_decision, guard_reason = sub_guard
            if quiet:
                effective, _ = _effective_decision(guard_decision, "PreToolUse", permission_mode)
                _emit_quiet_audit(command, effective, f"protected-branch (sub-cmd): {guard_reason}")
                return
            if not compact and not quiet:
                print(f"\n  {_colored(_RARR + ' ' + cmd_text, _ANSI_BOLD)}")
                c = _DECISION_COLOR.get(guard_decision, "")
                print(f"    {_colored('BLOCKED', c)}  protected-branch: {guard_reason}")
            effective, _ = _effective_decision(guard_decision, "PreToolUse", permission_mode)
            print(f"\n{_colored('Final:', _ANSI_BOLD)}  {_colored(effective, _DECISION_COLOR.get(effective, ''))}"
                  f"  (protected-branch in sub-command: {cmd_text[:60]})")
            return

        if not compact and not quiet:
            print(f"\n  {_colored(_RARR + ' ' + cmd_text, _ANSI_BOLD)}")
            print(f"    tokens: {tokens}")

        first = tokens[0].lower()
        positions: set[int] = set(index.get(first, []))
        positions.update(index.get("*", []))

        winner: Optional[Rule] = None
        for pos in sorted(positions):
            rule = bash_rules[pos]
            matched = _match_tokens(rule.tokens, tokens)
            if matched:
                is_best = winner is None or _beats(rule, winner)
                if is_best:
                    winner = rule
                if not compact and not quiet:
                    c = _DECISION_COLOR.get(rule.action.value, "")
                    best_tag = _colored(f" {_ARR} best", _ANSI_CYAN) if is_best else ""
                    print(f"    {_colored(_CHK, c)} {rule.id:<14} {_colored(rule.action.value, c):<18}"
                          f" score={rule.specificity.content_score:<4} {rule.normalized}{best_tag}")
            else:
                if not compact and not quiet:
                    print(f"    {_colored(_DOT, _ANSI_DIM)} {rule.id:<14} {_colored(rule.action.value, _ANSI_DIM):<18}"
                          f" score={rule.specificity.content_score:<4} {rule.normalized}")

        if winner is None:
            effective, _ = _effective_decision("ask", "PreToolUse", permission_mode)
            if quiet:
                _emit_quiet_audit(command, effective, f"no rule matched sub-command: {tokens[0]}")
                return
            if compact:
                cmd_label = cmd_text[:50]
                print(f"  {_colored('NO MATCH', _ANSI_YELLOW):<18} {cmd_label}")
            else:
                print(f"    {_colored('NO MATCH', _ANSI_YELLOW)} {_RARR} fallback ask")
            print(f"\n{_colored('Final:', _ANSI_BOLD)}  {_colored(effective, _DECISION_COLOR.get(effective, ''))}"
                  f" (no rule matched sub-command: {tokens[0]})")
            return

        if compact:
            c = _DECISION_COLOR.get(winner.action.value, "")
            cmd_label = cmd_text[:50]
            hint_str = f"  # {winner.hint}" if winner.hint else ""
            print(f"  {_cpad(winner.action.value, c, 10)} {winner.id:<14} {winner.normalized}"
                  f"  {_colored(cmd_label, _ANSI_DIM)}{hint_str}")

        if winner.action in (Action.DENY, Action.ASK, Action.REQUIRE_ASK):
            governing = winner
            break

        if governing is None or _beats(winner, governing):
            governing = winner

    if governing is None:
        effective, _ = _effective_decision("ask", "PreToolUse", permission_mode)
        if quiet:
            _emit_quiet_audit(command, effective, "no governing rule")
            return
        print(f"\n{_colored('Final:', _ANSI_BOLD)}  {_colored(effective, _DECISION_COLOR.get(effective, ''))}"
              f" (no governing rule)")
        return

    effective, reason_override = _effective_decision(governing.action.value, "PreToolUse", permission_mode)
    if quiet:
        governing_text = (
            f"{governing.id} line={governing.line} {governing.action.value} {governing.normalized}"
        )
        if reason_override:
            governing_text += f" (escalated in mode={permission_mode})"
        _emit_quiet_audit(command, effective, governing_text)
        return
    ec = _DECISION_COLOR.get(effective, "")
    if not compact and not quiet:
        print(f"\n{_colored('Governing:', _ANSI_BOLD)}  {governing.id} line={governing.line}"
              f"  {governing.action.value}  {governing.normalized}")
        if governing.hint:
            print(f"            hint: {governing.hint}")
        if reason_override:
            print(f"            escalated in mode={permission_mode}")
    print(f"\n{_colored('Final:', _ANSI_BOLD)}  {_colored(effective, ec)}")


# ---------------------------------------------------------------------------
# CLI: --replay
# ---------------------------------------------------------------------------

def _matches_search(command: str, search: Optional[str]) -> bool:
    """Case-insensitive OR match for comma-separated search terms."""
    if not search:
        return True
    haystack = command.lower()
    needles = [part.strip().lower() for part in search.split(",") if part.strip()]
    if not needles:
        return True
    return any(needle in haystack for needle in needles)


def cmd_replay(
    date_str: str,
    permission_mode: str = "default",
    search: Optional[str] = None,
) -> None:
    """Replay logged commands from a date and diff outcomes against current config."""
    from datetime import timedelta

    if not LOG_DIR.exists():
        print("No log directory found.")
        return

    # Handle "today" default — try today, fall back to yesterday
    if date_str == "today":
        today = datetime.now()
        log_date = today.strftime("%Y-%m-%d")
        log_file = LOG_DIR / f"{log_date}_commands.jsonl"
        if not log_file.exists():
            yesterday = today - timedelta(days=1)
            log_date = yesterday.strftime("%Y-%m-%d")
            log_file = LOG_DIR / f"{log_date}_commands.jsonl"
            if not log_file.exists():
                print(f"No log file for today or yesterday.")
                return
            print(f"(no log for today, using yesterday: {log_date})\n")
    else:
        # Normalize date input: accept 03-23-2026, 2026-03-23, etc.
        for fmt in ("%m-%d-%Y", "%Y-%m-%d", "%m/%d/%Y", "%Y/%m/%d"):
            try:
                dt = datetime.strptime(date_str, fmt)
                break
            except ValueError:
                continue
        else:
            print(f"Could not parse date: {date_str!r}")
            print("Accepted formats: MM-DD-YYYY, YYYY-MM-DD, MM/DD/YYYY, YYYY/MM/DD")
            sys.exit(1)

        log_date = dt.strftime("%Y-%m-%d")
        log_file = LOG_DIR / f"{log_date}_commands.jsonl"
        if not log_file.exists():
            print(f"No log file for {log_date}: {log_file}")
            return

    bash_rules, index, tool_rules = load_policy(CONF_PATH, JSON_PATH)

    entries: list[dict] = []
    malformed: list[tuple[int, str]] = []
    line_num = 0

    with open(log_file, "r", encoding="utf-8") as f:
        for raw_line in f:
            line_num += 1
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            try:
                entry = json.loads(raw_line)
            except json.JSONDecodeError as exc:
                malformed.append((line_num, f"JSON: {exc}"))
                continue

            # Validate expected structure
            if "result" not in entry:
                malformed.append((line_num, "missing 'result' key"))
                continue
            if "normalized" not in entry:
                malformed.append((line_num, "missing 'normalized' key"))
                continue

            entries.append(entry)

    if not entries and not malformed:
        print(f"No entries in {log_file}")
        return

    total = 0
    changed = 0
    unchanged = 0
    skipped = 0

    print(f"{_colored('Replaying', _ANSI_BOLD)} {len(entries)} entries from {log_date}")
    print(f"Policy:    {CONF_PATH}")
    print(f"Mode:      {permission_mode}")
    if search:
        print(f"Search:    {search}")
    print()
    print(f"{'#':<5} {'old':<12} {'new':<12} {'delta':<8} details")
    sep = _SEP_CHAR * 80
    print(sep)

    for i, entry in enumerate(entries):
        result = entry.get("result", {})
        old_decision = result.get("decision", "")
        if not old_decision:
            skipped += 1
            continue

        norm = entry.get("normalized", {})
        command = norm.get("command", "")
        tokens = norm.get("tokens", [])

        if not command and not tokens:
            skipped += 1
            continue

        total += 1
        full_command = command if command else " ".join(tokens)

        new_decision, new_detail = _replay_evaluate(
            command, tokens, bash_rules, index, tool_rules, permission_mode
        )

        # Normalize old decision for comparison (require_ask → ask in interactive)
        old_effective = old_decision
        if old_effective == "require_ask":
            old_effective = "ask"

        is_changed = old_effective != new_decision
        if is_changed:
            changed += 1
        else:
            unchanged += 1

        if is_changed:
            if not _matches_search(full_command, search):
                continue
            old_c = _DECISION_COLOR.get(old_effective, "")
            new_c = _DECISION_COLOR.get(new_decision, "")
            delta = _colored("CHANGED", _ANSI_RED)
            print(f"{total:<5} {_cpad(old_effective, old_c, 12)} {_cpad(new_decision, new_c, 12)}"
                  f" {delta:<18}")
            print(f"      cmd: {full_command}")
            old_rule = result.get('rule_id')
            old_reason = result.get('reason')
            if old_rule:
                print(f"      old: {old_rule}")
            elif old_reason:
                print(f"      old: {old_reason}")
            if new_detail:
                print(f"      new: {new_detail}")
            print()

    print(sep)
    print(f"\nTotal: {total}  Unchanged: {unchanged}  "
          f"{_colored(f'Changed: {changed}', _ANSI_RED if changed else _ANSI_GREEN)}  "
          f"Skipped: {skipped}")

    if malformed:
        print(f"\n{_colored(f'{len(malformed)} malformed line(s):', _ANSI_YELLOW)}")
        for ln, reason in malformed[:10]:
            print(f"  line {ln}: {reason}")
        if len(malformed) > 10:
            print(f"  ... {len(malformed) - 10} more")

    if changed == 0:
        print(_colored(f"\n{_CHK} No outcome changes -- current config matches logged behavior.", _ANSI_GREEN))
    else:
        print(_colored(f"\n{_WARN} {changed} command(s) would produce different outcomes with current config.", _ANSI_YELLOW))
        print("  Run --audit \"<command>\" on specific commands to investigate.")


def _rule_brief(rule: Rule | ToolRule) -> str:
    if isinstance(rule, ToolRule):
        target = f" {rule.path_pattern}" if rule.path_pattern is not None else ""
        return f"{rule.id} {rule.action.value} {rule.tool_name}{target}"
    return f"{rule.id} {rule.action.value} {rule.normalized}"


def _replay_evaluate(
    command: str,
    tokens: list[str],
    bash_rules: list[Rule],
    index: dict[str, list[int]],
    tool_rules: list[ToolRule],
    permission_mode: str,
) -> tuple[str, Optional[str]]:
    """Re-evaluate a single logged command against current rules."""
    if not tokens and command:
        tokens = strip_heredoc_bodies(command).lower().split()
    if not tokens:
        return "defer", "empty command"

    # Detect tool entries: check if first token is a known tool from $-rules
    known_tools = {r.tool_name for r in tool_rules}  # already lowercased
    first_lower = tokens[0].lower()

    if first_lower in known_tools and first_lower != "bash":
        tool_name = tokens[0]
        target = " ".join(tokens[1:]) if len(tokens) > 1 else ""
        winner = evaluate_tool(tool_rules, tool_name, target, debug=False)
        if winner is None:
            return "defer", "no matching tool rule"
        effective, _ = _effective_decision(winner.action.value, "PreToolUse", permission_mode)
        return effective, _rule_brief(winner)

    # Bash command evaluation
    pipe_shell = _check_pipe_to_shell(tokens)
    if pipe_shell:
        return "deny", f"pipe-to-shell: {pipe_shell}"

    push_guard = _check_git_protected_mutation(tokens)
    if push_guard:
        guard_decision, guard_reason = push_guard
        effective, _ = _effective_decision(guard_decision, "PreToolUse", permission_mode)
        return effective, f"protected-branch: {guard_reason}"

    raw_winner = _raw_pass(tokens, bash_rules, index, debug=False)
    if raw_winner is not None:
        effective, _ = _effective_decision(raw_winner.action.value, "PreToolUse", permission_mode)
        return effective, _rule_brief(raw_winner)

    cmd_str = command if command else " ".join(tokens)
    try:
        sub_commands = extract_commands(cmd_str)
    except ImportError:
        return "deny", "tree-sitter missing"

    if not sub_commands:
        effective, _ = _effective_decision("ask", "PreToolUse", permission_mode)
        return effective, "empty parse -> fallback ask"

    governing: Optional[Rule] = None

    for cmd_text in sub_commands:
        cleaned = strip_env_assignments(cmd_text)
        sub_tokens = cleaned.lower().split()
        if not sub_tokens:
            continue
        if all(t.strip("\\") == "" for t in sub_tokens):
            continue

        sub_guard = _check_git_protected_mutation(sub_tokens)
        if sub_guard:
            guard_decision, guard_reason = sub_guard
            effective, _ = _effective_decision(guard_decision, "PreToolUse", permission_mode)
            return effective, f"protected-branch: {guard_reason}"

        winner, _, _, _ = evaluate_bash(bash_rules, index, sub_tokens, debug=False)

        if winner is None:
            effective, _ = _effective_decision("ask", "PreToolUse", permission_mode)
            return effective, f"no rule matched sub-command: {sub_tokens[0]}"

        if winner.action in (Action.DENY, Action.ASK, Action.REQUIRE_ASK):
            governing = winner
            break

        if governing is None or _beats(winner, governing):
            governing = winner

    if governing is None:
        effective, _ = _effective_decision("ask", "PreToolUse", permission_mode)
        return effective, "no governing rule"

    effective, _ = _effective_decision(governing.action.value, "PreToolUse", permission_mode)
    return effective, _rule_brief(governing)


# ---------------------------------------------------------------------------
# Hook handlers
# ---------------------------------------------------------------------------

def _handle_tool(
    payload: dict,
    tool_rules: list[ToolRule],
    event: str,
    debug: bool,
    permission_mode: str = "default",
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

    decision, reason_override = _effective_decision(winner.action.value, event, permission_mode)

    if reason_override is not None:
        reason = reason_override
    elif decision in ("deny", "ask"):
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
    permission_mode: str = "default",
) -> None:
    tool_input = payload.get("tool_input") or {}
    raw_command = tool_input.get("command", "").strip()
    if not raw_command:
        return

    command = normalize(raw_command)
    precheck_command = strip_heredoc_bodies(command)
    raw_tokens = precheck_command.lower().split()

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

    # --- Pre-check 2: protected branch mutation guard ---
    push_guard = _check_git_protected_mutation(raw_tokens, debug=debug)
    if push_guard:
        guard_decision, guard_reason = push_guard
        effective_decision, reason_override = _effective_decision(guard_decision, event, permission_mode)
        reason = reason_override or guard_reason
        output = _emit(effective_decision, reason, event)
        log_decision(
            event=event,
            raw_input=payload,
            normalized_command=command,
            normalized_tokens=raw_tokens,
            decision=effective_decision,
            source="default",
            rule_id=None,
            reason="protected branch mutation",
            rules_evaluated=0,
            rules_matched=0,
            evaluations=[],
            output_payload=output,
        )
        return

    # --- Pre-check 3: raw pass — catches compound deny rules (redirects, etc.) ---
    raw_winner = _raw_pass(raw_tokens, bash_rules, index, debug)
    if raw_winner is not None:
        decision, reason_override = _effective_decision(raw_winner.action.value, event, permission_mode)
        if reason_override is not None:
            reason = reason_override
        elif decision in ("deny", "ask"):
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
        deny_reason = (
            "tree-sitter is not installed so compound Bash commands cannot be safely "
            "evaluated and are being denied. Inform the user that all Bash tool calls "
            "will be denied until the missing dependencies are installed: "
            "pip install tree-sitter tree-sitter-bash"
        )
        output = _emit("deny", deny_reason, event)
        log_decision(
            event=event,
            raw_input=payload,
            normalized_command=command,
            normalized_tokens=command.split(),
            decision="deny",
            source="default",
            rule_id=None,
            reason="tree-sitter missing",
            rules_evaluated=0,
            rules_matched=0,
            evaluations=[],
            output_payload=output,
        )
        return

    if not sub_commands:
        fallback_decision, fallback_reason = _effective_decision("ask", event, permission_mode)
        reason = fallback_reason or "no commands in parse tree — requires approval"
        output = _emit(fallback_decision, reason, event)
        log_decision(
            event=event,
            raw_input=payload,
            normalized_command=command,
            normalized_tokens=command.split(),
            decision=fallback_decision,
            source="default",
            rule_id=None,
            reason="no commands in parse tree",
            rules_evaluated=0,
            rules_matched=0,
            evaluations=[],
            output_payload=output,
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
        # Skip degenerate nodes: bare line-continuation backslashes, lone
        # punctuation, or other non-command artifacts from tree-sitter.
        if all(t.strip("\\") == "" for t in tokens):
            continue

        winner, n_eval, n_match, evals = evaluate_bash(bash_rules, index, tokens, debug=debug)
        total_evaluated += n_eval
        total_matched += n_match
        all_evals.extend(evals)

        if winner is None:
            # One sub-command has no matching rule — ask for approval
            fallback_decision, fallback_reason = _effective_decision("ask", event, permission_mode)
            reason = fallback_reason or f"no rule matched: {tokens[0][:60]} — requires approval"
            output = _emit(fallback_decision, reason, event)
            log_decision(
                event=event,
                raw_input=payload,
                normalized_command=command,
                normalized_tokens=tokens,
                decision=fallback_decision,
                source="default",
                rule_id=None,
                reason=f"no rule matched: {tokens[0][:60]}",
                rules_evaluated=total_evaluated,
                rules_matched=total_matched,
                evaluations=all_evals,
                output_payload=output,
            )
            return

        if winner.action in (Action.DENY, Action.ASK, Action.REQUIRE_ASK):
            governing = winner
            governing_tokens = tokens
            break  # deny/ask on any sub-command governs immediately

        if governing is None or _beats(winner, governing):
            governing = winner
            governing_tokens = tokens

    if governing is None:
        fallback_decision, fallback_reason = _effective_decision("ask", event, permission_mode)
        reason = fallback_reason or "evaluation produced no winner — requires approval"
        output = _emit(fallback_decision, reason, event)
        log_decision(
            event=event,
            raw_input=payload,
            normalized_command=command,
            normalized_tokens=command.split(),
            decision=fallback_decision,
            source="default",
            rule_id=None,
            reason="evaluation produced no winner",
            rules_evaluated=total_evaluated,
            rules_matched=total_matched,
            evaluations=all_evals,
            output_payload=output,
        )
        return

    decision, reason_override = _effective_decision(governing.action.value, event, permission_mode)

    if reason_override is not None:
        reason = reason_override
    elif decision in ("deny", "ask"):
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
    parser.add_argument("--usage", nargs="?", const=1, type=int, default=None,
                        help="Rule hit counts from logs (default: last 1 day, or --usage N for N days)")
    parser.add_argument("--audit", type=str, default=None,
                        help='Trace a command: --audit "git push origin main"')
    parser.add_argument("--target", type=str, default=None,
                        help="Mock PR base branch for --audit of gh pr merge (skips live gh pr view lookup)")
    parser.add_argument("--replay", nargs="?", const="today", type=str, default=None,
                        help="Replay a day's log (default: today, or --replay MM-DD-YYYY)")
    parser.add_argument("--search", type=str, default=None,
                        help='Filter replay output by case-insensitive comma-separated command terms, e.g. --search "git,gh"')
    parser.add_argument("--mode", type=str, default="default",
                        help="Permission mode for --audit/--replay (default, dontAsk, bypassPermissions)")
    parser.add_argument("--no-color", action="store_true",
                        help="Disable ANSI color codes in output (auto-set when stdout is not a tty)")
    parser.add_argument("--compact", action="store_true",
                        help="Compact audit output: one line per sub-command showing only the governing rule")
    parser.add_argument("-q", "--quiet", action="store_true",
                        help="Minimal audit output: '<command> --> <decision>' and governing rule")
    args, _ = parser.parse_known_args()

    if args.no_color:
        global _NO_COLOR
        _NO_COLOR = True

    if args.verify:
        cmd_verify()
        return

    if args.usage is not None:
        cmd_usage(days=args.usage)
        return

    if args.audit is not None:
        cmd_audit(args.audit, permission_mode=args.mode, compact=args.compact, quiet=args.quiet, target=args.target)
        return

    if args.replay is not None:
        cmd_replay(args.replay, permission_mode=args.mode, search=args.search)
        return

    raw_input = sys.stdin.read()

    try:
        payload = json.loads(raw_input)
    except json.JSONDecodeError:
        log_error("Failed to parse JSON input", raw_input)
        return

    event = payload.get("hook_event_name") or "PreToolUse"
    tool_name = payload.get("tool_name", "") or ""
    permission_mode = payload.get("permission_mode") or "default"

    if not tool_name:
        return

    bash_rules, index, tool_rules = load_policy(CONF_PATH, JSON_PATH, debug=args.debug)

    if args.debug:
        print(
            f"[debug] event={event} tool={tool_name} permission_mode={permission_mode}"
            f" bash_rules={len(bash_rules)} tool_rules={len(tool_rules)}",
            file=sys.stderr,
        )

    if tool_name == "Bash":
        _handle_bash(payload, bash_rules, index, event, args.debug, permission_mode)
    else:
        _handle_tool(payload, tool_rules, event, args.debug, permission_mode)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log_error(traceback.format_exc())
        sys.exit(0)

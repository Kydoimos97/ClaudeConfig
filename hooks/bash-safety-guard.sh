#!/bin/bash
# bash-safety-guard.sh -- PreToolUse hook for Bash commands
#
# Decision flow:
#   1. BLOCK   — matches blocked.commands  → hookSpecificOutput deny  (exit 0)
#   2. APPROVE — matches accepted.commands → hookSpecificOutput allow (exit 0)
#   3. PASS    — unknown                   → exit 0, dontAsk handles it
#
# Optimised for Windows/MINGW64: pure bash for all hot paths, no grep/sed/awk
# subshells in loops. Only 2 forks total (jq x2 for JSON parsing).

INPUT=$(cat)
INPUT="${INPUT//$'\n'/ }"   # collapse literal newlines — invalid in JSON strings

# ── Error logging ─────────────────────────────────────────────────────────────
_HOOK_NAME="bash-safety-guard"
_LOG_DIR="$HOME/.claude/custom_logs"
mkdir -p "$_LOG_DIR"
_ERR_TMP="$(mktemp)"
exec 2>"$_ERR_TMP"
_flush_errors() {
  local exit_code=$?
  [[ -s "$_ERR_TMP" ]] || { rm -f "$_ERR_TMP"; return; }
  local ts errs
  printf -v ts '%(%Y-%m-%dT%H:%M:%S)T' -1
  errs=$(<"$_ERR_TMP")
  errs="${errs//$'\n'/ | }"
  jq -cn \
    --arg ts "$ts" --arg hook "$_HOOK_NAME" \
    --argjson exit_code "$exit_code" --arg errors "$errs" \
    --arg raw_input "${INPUT:-}" \
    '{ts:$ts,hook:$hook,exit_code:$exit_code,input:($raw_input|if .=="" then null else (try fromjson catch $raw_input) end),errors:$errors}' \
    >> "$_LOG_DIR/hook_errors.jsonl"
  bash "$HOME/.claude/hooks/claude-notify.sh" error "$_HOOK_NAME" "${errs:0:100}"
  rm -f "$_ERR_TMP"
}
trap '_flush_errors' EXIT

# jq is unavoidable for JSON — use herestring to avoid extra echo fork
TOOL=$(jq -r '.tool_name // empty' <<< "$INPUT")
[[ "$TOOL" != "Bash" ]] && exit 0

COMMAND=$(jq -r '.tool_input.command // empty' <<< "$INPUT")
[[ -z "$COMMAND" ]] && exit 0

# Normalise Claude Code's path-prefixed rewrites:
#   git -C "/abs/path" status  →  git status
#   cd "/abs/path" && cmd      →  cmd
if [[ "$COMMAND" =~ ^git\ -C\ (\"[^\"]*\"|\'[^\']*\')\ (.+)$ ]]; then
  COMMAND="git ${BASH_REMATCH[2]}"
elif [[ "$COMMAND" =~ ^cd\ (\"[^\"]*\"|\'[^\']*\')\ \&\&\ (.+)$ ]]; then
  COMMAND="${BASH_REMATCH[2]}"
fi

_HOOKS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_BLOCKED_FILE="$_HOOKS_DIR/resources/blocked.commands"
_ACCEPTED_FILE="$_HOOKS_DIR/resources/accepted.commands"

# ──────────────────────────────────────────────────────────────────────────────
# DUMP — daily JSONL log for all commands (APPROVED/PROMPTED/BLOCKED)
# ──────────────────────────────────────────────────────────────────────────────
_LOG_DIR="$HOME/.claude/custom_logs"

dump() {
  local status="$1" reason="${2:-}"
  mkdir -p "$_LOG_DIR"
  local cmd_oneline ts
  cmd_oneline="${COMMAND//$'\n'/ }"
  cmd_oneline="${cmd_oneline//\\/\\\\}"
  cmd_oneline="${cmd_oneline//\"/\\\"}"
  printf -v ts '%(%Y-%m-%dT%H:%M:%S)T' -1
  if [[ -n "$reason" ]]; then
    local r="${reason//\\/\\\\}"
    r="${r//\"/\\\"}"
    printf '{"ts":"%s","status":"%s","command":"%s","reason":"%s"}\n' \
      "$ts" "$status" "$cmd_oneline" "$r"
  else
    printf '{"ts":"%s","status":"%s","command":"%s"}\n' \
      "$ts" "$status" "$cmd_oneline"
  fi >> "$_LOG_DIR/$(date +%Y-%m-%d)_commands.jsonl"
}

# ──────────────────────────────────────────────────────────────────────────────
# SECTION 1: BLOCK — load patterns from blocked.commands, match with bash =~
# Format: <regex>  @@  <reason>
# ──────────────────────────────────────────────────────────────────────────────
block() {
  dump "BLOCKED" "$1"
  local r="${1//\\/\\\\}"; r="${r//\"/\\\"}"
  printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"%s"}}\n' "$r"
  exit 0
}

if [[ -f "$_BLOCKED_FILE" ]]; then
  while IFS= read -r line; do
    [[ "$line" =~ ^[[:space:]]*# || -z "${line// }" ]] && continue
    # Split on  @@  using pure bash parameter expansion — zero forks
    pattern="${line%%  @@  *}"
    reason="${line#*  @@  }"
    pattern="${pattern%"${pattern##*[! ]}"}"  # rtrim
    [[ -z "$pattern" ]] && continue
    [[ "$COMMAND" =~ $pattern ]] && block "${reason:-BLOCKED: matched blocked pattern.}"
  done < "$_BLOCKED_FILE"
fi

# ──────────────────────────────────────────────────────────────────────────────
# SECTION 2: AUTO-APPROVE — pure bash prefix matching
# ──────────────────────────────────────────────────────────────────────────────

# Load accepted prefixes once into an array
_accepted=()
if [[ -f "$_ACCEPTED_FILE" ]]; then
  while IFS= read -r line; do
    [[ "$line" =~ ^[[:space:]]*# || -z "${line// }" ]] && continue
    line="${line#"${line%%[! ]*}"}"
    line="${line%"${line##*[! ]}"}"
    [[ -n "$line" ]] && _accepted+=("$line")
  done < "$_ACCEPTED_FILE"
fi

# Strip trailing redirects from a segment — pure bash =~ loops, no sed
# Patterns stored in vars to avoid bash inline-parsing issues with ? and &
_PAT_FD_REDIR='^(.*[^[:space:]])[[:space:]]+[12]?[>][&][12][[:space:]]*$'
_PAT_OUT_REDIR='^(.*[^[:space:]])[[:space:]]+[>][[:space:]]*[^[:space:]]+[[:space:]]*$'
_PAT_APPEND_REDIR='^(.*[^[:space:]])[[:space:]]+[>][>][[:space:]]*[^[:space:]]+[[:space:]]*$'

_strip_redirects() {
  local seg="$1"
  while [[ "$seg" =~ $_PAT_FD_REDIR ]];     do seg="${BASH_REMATCH[1]}"; done
  while [[ "$seg" =~ $_PAT_APPEND_REDIR ]]; do seg="${BASH_REMATCH[1]}"; done
  while [[ "$seg" =~ $_PAT_OUT_REDIR ]];    do seg="${BASH_REMATCH[1]}"; done
  printf '%s' "$seg"
}

_MATCH_PREFIX=""

is_safe_segment() {
  local seg="$1"

  seg="${seg#"${seg%%[! ]*}"}"
  seg="${seg%"${seg##*[! ]}"}"

  # Strip leading env var assignments (KEY=val KEY2=val2 cmd ...)
  while [[ "$seg" =~ ^[A-Z_][A-Z0-9_]*=[^[:space:]]*[[:space:]]+(.*) ]]; do
    seg="${BASH_REMATCH[1]}"
  done

  seg="$(_strip_redirects "$seg")"

  seg="${seg#"${seg%%[! ]*}"}"
  seg="${seg%"${seg##*[! ]}"}"

  [[ -z "$seg" ]] && return 0

  local prefix
  for prefix in "${_accepted[@]}"; do
    if [[ "$seg" == "$prefix" || "$seg" == "$prefix "* ]]; then
      _MATCH_PREFIX="$prefix"
      return 0
    fi
  done

  return 1
}

_FAIL_SEGMENT=""
all_safe=true
in_single=false
in_double=false
i=0
char=""
accumulated_segment=""
remaining="$COMMAND"

while (( i < ${#remaining} )); do
  char="${remaining:i:1}"

  if $in_single; then
    accumulated_segment+="$char"
    if [[ "$char" == "'" ]]; then
      in_single=false
    fi
    (( i++ ))
    continue
  fi

  if $in_double; then
    accumulated_segment+="$char"
    if [[ "$char" == '"' ]] && [[ "${remaining:i-1:1}" != '\' ]]; then
      in_double=false
    fi
    (( i++ ))
    continue
  fi

  if [[ "$char" == "'" ]]; then
    in_single=true
    accumulated_segment+="$char"
    (( i++ ))
    continue
  fi

  if [[ "$char" == '"' ]]; then
    in_double=true
    accumulated_segment+="$char"
    (( i++ ))
    continue
  fi

  if [[ "$char" == '&' ]] && [[ "${remaining:i+1:1}" == '&' ]]; then
    if ! is_safe_segment "$accumulated_segment"; then
      all_safe=false
      _FAIL_SEGMENT="$accumulated_segment"
      break
    fi
    accumulated_segment=""
    (( i += 2 ))
    continue
  fi

  if [[ "$char" == '|' ]] && [[ "${remaining:i+1:1}" == '|' ]]; then
    if ! is_safe_segment "$accumulated_segment"; then
      all_safe=false
      _FAIL_SEGMENT="$accumulated_segment"
      break
    fi
    accumulated_segment=""
    (( i += 2 ))
    continue
  fi

  if [[ "$char" == ';' ]]; then
    if ! is_safe_segment "$accumulated_segment"; then
      all_safe=false
      _FAIL_SEGMENT="$accumulated_segment"
      break
    fi
    accumulated_segment=""
    (( i++ ))
    continue
  fi

  if [[ "$char" == '|' ]]; then
    if ! is_safe_segment "$accumulated_segment"; then
      all_safe=false
      _FAIL_SEGMENT="$accumulated_segment"
      break
    fi
    accumulated_segment=""
    (( i++ ))
    continue
  fi

  accumulated_segment+="$char"
  (( i++ ))
done

if [[ "$all_safe" == "true" ]] && [[ -n "$accumulated_segment" ]]; then
  if ! is_safe_segment "$accumulated_segment"; then
    all_safe=false
    _FAIL_SEGMENT="$accumulated_segment"
  fi
fi

if [[ "$all_safe" == "true" ]]; then
  dump "APPROVED" "matched prefix: $_MATCH_PREFIX"
  printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"allow"}}\n'
  exit 0
fi

# ──────────────────────────────────────────────────────────────────────────────
# SECTION 3: PASS dump prompted
# ──────────────────────────────────────────────────────────────────────────────
dump "CONTINUE" "no accepted prefix for: ${_FAIL_SEGMENT:0:60}"

exit 0
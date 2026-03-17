#!/usr/bin/env bash
# claude-notify.sh — send a desktop notification
# Usage: claude-notify.sh <preset> [detail]
# Presets: approval, completed, elicitation, notification

preset="${1:-completed}"
detail="${2:-}"
repo="$(basename "$(git rev-parse --show-toplevel 2>/dev/null || pwd)")"
INPUT="{\"preset\":\"${1:-}\",\"detail\":\"${2:-}\"}"

# ── Error logging ─────────────────────────────────────────────────────────────
_HOOK_NAME="claude-notify"
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
  local _errtitle="${repo}: claude-notify failed"
  local _errmsg="${errs:0:100}"
  local _erricon='C:\Users\willem\.claude\hooks\resources\error_icon.png'
  pwsh -NoProfile -Command "
Import-Module BurntToast
if (Test-Path '$_erricon') {
    New-BurntToastNotification -Text '$_errtitle', '$_errmsg' -AppLogo '$_erricon' -Silent -Attribution 'Claude - $repo' -UniqueIdentifier 'error-$repo'
} else {
    New-BurntToastNotification -Text '$_errtitle', '$_errmsg' -Silent -Attribution 'Claude - $repo' -UniqueIdentifier 'error-$repo'
}
"
  rm -f "$_ERR_TMP"
}
trap '_flush_errors' EXIT

case "$preset" in
  approval)
    title="${repo}: Approval Needed"
    message="${detail:-Waiting for input}"
    icon='C:\Users\willem\.claude\hooks\resources\approval_icon.png'
    urgency="critical"
    ;;
  completed)
    title="${repo}: Claude Finished"
    message="${detail:-Processing complete}"
    icon='C:\Users\willem\.claude\hooks\resources\completed_icon.png'
    urgency="normal"
    ;;
  elicitation)
    title="${repo}: Input Required"
    message="${detail:-MCP server is requesting input}"
    icon='C:\Users\willem\.claude\hooks\resources\elicitation_icon.png'
    urgency="critical"
    ;;
  notification)
    title="${repo}: Claude"
    message="${detail:-Claude sent a notification}"
    icon='C:\Users\willem\.claude\hooks\resources\notification_icon.png'
    urgency="normal"
    ;;
  error)
    # $2 = hook name, $3 = error snippet
    title="${repo}: ${detail:-hook} failed"
    message="${3:-hook encountered an error}"
    icon='C:\Users\willem\.claude\hooks\resources\error_icon.png'
    urgency="critical"
    ;;
  *)
    echo "Unknown preset: $preset (use: approval, completed, elicitation, notification, error)" >&2
    exit 1
    ;;
esac

# ── Extract context from hook event JSON (piped on stdin) ────────────────────
if [[ -t 0 ]]; then
  _stdin=""
else
  _stdin="$(cat)"
fi

if [[ -n "$_stdin" ]] && command -v jq >/dev/null 2>&1; then
  _notif_type=""
  case "$preset" in
    approval)
      _tool="$(jq -r '.tool_name // empty' <<< "$_stdin" 2>/dev/null)"
      if [[ -n "$_tool" ]]; then
        case "$_tool" in
          Edit|Write)
            _path="$(jq -r '.tool_input.file_path // empty' <<< "$_stdin" 2>/dev/null)"
            _basename="${_path##*/}"
            [[ -n "$_basename" ]] && message="${_tool}: ${_basename}"
            ;;
          Bash)
            _cmd="$(jq -r '.tool_input.command // empty' <<< "$_stdin" 2>/dev/null)"
            [[ -n "$_cmd" ]] && message="Bash: ${_cmd:0:80}"
            ;;
          *)
            message="${_tool}: permission required"
            ;;
        esac
      fi
      ;;
    elicitation)
      _msg="$(jq -r '.message // empty' <<< "$_stdin" 2>/dev/null)"
      [[ -n "$_msg" ]] && message="${_msg:0:100}"
      _notif_type="$(jq -r '.notification_type // empty' <<< "$_stdin" 2>/dev/null)"
      ;;
    notification)
      _msg="$(jq -r '.message // empty' <<< "$_stdin" 2>/dev/null)"
      [[ -n "$_msg" ]] && message="${_msg:0:100}"
      _notif_type="$(jq -r '.notification_type // empty' <<< "$_stdin" 2>/dev/null)"
      ;;
  esac
fi

os="$(uname -s)"

# ──────────────────────────────────────────────────────────────────────────────
# Send notification
# ──────────────────────────────────────────────────────────────────────────────
notify_exit=0
case "$os" in
  MINGW*|MSYS*|CYGWIN*)
    pwsh -NoProfile -Command "
if (-not (Get-Module -ListAvailable BurntToast)) {
    Install-Module BurntToast -Scope CurrentUser -Force -AllowClobber
}
Import-Module BurntToast
\$expiry = (Get-Date).AddHours(1)
if (Test-Path '$icon') {
    New-BurntToastNotification -Text '$title', '$message' -AppLogo '$icon' -Silent -Attribution 'Claude - $repo' -UniqueIdentifier '$preset-$repo' -ExpirationTime \$expiry
} else {
    New-BurntToastNotification -Text '$title', '$message' -Silent -Attribution 'Claude - $repo' -UniqueIdentifier '$preset-$repo' -ExpirationTime \$expiry
}
"
    notify_exit=$?
    ;;
  Darwin*)
    osascript -e "display notification \"$message\" with title \"$title\""
    notify_exit=$?
    ;;
  Linux*)
    if command -v notify-send >/dev/null 2>&1; then
      notify-send -u "$urgency" -i "dialog-${urgency/normal/information}" "$title" "$message"
      notify_exit=$?
    fi
    ;;
esac

# ──────────────────────────────────────────────────────────────────────────────
# Log to ~/.claude/custom_logs/<date>_notif.jsonl
# ──────────────────────────────────────────────────────────────────────────────
_LOG_DIR=~/.claude/custom_logs
mkdir -p "$_LOG_DIR"

printf -v ts '%(%Y-%m-%dT%H:%M:%S)T' -1

detail_escaped="${detail//\\/\\\\}"
detail_escaped="${detail_escaped//\"/\\\"}"

_notif_type="${_notif_type:-}"
notif_type_escaped="${_notif_type//\"/\\\"}"

printf '{"ts":"%s","preset":"%s","notification_type":"%s","title":"%s","message":"%s","detail":"%s","repo":"%s","os":"%s","exit":%d}\n' \
  "$ts" "$preset" "$notif_type_escaped" "$title" "$message" "$detail_escaped" "$repo" "$os" "$notify_exit" \
  >> "$_LOG_DIR/$(date +%Y-%m-%d)_notif.jsonl"

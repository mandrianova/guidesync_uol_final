#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 ]]; then
  printf 'Usage: %s <browser-capture.json> <guide-output.md> [existing-guide.md] [title]\n' "$0" >&2
  exit 2
fi

CAPTURE_JSON="$1"
GUIDE_OUTPUT="$2"
EXISTING_GUIDE="${3:-}"
TITLE="${4:-GuideSync Generated Guide}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MVP_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
WORKSPACE_ROOT="$(cd "$MVP_ROOT/../.." && pwd)"

resolve_path() {
  local raw_path="$1"
  if [[ -z "$raw_path" || "$raw_path" == /* ]]; then
    printf '%s\n' "$raw_path"
  elif [[ -e "$raw_path" || -e "$(dirname "$raw_path")" ]]; then
    printf '%s/%s\n' "$(cd "$(dirname "$raw_path")" && pwd)" "$(basename "$raw_path")"
  elif [[ "$raw_path" == project/guidesync-mvp/* ]]; then
    printf '%s/%s\n' "$WORKSPACE_ROOT" "$raw_path"
  else
    printf '%s/%s\n' "$MVP_ROOT" "$raw_path"
  fi
}

CAPTURE_JSON="$(resolve_path "$CAPTURE_JSON")"
GUIDE_OUTPUT="$(resolve_path "$GUIDE_OUTPUT")"
if [[ -n "$EXISTING_GUIDE" ]]; then
  EXISTING_GUIDE="$(resolve_path "$EXISTING_GUIDE")"
fi

cd "$MVP_ROOT"
if [[ -n "$EXISTING_GUIDE" ]]; then
  uv run guidesync-guide --capture "$CAPTURE_JSON" --output "$GUIDE_OUTPUT" --existing-guide "$EXISTING_GUIDE" --title "$TITLE"
else
  uv run guidesync-guide --capture "$CAPTURE_JSON" --output "$GUIDE_OUTPUT" --title "$TITLE"
fi

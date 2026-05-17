#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  printf 'Usage: %s <task-json>\n' "$0" >&2
  exit 2
fi

TASK_JSON="$1"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MVP_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
WORKSPACE_ROOT="$(cd "$MVP_ROOT/../.." && pwd)"

if [[ "$TASK_JSON" != /* ]]; then
  if [[ -f "$TASK_JSON" ]]; then
    TASK_JSON="$(cd "$(dirname "$TASK_JSON")" && pwd)/$(basename "$TASK_JSON")"
  elif [[ -f "$WORKSPACE_ROOT/$TASK_JSON" ]]; then
    TASK_JSON="$WORKSPACE_ROOT/$TASK_JSON"
  elif [[ -f "$MVP_ROOT/$TASK_JSON" ]]; then
    TASK_JSON="$MVP_ROOT/$TASK_JSON"
  fi
fi

cd "$MVP_ROOT"
uv run guidesync-plan --task "$TASK_JSON"

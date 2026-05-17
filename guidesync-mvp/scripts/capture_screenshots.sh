#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 3 ]]; then
  printf 'Usage: %s <screenshot-plan.json> <screenshots-dir> <browser-capture.json> [capture flags]\n' "$0" >&2
  exit 2
fi

PLAN="$1"
SCREENSHOTS_DIR="$2"
OUTPUT="$3"
shift 3

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MVP_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$MVP_ROOT"
uv run guidesync-capture \
  --plan "$PLAN" \
  --screenshots-dir "$SCREENSHOTS_DIR" \
  --output "$OUTPUT" \
  "$@"

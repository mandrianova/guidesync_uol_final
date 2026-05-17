#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 ]]; then
  printf 'Usage: %s --input <release-task.json>\n' "$0" >&2
  printf '   or: %s --since <period> --output-dir <dir> --repo <repo-dir> [--repo <repo-dir> ...] [agent flags]\n' "$0" >&2
  exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MVP_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$MVP_ROOT"
uv run guidesync-agent "$@"

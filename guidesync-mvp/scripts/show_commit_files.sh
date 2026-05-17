#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

if [[ $# -ne 2 ]]; then
  printf 'Usage: %s <repo> <commit>\n' "$0" >&2
  printf 'Example: %s /path/to/repo abc1234\n' "$0" >&2
  exit 2
fi

repo="$1"
commit="$2"

require_repo "$repo"
path="$(repo_path "$repo")"

git -C "$path" show --stat --oneline --name-only "$commit"

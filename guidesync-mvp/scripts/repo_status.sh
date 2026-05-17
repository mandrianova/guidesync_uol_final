#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

if [[ "${#SCOPED_REPOS[@]}" -eq 0 ]]; then
  printf 'No repositories configured. Set GUIDESYNC_REPOS as a colon-separated list of repo paths or names.\n' >&2
  exit 2
fi

for repo in "${SCOPED_REPOS[@]}"; do
  require_repo "$repo"
  path="$(repo_path "$repo")"

  printf '\n== %s ==\n' "$repo"
  git -C "$path" status --short --branch
done

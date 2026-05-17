#!/usr/bin/env bash
set -euo pipefail

GUIDESYNC_REPO_ROOT="${GUIDESYNC_REPO_ROOT:-}"
GUIDESYNC_REPOS="${GUIDESYNC_REPOS:-}"

SCOPED_REPOS=()
if [[ -n "$GUIDESYNC_REPOS" ]]; then
  IFS=':' read -r -a SCOPED_REPOS <<< "$GUIDESYNC_REPOS"
fi

repo_path() {
  local repo="$1"
  if [[ "$repo" = /* ]]; then
    printf '%s\n' "$repo"
  elif [[ -n "$GUIDESYNC_REPO_ROOT" ]]; then
    printf '%s/%s\n' "$GUIDESYNC_REPO_ROOT" "$repo"
  else
    printf '%s\n' "$repo"
  fi
}

require_repo() {
  local repo="$1"
  local path
  path="$(repo_path "$repo")"

  if [[ ! -d "$path/.git" ]]; then
    printf 'Repository not found or not a git repo: %s\n' "$path" >&2
    return 1
  fi
}

print_scoped_repos() {
  if [[ "${#SCOPED_REPOS[@]}" -eq 0 ]]; then
    printf 'No repositories configured. Set GUIDESYNC_REPOS or use the JSON input agent.\n' >&2
    return 1
  fi
  local repo
  for repo in "${SCOPED_REPOS[@]}"; do
    printf '%s\n' "$repo"
  done
}

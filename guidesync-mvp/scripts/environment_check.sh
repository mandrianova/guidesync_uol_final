#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

printf '== Tooling ==\n'
for cmd in git bun node python3 uv; do
  if command -v "$cmd" >/dev/null 2>&1; then
    printf '%s: %s\n' "$cmd" "$(command -v "$cmd")"
  else
    printf '%s: missing\n' "$cmd"
  fi
done

if command -v docker >/dev/null 2>&1; then
  printf 'docker: %s\n' "$(command -v docker)"
else
  printf 'docker: missing\n'
fi

printf '\n== GuideSync Python runtime ==\n'
mvp_root="$(cd "$SCRIPT_DIR/.." && pwd)"
for file in pyproject.toml src/guidesync_mvp/capture.py; do
  if [[ -f "$mvp_root/$file" ]]; then
    printf '%s: present\n' "$file"
  else
    printf '%s: missing\n' "$file"
  fi
done

printf '\n== Scoped repositories ==\n'
if [[ "${#SCOPED_REPOS[@]}" -eq 0 ]]; then
  printf 'No repositories configured for this legacy check. Prefer scripts/run_release_agent.sh --input <task.json>.\n'
else
  for repo in "${SCOPED_REPOS[@]}"; do
    path="$(repo_path "$repo")"
    if [[ -d "$path/.git" ]]; then
      printf '%s: present\n' "$path"
    else
      printf '%s: missing\n' "$path"
    fi
  done
fi

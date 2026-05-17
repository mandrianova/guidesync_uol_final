#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  printf 'Usage: %s <task-json> [capture flags]\n' "$0" >&2
  exit 2
fi

TASK_JSON="$1"
shift

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

./scripts/validate_task_input.sh "$TASK_JSON"
./scripts/init_run_dirs.sh "$TASK_JSON"

PLAN_PATH="$(uv run guidesync-plan --task "$TASK_JSON")"

IFS=$'\t' read -r SCREENSHOTS_DIR CAPTURE_PATH GUIDE_PATH DOC_PATH TITLE < <(
  node -e '
const fs = require("fs");
const path = require("path");
const task = JSON.parse(fs.readFileSync(process.argv[1], "utf8"));
const mvpRoot = process.argv[2];
const workspaceRoot = process.argv[3];
const output = task.output || {};
const doc = task.documentation || {};
const title = (task.workflow && task.workflow.goal) || "GuideSync Generated Guide";
function resolveLocalPath(rawPath) {
  if (!rawPath) return "";
  if (path.isAbsolute(rawPath)) return rawPath;
  if (rawPath.startsWith("project/guidesync-mvp/")) return path.join(workspaceRoot, rawPath);
  return path.join(mvpRoot, rawPath);
}
console.log([
  resolveLocalPath(output.screenshots_dir || `${output.root}/screenshots`),
  resolveLocalPath(`${output.root}/browser-capture.json`),
  resolveLocalPath(output.guide_update_path || `${output.root}/guide-update.md`),
  resolveLocalPath(doc.path || ""),
  title
].join("\t"));
' "$TASK_JSON" "$MVP_ROOT" "$WORKSPACE_ROOT"
)

./scripts/capture_screenshots.sh "$PLAN_PATH" "$SCREENSHOTS_DIR" "$CAPTURE_PATH" "$@"
./scripts/generate_guide_draft.sh "$CAPTURE_PATH" "$GUIDE_PATH" "$DOC_PATH" "$TITLE"

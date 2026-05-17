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

node -e '
const fs = require("fs");
const path = require("path");
const taskPath = process.argv[1];
const mvpRoot = process.argv[2];
const workspaceRoot = process.argv[3];
const task = JSON.parse(fs.readFileSync(taskPath, "utf8"));
function resolveLocalPath(rawPath) {
  if (!rawPath) return "";
  if (path.isAbsolute(rawPath)) return rawPath;
  if (rawPath.startsWith("project/guidesync-mvp/")) return path.join(workspaceRoot, rawPath);
  return path.join(mvpRoot, rawPath);
}
const dirs = [
  resolveLocalPath(task.output?.root),
  resolveLocalPath(task.output?.screenshots_dir),
  path.dirname(resolveLocalPath(task.output?.report_path || "")),
  path.dirname(resolveLocalPath(task.output?.guide_update_path || ""))
].filter(Boolean);
for (const dir of dirs) {
  fs.mkdirSync(dir, { recursive: true });
  console.log(`created: ${dir}`);
}
' "$TASK_JSON" "$MVP_ROOT" "$WORKSPACE_ROOT"

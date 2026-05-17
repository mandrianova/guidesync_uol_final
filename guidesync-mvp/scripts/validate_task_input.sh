#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  printf 'Usage: %s <task-json>\n' "$0" >&2
  exit 2
fi

TASK_JSON="$1"

if [[ ! -f "$TASK_JSON" ]]; then
  printf 'Task JSON not found: %s\n' "$TASK_JSON" >&2
  exit 1
fi

node -e '
const fs = require("fs");
const path = process.argv[1];
const task = JSON.parse(fs.readFileSync(path, "utf8"));
const required = ["task_id", "created_at", "trigger", "project_root", "repositories", "time_window", "ui", "documentation", "output"];
const missing = required.filter((key) => task[key] === undefined);
if (missing.length) {
  console.error(`Missing required fields: ${missing.join(", ")}`);
  process.exit(1);
}
if (!Array.isArray(task.repositories) || task.repositories.length === 0) {
  console.error("repositories must be a non-empty array");
  process.exit(1);
}
for (const repo of task.repositories) {
  for (const key of ["name", "path", "branch"]) {
    if (!repo[key]) {
      console.error(`repository entry missing ${key}: ${JSON.stringify(repo)}`);
      process.exit(1);
    }
  }
}
console.log(`Task input OK: ${task.task_id}`);
' "$TASK_JSON"

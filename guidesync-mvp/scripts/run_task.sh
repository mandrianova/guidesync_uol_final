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

TASK_KIND="$(node -e '
const fs = require("fs");
const task = JSON.parse(fs.readFileSync(process.argv[1], "utf8"));
if (task.task && task.task.type === "project_init") {
  console.log("project_init");
} else if (task.period && task.repositories && !task.trigger && !task.time_window && !task.documentation) {
  console.log("release");
} else {
  console.log("unsupported");
}
' "$TASK_JSON")"

if [[ "$TASK_KIND" == "project_init" ]]; then
  exec ./scripts/init_project_from_task.sh "$TASK_JSON"
fi

if [[ "$TASK_KIND" == "release" ]]; then
  exec ./scripts/run_release_agent.sh --input "$TASK_JSON" "$@"
fi

printf 'Unsupported GuideSync task kind for %s. Use project-init-task.schema.json or release-task.schema.json.\n' "$TASK_JSON" >&2
exit 2

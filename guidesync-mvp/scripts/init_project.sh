#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 ]]; then
  printf 'Usage: %s <project-id> <project-name> [project-root]\n' "$0" >&2
  exit 2
fi

PROJECT_ID="$1"
PROJECT_NAME="$2"
PROJECT_ROOT="${3:-.}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MVP_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PROJECT_DIR="$MVP_ROOT/inputs/projects/$PROJECT_ID"

mkdir -p "$PROJECT_DIR"
mkdir -p "$MVP_ROOT/outputs/projects/$PROJECT_ID/tasks"

if [[ ! -f "$PROJECT_DIR/.env.example" ]]; then
  printf 'GUIDESYNC_AUTH0_TOKEN=\n' > "$PROJECT_DIR/.env.example"
fi

node -e '
const fs = require("fs");
const path = require("path");
const [projectDir, projectId, projectName, projectRoot] = process.argv.slice(1);
const project = {
  project: {
    id: projectId,
    name: projectName,
    description: "GuideSync project configuration. Fill in repositories and UI settings before running.",
    root: projectRoot,
    env_file: ".env"
  },
  defaults: {
    ref: "HEAD",
    output_root: `outputs/projects/${projectId}/tasks`
  }
};
const task = {
  project: project.project,
  task: {
    id: "recent-user-facing-changes",
    description: "Collect recent repository changes and produce user-facing release notes with UI evidence.",
    audience: "ordinary users",
    example_context: "Use examples that explain how a non-technical user would try the feature in the product UI."
  },
  repositories: [
    {
      name: "frontend",
      path: "/absolute/path/to/frontend-repo"
    }
  ],
  period: {
    since: "2 weeks ago"
  },
  ref: "HEAD",
  max_features: 8,
  auth: {
    mode: "token_env",
    env_file: ".env",
    token_env: "GUIDESYNC_AUTH0_TOKEN",
    role: "regular-user"
  },
  ui: {
    url: "http://localhost:3100",
    launch: {
      mode: "none",
      timeout_seconds: 90,
      down_after: false
    },
    max_screenshots: 5,
    expected_text: []
  },
  output: {
    title: `What is new in ${projectName}`
  }
};
fs.writeFileSync(path.join(projectDir, "project.json"), `${JSON.stringify(project, null, 2)}\n`);
fs.writeFileSync(path.join(projectDir, "release-task.json"), `${JSON.stringify(task, null, 2)}\n`);
' "$PROJECT_DIR" "$PROJECT_ID" "$PROJECT_NAME" "$PROJECT_ROOT"

printf '%s\n' "$PROJECT_DIR"

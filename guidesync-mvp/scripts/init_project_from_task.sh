#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  printf 'Usage: %s <project-init-task.json>\n' "$0" >&2
  exit 2
fi

TASK_JSON="$1"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MVP_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

node -e '
const fs = require("fs");
const path = require("path");

const [taskPath, mvpRoot] = process.argv.slice(1);
const task = JSON.parse(fs.readFileSync(taskPath, "utf8"));
const project = task.project || {};
const ui = task.ui || {};
const output = task.output || {};
const projectId = project.id;
const projectName = project.name || projectId;
if (!projectId || !projectName) {
  throw new Error("project.id and project.name are required");
}
const taskDir = path.dirname(taskPath);

function resolveProjectDir(rawPath) {
  if (rawPath) return path.isAbsolute(rawPath) ? rawPath : path.join(mvpRoot, rawPath);
  return path.join(mvpRoot, "inputs", "projects", projectId);
}

function resolveInputPath(rawPath) {
  if (!rawPath) return "";
  if (path.isAbsolute(rawPath)) return rawPath;
  const taskRelative = path.resolve(taskDir, rawPath);
  if (fs.existsSync(taskRelative)) return taskRelative;
  return path.resolve(mvpRoot, rawPath);
}

function repoPath(entry) {
  if (!entry) return "";
  if (typeof entry === "string") return entry;
  return entry.path || "";
}

function uiScanRoots() {
  const entries = [];
  if (ui.repository) entries.push(ui.repository);
  for (const entry of ui.repositories || []) entries.push(entry);
  if (!entries.length && project.root) entries.push(project.root);
  const seen = new Set();
  return entries
    .map((entry) => resolveInputPath(repoPath(entry)))
    .filter((entry) => entry && fs.existsSync(entry))
    .filter((entry) => {
      if (seen.has(entry)) return false;
      seen.add(entry);
      return true;
    });
}

function walk(dir, limit = 8000) {
  const result = [];
  const stack = [dir];
  const skip = new Set([".git", "node_modules", "dist", "build", ".next", "coverage", ".turbo", ".cache"]);
  while (stack.length && result.length < limit) {
    const current = stack.pop();
    let entries = [];
    try {
      entries = fs.readdirSync(current, { withFileTypes: true });
    } catch {
      continue;
    }
    for (const entry of entries) {
      if (skip.has(entry.name)) continue;
      const fullPath = path.join(current, entry.name);
      if (entry.isDirectory()) {
        stack.push(fullPath);
      } else {
        result.push(fullPath);
      }
    }
  }
  return result;
}

function scoreLogo(filePath, projectId, projectName) {
  const normalized = filePath.toLowerCase();
  const base = path.basename(normalized, path.extname(normalized));
  const projectTokens = [projectId, projectName]
    .filter(Boolean)
    .flatMap((value) => String(value).toLowerCase().split(/[^a-z0-9]+/))
    .filter((value) => value.length >= 3);
  let score = 0;
  if (/^(logo|brand|wordmark|mark)$/.test(base)) score += 30;
  if (/logo|brand|wordmark|mark/.test(normalized)) score += 20;
  if (projectTokens.some((token) => base.includes(token))) score += 35;
  if (projectTokens.some((token) => normalized.includes(`/${token}/`) || normalized.includes(`${token}-`))) score += 12;
  if (/public|assets|static|images|img/.test(normalized)) score += 8;
  if (/favicon|apple-touch|mask-icon|sprite|loader|empty|illustration/.test(normalized)) score -= 12;
  if (/copilot|demo|storybook|fixture|test/.test(normalized) && !projectTokens.some((token) => normalized.includes(token))) score -= 18;
  if (normalized.endsWith(".svg")) score += 8;
  if (normalized.includes("icon")) score -= 4;
  return score;
}

function findLogo(files, projectId, projectName) {
  const candidates = files
    .filter((file) => /\.(svg|png|jpg|jpeg|webp)$/i.test(file))
    .map((file) => ({ file, score: scoreLogo(file, projectId, projectName) }))
    .sort((a, b) => b.score - a.score);
  return (candidates.find((candidate) => candidate.score > 0) || {}).file || "";
}

function hexToRgb(hex) {
  const value = hex.replace("#", "");
  const full = value.length === 3 ? value.split("").map((part) => part + part).join("") : value;
  if (full.length !== 6) return null;
  return [parseInt(full.slice(0, 2), 16), parseInt(full.slice(2, 4), 16), parseInt(full.slice(4, 6), 16)];
}

function luminance(hex) {
  const rgb = hexToRgb(hex);
  if (!rgb) return 0;
  return (0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]) / 255;
}

function colorDistance(a, b) {
  const left = hexToRgb(a);
  const right = hexToRgb(b);
  if (!left || !right) return 0;
  return Math.sqrt(left.reduce((sum, value, index) => sum + Math.pow(value - right[index], 2), 0));
}

function normalizeHex(raw) {
  const value = raw.toLowerCase();
  if (value.length === 4) {
    return `#${value[1]}${value[1]}${value[2]}${value[2]}${value[3]}${value[3]}`;
  }
  return value;
}

function findColors(files) {
  const colorScores = new Map();
  const sourceFiles = files.filter((file) => /\.(css|scss|sass|less|tsx|jsx|ts|js|html|svg)$/i.test(file)).slice(0, 1200);
  for (const file of sourceFiles) {
    let text = "";
    try {
      text = fs.readFileSync(file, "utf8").slice(0, 200000);
    } catch {
      continue;
    }
    const lowerPath = file.toLowerCase();
    const pathBoost = /theme|brand|token|style|tailwind|app|global|layout/.test(lowerPath) ? 3 : 1;
    for (const match of text.matchAll(/#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?\b/g)) {
      const color = normalizeHex(match[0]);
      const lum = luminance(color);
      if (lum > 0.94 || lum < 0.03) continue;
      colorScores.set(color, (colorScores.get(color) || 0) + pathBoost);
    }
  }
  const ranked = [...colorScores.entries()]
    .filter(([color]) => colorDistance(color, "#ffffff") > 35 && colorDistance(color, "#000000") > 35)
    .sort((a, b) => b[1] - a[1])
    .map(([color]) => color);
  const primary = ranked.find((color) => luminance(color) < 0.35) || ranked[0] || "#171b1f";
  const accent = ranked.find((color) => colorDistance(color, primary) > 90 && luminance(color) > 0.2 && luminance(color) < 0.75) || "#ff5a1f";
  const secondary = ranked.find((color) => color !== primary && color !== accent && colorDistance(color, accent) > 70) || "#126b7f";
  return {
    primary,
    secondary,
    accent,
    background: "#fbfaf7",
    text: luminance(primary) < 0.55 ? primary : "#171b1f"
  };
}

const projectDir = resolveProjectDir(output.project_dir);
const templatesDir = path.join(projectDir, "templates");
const assetsDir = path.join(projectDir, "assets");
const projectOutputDir = path.join(mvpRoot, "outputs", "projects", projectId);
fs.mkdirSync(templatesDir, { recursive: true });
fs.mkdirSync(assetsDir, { recursive: true });
fs.mkdirSync(path.join(projectOutputDir, "tasks"), { recursive: true });

const scanRoots = uiScanRoots();
const files = scanRoots.flatMap((scanRoot) => walk(scanRoot));
const colors = findColors(files);
const discoveredLogo = findLogo(files, projectId, projectName);
const logoExtension = discoveredLogo ? path.extname(discoveredLogo).toLowerCase() || ".svg" : ".svg";
const logoFile = `assets/logo${logoExtension}`;
const cssFile = "templates/brand.css";
const copyFile = "templates/copy.json";
const logoPath = path.join(projectDir, logoFile);
const cssPath = path.join(projectDir, cssFile);
const copyPath = path.join(projectDir, copyFile);

fs.writeFileSync(cssPath, `:root {
  --bg: ${colors.background};
  --ink: ${colors.text};
  --muted: #5f6972;
  --line: #dde2e4;
  --panel: #ffffff;
  --soft: color-mix(in srgb, ${colors.secondary} 9%, #ffffff);
  --accent: ${colors.accent};
  --accent-2: ${colors.secondary};
  --accent-3: color-mix(in srgb, ${colors.primary} 72%, ${colors.accent});
}

.hero-panel,
.spotlight,
.update-card {
  border-color: color-mix(in srgb, var(--accent-2) 18%, var(--line));
}
`);

if (discoveredLogo) {
  fs.copyFileSync(discoveredLogo, logoPath);
} else if (!fs.existsSync(logoPath)) {
  const safeName = String(projectName).replace(/[<&>"]/g, "");
  fs.writeFileSync(logoPath, `<svg xmlns="http://www.w3.org/2000/svg" width="160" height="44" viewBox="0 0 160 44" role="img" aria-label="${safeName}">
  <rect width="160" height="44" fill="${colors.primary}"/>
  <circle cx="28" cy="22" r="10" fill="${colors.accent}"/>
  <text x="48" y="29" fill="#ffffff" font-family="Inter, Arial, sans-serif" font-size="22" font-weight="800">${safeName}</text>
</svg>
`);
}

if (!fs.existsSync(copyPath)) {
  fs.writeFileSync(copyPath, "{\n  \"text\": {},\n  \"feature_copy\": {}\n}\n");
}

const projectJson = {
  $schema: "../../project.schema.json",
  project: {
    id: projectId,
    name: projectName,
    description: project.description || "GuideSync project configuration.",
    root: project.root || (scanRoots[0] || ""),
    env_file: project.env_file || ".env",
    languages: project.languages || ["en"],
    branding: {
      name: projectName,
      logo_file: logoFile,
      css_file: cssFile
    },
    copy: {
      catalog_file: copyFile
    }
  },
  defaults: {
    ref: "HEAD",
    ui_url: ui.url || "",
    output_root: `outputs/projects/${projectId}/tasks`,
    ui: {
      repository: ui.repository || (ui.repositories && ui.repositories[0]) || "",
      repositories: ui.repositories || [],
      route_overrides: {}
    }
  }
};

const releaseTaskPath = path.join(projectDir, "release-task.json");
fs.writeFileSync(path.join(projectDir, "project.json"), `${JSON.stringify(projectJson, null, 2)}\n`);
if (!fs.existsSync(path.join(projectDir, ".env.example"))) {
  fs.writeFileSync(path.join(projectDir, ".env.example"), "GUIDESYNC_AUTH0_TOKEN=\n");
}
if (!fs.existsSync(releaseTaskPath)) {
  const releaseTask = {
    $schema: "../../release-task.schema.json",
    task_id: `${projectId}-recent-user-facing-changes`,
    project: projectJson.project,
    task: {
      id: "recent-user-facing-changes",
      description: "Collect recent repository changes and produce user-facing release notes with UI evidence.",
      audience: "ordinary users",
      example_context: "Use examples that explain how a non-technical user would try the feature in the product UI."
    },
    repositories: [{ name: "frontend", path: "/absolute/path/to/frontend-repo" }],
    period: { since: "2 weeks ago" },
    ref: "HEAD",
    max_features: 8,
    auth: { mode: "token_env", env_file: ".env", token_env: "GUIDESYNC_AUTH0_TOKEN", role: "regular-user" },
    ui: { url: ui.url || "", launch: { mode: "none", timeout_seconds: 90, down_after: false }, max_screenshots: 5, expected_text: ui.expected_text || [] },
    output: { title: `What is new in ${projectName}` }
  };
  fs.writeFileSync(releaseTaskPath, `${JSON.stringify(releaseTask, null, 2)}\n`);
}

const report = {
  project_dir: projectDir,
  report_path: path.join(projectOutputDir, "init-report.json"),
  scanned_roots: scanRoots,
  scanned_files: files.length,
  logo_source: discoveredLogo || "generated fallback",
  colors
};
fs.writeFileSync(path.join(projectOutputDir, "init-report.json"), `${JSON.stringify(report, null, 2)}\n`);
console.log(projectDir);
' "$TASK_JSON" "$MVP_ROOT"

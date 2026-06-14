const projectList = document.querySelector("#project-list");
const projectOverview = document.querySelector("#project-overview");
const newProjectButton = document.querySelector("#new-project");
const projectForm = document.querySelector("#project-form");
const projectStatus = document.querySelector("#project-status");
const pageTitle = document.querySelector("#page-title");
const repositoryEditorList = document.querySelector("#repository-editor-list");
const addRepositoryButton = document.querySelector("#add-repository");
const runForm = document.querySelector("#run-form");
const runRepositoryList = document.querySelector("#run-repository-list");
const periodPanel = document.querySelector("#period-panel");
const branchPanel = document.querySelector("#branch-panel");
const statusPill = document.querySelector("#status-pill");
const pipelineReport = document.querySelector("#pipeline-report");
const changeReport = document.querySelector("#change-report");
const findingCount = document.querySelector("#finding-count");
const artifactLink = document.querySelector("#artifact-link");
const reportHistory = document.querySelector("#report-history");
const refreshReportsButton = document.querySelector("#refresh-reports");
const pageButtons = document.querySelectorAll("[data-page-target]");
const pages = document.querySelectorAll("[data-page]");
const modelSettingsForm = document.querySelector("#model-settings-form");
const modelSettingsStatus = document.querySelector("#model-settings-status");

let projects = [];
let currentProject = null;
let branchCache = {};
let branchWarnings = {};
let branchSortByRepo = {};
let currentPage = "projects";
let activeRunPollTimer = null;
let activeRenderedReportId = null;

const pageTitles = {
  projects: "Projects",
  "app-settings": "AI model",
  settings: "Project setup",
  run: "Run analysis",
  reports: "Reports",
};

function updatePageTitle() {
  const baseTitle = pageTitles[currentPage] || "Project workspace";
  if (currentPage === "projects" || currentPage === "app-settings" || !currentProject?.id) {
    pageTitle.textContent = baseTitle;
    return;
  }
  pageTitle.textContent = `${baseTitle} · ${currentProject.name}`;
}

function uid(prefix) {
  return `${prefix}-${crypto.randomUUID().slice(0, 10)}`;
}

function isoDate(daysAgo) {
  const date = new Date();
  date.setDate(date.getDate() - daysAgo);
  return date.toISOString().slice(0, 10);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

async function requestJson(url, options = {}) {
  const response = await fetch(url, {
    headers: { "content-type": "application/json" },
    ...options,
  });
  if (!response.ok) {
    const body = await response.text();
    throw new Error(`${response.status}: ${body}`);
  }
  return response.json();
}

async function requestText(url) {
  const response = await fetch(url);
  if (!response.ok) {
    const body = await response.text();
    throw new Error(`${response.status}: ${body}`);
  }
  return response.text();
}

function artifactUrl(runId, filename, params = {}) {
  const query = new URLSearchParams(params).toString();
  return `/runs/${encodeURIComponent(runId)}/artifacts/${encodeURIComponent(filename)}${query ? `?${query}` : ""}`;
}

function renderInlineMarkdown(value) {
  return escapeHtml(value)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(
      /\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g,
      '<a href="$2" target="_blank" rel="noreferrer">$1</a>',
    );
}

function renderMarkdown(markdown) {
  const blocks = [];
  let paragraph = [];
  let listItems = [];

  const flushParagraph = () => {
    if (!paragraph.length) {
      return;
    }
    blocks.push(`<p>${renderInlineMarkdown(paragraph.join(" "))}</p>`);
    paragraph = [];
  };

  const flushList = () => {
    if (!listItems.length) {
      return;
    }
    blocks.push(`<ul>${listItems.map((item) => `<li>${item}</li>`).join("")}</ul>`);
    listItems = [];
  };

  markdown.split(/\r?\n/).forEach((rawLine) => {
    const line = rawLine.trim();
    if (!line) {
      flushParagraph();
      flushList();
      return;
    }
    if (line.startsWith("#")) {
      flushParagraph();
      flushList();
      const marker = line.match(/^#{1,3}/)?.[0] || "#";
      const level = marker.length;
      blocks.push(`<h${level}>${renderInlineMarkdown(line.slice(level).trim())}</h${level}>`);
      return;
    }
    if (line.startsWith("- ")) {
      flushParagraph();
      listItems.push(renderInlineMarkdown(line.slice(2).trim()));
      return;
    }
    flushList();
    paragraph.push(line);
  });

  flushParagraph();
  flushList();
  return blocks.join("");
}

function blankProject() {
  return {
    id: null,
    name: "Untitled documentation project",
    description: "",
    repositories: [
      {
        id: uid("repo"),
        name: "repository",
        url: "https://github.com/pydantic/pydantic-ai",
        default_branch: "main",
        paths: [],
      },
    ],
    documentation: [
      {
        id: "doc-primary",
        name: "documentation-context",
        description: "Editable project documentation context stored in the database.",
        content:
          "Describe the intended user-facing documentation area, current assumptions, terminology, and known stale sections here.",
      },
    ],
  };
}

function activeRunMode() {
  return document.querySelector("input[name='run-mode']:checked").value;
}

function renderProjectList() {
  const items = projects
    .map(
      (project) => `
        <button
          class="project-button ${currentProject?.id === project.id ? "active" : ""}"
          data-project-id="${escapeHtml(project.id)}"
          type="button"
        >
          <strong>${escapeHtml(project.name)}</strong>
          <span>${escapeHtml(project.repositories?.length || 0)} repositories</span>
        </button>`,
    )
    .join("");
  projectList.innerHTML = items || `<p class="muted">No saved projects yet.</p>`;
}

function renderProjectOverview() {
  if (!projects.length) {
    projectOverview.innerHTML = `
      <div class="empty-state">
        Create a project to start tracking repository changes.
      </div>`;
    return;
  }
  projectOverview.innerHTML = projects
    .map(
      (project) => `
        <article class="project-summary ${currentProject?.id === project.id ? "active" : ""}">
          <div>
            <h3>${escapeHtml(project.name)}</h3>
            <p>${escapeHtml(project.description || "No description added yet.")}</p>
          </div>
          <div class="summary-metrics">
            <span>${escapeHtml(project.repositories?.length || 0)} repositories</span>
            <span>${escapeHtml(project.documentation?.length || 0)} context docs</span>
          </div>
          <div class="summary-actions">
            <button class="primary compact-action" data-project-id="${escapeHtml(project.id)}" data-open-page="run" type="button">Run analysis</button>
            <button class="secondary compact-action" data-project-id="${escapeHtml(project.id)}" data-open-page="reports" type="button">Reports</button>
            <button class="ghost compact-action" data-project-id="${escapeHtml(project.id)}" data-open-page="settings" type="button">Edit</button>
          </div>
        </article>`,
    )
    .join("");
}

function navigate(page) {
  currentPage = page;
  pages.forEach((element) => {
    element.classList.toggle("active", element.dataset.page === page);
  });
  pageButtons.forEach((button) => {
    button.classList.toggle("active", button.dataset.pageTarget === page);
  });
  updatePageTitle();
}

function setProject(project, statusText = null) {
  currentProject = structuredClone(project);
  document.querySelector("#project-name").value = currentProject.name || "";
  document.querySelector("#project-description").value = currentProject.description || "";
  document.querySelector("#doc-content").value = currentProject.documentation?.[0]?.content || "";
  projectStatus.textContent = statusText || (currentProject.id ? "Saved" : "Draft");
  branchCache = {};
  branchWarnings = {};
  branchSortByRepo = {};
  renderProjectList();
  renderProjectOverview();
  renderRepositoryEditors();
  renderRunRepositories();
  loadReports().catch(renderReportLoadError);
  updatePageTitle();
}

function repositoryFromCard(card) {
  return {
    id: card.dataset.repoId,
    name: card.querySelector("[data-field='name']").value.trim(),
    url: card.querySelector("[data-field='url']").value.trim(),
    default_branch: card.querySelector("[data-field='default_branch']").value.trim() || null,
    paths: card
      .querySelector("[data-field='paths']")
      .value.split(",")
      .map((item) => item.trim())
      .filter(Boolean),
  };
}

function projectPayload() {
  const repositories = [...repositoryEditorList.querySelectorAll(".repo-card")]
    .map(repositoryFromCard)
    .filter((repository) => repository.name && repository.url);
  return {
    name: document.querySelector("#project-name").value.trim(),
    description: document.querySelector("#project-description").value.trim() || null,
    repositories,
    documentation: [
      {
        id: currentProject?.documentation?.[0]?.id || "doc-primary",
        name: currentProject?.documentation?.[0]?.name || "documentation-context",
        description: "Editable project documentation context stored in the database.",
        content: document.querySelector("#doc-content").value,
      },
    ],
  };
}

function renderRepositoryEditors() {
  const repositories = currentProject?.repositories?.length
    ? currentProject.repositories
    : blankProject().repositories;
  repositoryEditorList.innerHTML = repositories
    .map(
      (repository, index) => `
        <article class="repo-card" data-repo-id="${escapeHtml(repository.id || uid("repo"))}">
          <div class="repo-card-head">
            <div>
              <h4>Repository ${index + 1}</h4>
              <p class="panel-note">${escapeHtml(repository.url || "Public GitHub URL")}</p>
            </div>
            <button class="secondary remove-repo" type="button" data-action="remove-repo">
              Remove
            </button>
          </div>
          <div class="two-col">
            <label>
              Name
              <input data-field="name" value="${escapeHtml(repository.name)}" />
            </label>
            <label>
              Default branch
              <input data-field="default_branch" value="${escapeHtml(repository.default_branch || "main")}" />
            </label>
          </div>
          <label>
            GitHub URL
            <input data-field="url" value="${escapeHtml(repository.url)}" />
          </label>
          <label>
            Path filters
            <input data-field="paths" value="${escapeHtml((repository.paths || []).join(", "))}" placeholder="Optional: docs/, src/package/" />
          </label>
        </article>`,
    )
    .join("");
}

function renderRunRepositories() {
  const repositories = projectPayload().repositories;
  const mode = activeRunMode();
  periodPanel.classList.toggle("hidden", mode !== "default_branch_period");
  branchPanel.classList.toggle("hidden", mode !== "select_branches");

  runRepositoryList.innerHTML = repositories
    .map((repository) => {
      const defaultBranch = repository.default_branch || "main";
      const branches = branchCache[repository.id] || [];
      const branchWarning = branchWarnings[repository.id] || "";
      const branchSort = branchSortByRepo[repository.id] || "updated_desc";
      const branchControls =
        mode === "select_branches"
          ? `
            <div class="branch-toolbar">
              <button class="secondary" type="button" data-action="load-branches" data-repo-id="${escapeHtml(repository.id)}">
                Load branch list
              </button>
              <label>
                Sort
                <select data-action="sort-branches" data-repo-id="${escapeHtml(repository.id)}">
                  <option value="updated_desc" ${branchSort === "updated_desc" ? "selected" : ""}>Newest first</option>
                  <option value="name_asc" ${branchSort === "name_asc" ? "selected" : ""}>Name A-Z</option>
                  <option value="name_desc" ${branchSort === "name_desc" ? "selected" : ""}>Name Z-A</option>
                </select>
              </label>
            </div>
            <div class="branch-list" data-branches-for="${escapeHtml(repository.id)}">
              ${renderBranchChoices(repository, branches, branchWarning, branchSort)}
            </div>`
          : `<p class="panel-note">Analyzing ${escapeHtml(defaultBranch)} with the selected period.</p>`;
      return `
        <article class="run-repo-card" data-repo-id="${escapeHtml(repository.id)}">
          <div class="run-repo-head">
            <div>
              <h4>${escapeHtml(repository.name)}</h4>
              <p class="panel-note">${escapeHtml(repository.url)}</p>
            </div>
            <span class="status-pill">${escapeHtml(defaultBranch)}</span>
          </div>
          ${branchControls}
        </article>`;
    })
    .join("");
}

function normalizeBranch(branch) {
  return typeof branch === "string" ? { name: branch, updated_at: null } : branch;
}

function formatBranchDate(value) {
  if (!value) {
    return "Date unavailable";
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return parsed.toLocaleString();
}

function sortBranches(branches, sortMode) {
  const normalized = branches.map(normalizeBranch);
  return normalized.sort((left, right) => {
    if (sortMode === "name_desc") {
      return String(right.name || "").localeCompare(String(left.name || ""));
    }
    if (sortMode === "name_asc") {
      return String(left.name || "").localeCompare(String(right.name || ""));
    }
    return String(right.updated_at || "").localeCompare(String(left.updated_at || ""));
  });
}

function renderBranchChoices(repository, branches, warning = "", sortMode = "updated_desc") {
  if (warning) {
    return `<p class="branch-warning">${escapeHtml(warning)}</p>`;
  }
  if (!branches.length) {
    return `<p class="panel-note">Load branches to choose from the repository branch list.</p>`;
  }
  const defaultBranch = repository.default_branch || "main";
  return sortBranches(branches, sortMode)
    .map(
      (branch) => `
        <label class="branch-choice">
          <input
            type="checkbox"
            value="${escapeHtml(branch.name)}"
            ${branch.name === defaultBranch ? "checked" : ""}
          />
          <span>
            <strong>${escapeHtml(branch.name)}</strong>
            <small>${escapeHtml(formatBranchDate(branch.updated_at))}</small>
          </span>
        </label>`,
    )
    .join("");
}

function modelSettingsPayload() {
  const provider = document.querySelector("#provider-kind").value;
  const model = document.querySelector("#provider-model").value.trim();
  const baseUrl = document.querySelector("#provider-base-url").value.trim();
  const apiKey = document.querySelector("#provider-api-key").value.trim();
  const timeout = Number.parseInt(document.querySelector("#provider-timeout").value, 10);
  const payload = {
    provider,
    model: model || (provider === "mock" ? "mock:deterministic" : "google/gemma-4-31b-qat"),
    timeout_seconds: Number.isFinite(timeout) && timeout > 0 ? timeout : 60,
  };
  if (baseUrl) {
    payload.base_url = baseUrl;
  }
  if (apiKey) {
    payload.api_key = apiKey;
  }
  payload.clear_api_key = document.querySelector("#provider-clear-api-key").checked;
  return payload;
}

function applyModelSettings(settings) {
  document.querySelector("#provider-kind").value = settings.provider || "local_http";
  document.querySelector("#provider-model").value = settings.model || "google/gemma-4-31b-qat";
  document.querySelector("#provider-base-url").value =
    settings.base_url || "http://localhost:1234/api/v1/chat";
  document.querySelector("#provider-timeout").value = settings.timeout_seconds || 60;
  document.querySelector("#provider-api-key").value = "";
  document.querySelector("#provider-api-key").placeholder = settings.has_api_key
    ? "Saved token is configured"
    : "Optional for local runs";
  document.querySelector("#provider-clear-api-key").checked = false;
  modelSettingsStatus.textContent = settings.has_api_key ? "Saved with token" : "Saved";
}

function selectedBranchesByRepo() {
  const selected = {};
  for (const card of runRepositoryList.querySelectorAll(".run-repo-card")) {
    const branches = [...card.querySelectorAll("input[type='checkbox']:checked")].map(
      (input) => input.value,
    );
    if (branches.length) {
      selected[card.dataset.repoId] = branches;
    }
  }
  return selected;
}

async function loadProjects(selectedId = null) {
  projects = await requestJson("/projects");
  const selectedProject =
    projects.find((project) => project.id === selectedId) ||
    projects.find((project) => project.id === currentProject?.id) ||
    projects[0];
  if (selectedProject) {
    setProject(selectedProject);
  } else {
    setProject(blankProject());
  }
}

async function loadReports() {
  if (!currentProject?.id) {
    renderReportHistory([]);
    return;
  }
  const reports = await requestJson(`/projects/${currentProject.id}/runs`);
  renderReportHistory(reports);
}

function renderReportHistory(reports) {
  if (!reports.length) {
    reportHistory.innerHTML = `<div class="empty-state">No saved reports for this project yet.</div>`;
    return;
  }
  reportHistory.innerHTML = reports
    .map((report) => {
      const createdAt = report.created_at ? new Date(report.created_at).toLocaleString() : "";
      const updatedAt = report.updated_at ? new Date(report.updated_at).toLocaleString() : "";
      const provider = [report.provider, report.model].filter(Boolean).join(" · ") || "provider n/a";
      return `
        <button class="report-history-item" data-run-id="${escapeHtml(report.run_id)}" type="button">
          <span>
            <strong>${escapeHtml(report.title)}</strong>
            <small>Created ${escapeHtml(createdAt)}</small>
          </span>
          <span class="report-meta">
            <span class="status-pill">${escapeHtml(report.status)}</span>
            <small>${escapeHtml(provider)} · ${escapeHtml(updatedAt)}</small>
          </span>
        </button>`;
    })
    .join("");
}

function renderReportLoadError(error) {
  reportHistory.innerHTML = `
    <div class="empty-state">
      Could not load saved reports: ${escapeHtml(error.message)}
    </div>`;
}

function renderPipeline(result) {
  const findings = result.findings || [];
  const provider = result.provider_metadata || {};
  const warnings = result.evidence?.warnings || [];
  const visibleWarnings = warnings.slice(0, 8);
  findingCount.textContent = findings.length
    ? `${findings.length} finding${findings.length === 1 ? "" : "s"}`
    : "No findings";

  const findingItems = findings.length
    ? findings
        .map(
          (finding) => `
            <li class="finding severity-${escapeHtml(finding.severity)}">
              <strong>${escapeHtml(finding.severity)} / ${escapeHtml(finding.check)}</strong>
              <span>${escapeHtml(finding.message)}</span>
            </li>`,
        )
        .join("")
    : `<li class="finding severity-ok"><strong>pass</strong><span>No validation findings.</span></li>`;

  const warningItems = visibleWarnings
    .map(
      (warning) => `
        <li class="finding severity-warning">
          <strong>evidence warning</strong>
          <span>${escapeHtml(warning)}</span>
        </li>`,
    )
    .join("");
  const hiddenWarningCount = warnings.length - visibleWarnings.length;
  const hiddenWarningItem =
    hiddenWarningCount > 0
      ? `
        <li class="finding severity-info">
          <strong>evidence warning</strong>
          <span>${escapeHtml(hiddenWarningCount)} more warnings hidden.</span>
        </li>`
      : "";
  const providerLabel =
    provider.provider || provider.model || provider.latency_ms != null
      ? `${provider.provider || "n/a"} · ${provider.model || "n/a"} · ${provider.latency_ms ?? "n/a"}ms`
      : "n/a";

  pipelineReport.className = "";
  pipelineReport.innerHTML = `
    <div class="report-body">
      <div class="metric-row">
        <strong>Status</strong>
        <span>${escapeHtml(result.status)}</span>
      </div>
      <div class="metric-row">
        <strong>Provider</strong>
        <span>${escapeHtml(providerLabel)}</span>
      </div>
      <div class="metric-row">
        <strong>Evidence</strong>
        <span>${escapeHtml(result.evidence?.commits?.length || 0)} commits · ${escapeHtml(result.evidence?.documentation?.length || 0)} docs</span>
      </div>
      <ul class="finding-list">${findingItems}${warningItems}${hiddenWarningItem}</ul>
    </div>`;
}

function renderChangeReport(result) {
  const update = result.update;
  const artifacts = result.artifacts || {};
  activeRenderedReportId = result.run_id;
  renderArtifactActions(result);

  if (!update) {
    changeReport.className = "empty-state";
    changeReport.textContent = "No documentation update was generated.";
    return;
  }

  const evidenceItems = (update.evidence_used || [])
    .map(
      (ref) => `
        <li class="evidence-item">
          <strong>${escapeHtml(ref.source)}</strong>
          <span>${escapeHtml(ref.detail)}</span>
          <small>${escapeHtml(ref.relevance)}</small>
        </li>`,
    )
    .join("");

  changeReport.className = "";
  changeReport.innerHTML = `
    <div class="report-body">
      <div>
        <h3>${escapeHtml(update.title)}</h3>
        <p>${escapeHtml(update.summary)}</p>
      </div>
      <div class="metric-row">
        <strong>User-facing change</strong>
        <span>${escapeHtml(update.user_facing_change)}</span>
      </div>
      <div>
        <h3>Proposed documentation update</h3>
        <div class="markdown rendered-markdown">${renderMarkdown(update.proposed_update_markdown)}</div>
      </div>
      <div>
        <h3>Evidence used</h3>
        <ul class="evidence-list">${evidenceItems || "<li class=\"evidence-item\">No evidence references.</li>"}</ul>
      </div>
    </div>`;

  if (artifacts["report.md"]) {
    loadRenderedMarkdownReport(result.run_id).catch((error) => {
      if (activeRenderedReportId !== result.run_id) {
        return;
      }
      const reportContainer = changeReport.querySelector("[data-report-markdown]");
      if (reportContainer) {
        reportContainer.innerHTML = `
          <div class="empty-state">Could not load markdown artifact: ${escapeHtml(error.message)}</div>`;
      }
    });
  }
}

function renderArtifactActions(result) {
  const artifacts = result.artifacts || {};
  const actions = [];
  if (artifacts["report.html"]) {
    actions.push(`
      <a class="artifact-action" href="${artifactUrl(result.run_id, "report.html")}" target="_blank" rel="noreferrer">
        Open report
      </a>`);
    actions.push(`
      <a class="artifact-action" href="${artifactUrl(result.run_id, "report.html", { print: "1" })}" target="_blank" rel="noreferrer">
        Print / save PDF
      </a>`);
  }
  if (artifacts["report.md"]) {
    actions.push(`
      <a class="artifact-action" href="${artifactUrl(result.run_id, "report.md")}" target="_blank" rel="noreferrer">
        Markdown
      </a>`);
  }
  artifactLink.className = actions.length ? "artifact-actions" : "muted";
  artifactLink.innerHTML = actions.join("");
}

async function loadRenderedMarkdownReport(runId) {
  const markdown = await requestText(artifactUrl(runId, "report.md"));
  if (activeRenderedReportId !== runId) {
    return;
  }
  const update = (await requestJson(`/runs/${encodeURIComponent(runId)}`)).update;
  if (activeRenderedReportId !== runId) {
    return;
  }
  changeReport.className = "";
  changeReport.innerHTML = `
    <div class="report-body">
      ${update ? `
        <div>
          <h3>${escapeHtml(update.title)}</h3>
          <p>${escapeHtml(update.summary)}</p>
        </div>` : ""}
      <div data-report-markdown class="markdown rendered-markdown">${renderMarkdown(markdown)}</div>
    </div>`;
}

function terminalStatus(status) {
  return status === "completed" || status === "failed";
}

function stopRunPolling() {
  if (activeRunPollTimer) {
    clearTimeout(activeRunPollTimer);
    activeRunPollTimer = null;
  }
}

async function pollRun(runId) {
  const result = await requestJson(`/runs/${runId}`);
  renderPipeline(result);
  renderChangeReport(result);
  await loadReports();
  statusPill.textContent = result.status;
  if (!terminalStatus(result.status)) {
    activeRunPollTimer = setTimeout(() => {
      pollRun(runId).catch((error) => {
        statusPill.textContent = "Poll error";
        pipelineReport.className = "";
        pipelineReport.innerHTML = `
          <ul class="finding-list">
            <li class="finding severity-error">
              <strong>ui / poll</strong>
              <span>${escapeHtml(error.message)}</span>
            </li>
          </ul>`;
      });
    }, 3000);
  }
}

function startRunPolling(runId) {
  stopRunPolling();
  pollRun(runId).catch((error) => {
    statusPill.textContent = "Poll error";
    pipelineReport.className = "";
    pipelineReport.innerHTML = `
      <ul class="finding-list">
        <li class="finding severity-error">
          <strong>ui / poll</strong>
          <span>${escapeHtml(error.message)}</span>
        </li>
      </ul>`;
  });
}

projectList.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-project-id]");
  if (!button) {
    return;
  }
  const project = await requestJson(`/projects/${button.dataset.projectId}`);
  setProject(project);
});

projectOverview.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-project-id]");
  if (!button) {
    return;
  }
  const project = await requestJson(`/projects/${button.dataset.projectId}`);
  setProject(project);
  navigate(button.dataset.openPage || "settings");
});

document.addEventListener("click", (event) => {
  const button = event.target.closest("[data-page-target]");
  if (!button) {
    return;
  }
  navigate(button.dataset.pageTarget);
  if (button.dataset.pageTarget === "reports") {
    loadReports().catch(renderReportLoadError);
  }
});

newProjectButton.addEventListener("click", () => {
  setProject(blankProject());
  navigate("settings");
});

addRepositoryButton.addEventListener("click", () => {
  const draft = projectPayload();
  draft.repositories.push({
    id: uid("repo"),
    name: `repository-${draft.repositories.length + 1}`,
    url: "",
    default_branch: "main",
    paths: [],
  });
  setProject({ ...currentProject, ...draft }, "Draft");
});

repositoryEditorList.addEventListener("click", (event) => {
  const button = event.target.closest("[data-action='remove-repo']");
  if (!button) {
    return;
  }
  const cards = [...repositoryEditorList.querySelectorAll(".repo-card")];
  if (cards.length <= 1) {
    projectStatus.textContent = "Keep at least one repository";
    return;
  }
  button.closest(".repo-card").remove();
  renderRunRepositories();
});

repositoryEditorList.addEventListener("input", () => {
  renderRunRepositories();
    projectStatus.textContent = currentProject?.id ? "Unsaved" : "Draft";
});

projectForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  projectStatus.textContent = "Saving";
  const payload = projectPayload();
  const url = currentProject?.id ? `/projects/${currentProject.id}` : "/projects";
  const method = currentProject?.id ? "PUT" : "POST";
  const project = await requestJson(url, {
    method,
    body: JSON.stringify(payload),
  });
  await loadProjects(project.id);
  navigate("run");
});

document.querySelectorAll("input[name='run-mode']").forEach((input) => {
  input.addEventListener("change", renderRunRepositories);
});

runRepositoryList.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-action='load-branches']");
  if (!button) {
    return;
  }
  const repoId = button.dataset.repoId;
  const repository = projectPayload().repositories.find((item) => item.id === repoId);
  if (!repository) {
    return;
  }
  button.disabled = true;
  button.textContent = "Loading";
  branchWarnings[repoId] = "";
  try {
    const result = await requestJson(`/github/branches?url=${encodeURIComponent(repository.url)}`);
    branchCache[repoId] = result.branches || [];
    branchWarnings[repoId] = result.warning || "";
  } catch (error) {
    branchCache[repoId] = [];
    branchWarnings[repoId] = `Could not load branches: ${error.message}`;
  } finally {
    renderRunRepositories();
  }
});

runRepositoryList.addEventListener("change", (event) => {
  const select = event.target.closest("[data-action='sort-branches']");
  if (!select) {
    return;
  }
  branchSortByRepo[select.dataset.repoId] = select.value;
  renderRunRepositories();
});

reportHistory.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-run-id]");
  if (!button) {
    return;
  }
  stopRunPolling();
  const result = await requestJson(`/runs/${button.dataset.runId}`);
  renderPipeline(result);
  renderChangeReport(result);
  if (!terminalStatus(result.status)) {
    startRunPolling(result.run_id);
  }
});

refreshReportsButton.addEventListener("click", () => {
  loadReports().catch(renderReportLoadError);
});

runForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!currentProject?.id) {
    projectStatus.textContent = "Save project first";
    return;
  }

  const mode = activeRunMode();
  const branches = mode === "select_branches" ? selectedBranchesByRepo() : {};
  if (mode === "select_branches") {
    const missingRepositories = projectPayload().repositories.filter((repository) => {
      return !branches[repository.id]?.length;
    });
    if (missingRepositories.length) {
      statusPill.textContent = "Select branches";
      return;
    }
  }

  statusPill.textContent = "Creating";
  runForm.querySelector("button[type='submit']").disabled = true;

  try {
    const payload = {
      mode,
      goal: document.querySelector("#goal").value,
      since: mode === "default_branch_period" ? document.querySelector("#since").value || null : null,
      until: mode === "default_branch_period" ? document.querySelector("#until").value || null : null,
      branches,
    };

    const summary = await requestJson(`/projects/${currentProject.id}/runs`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
    statusPill.textContent = summary.status;
    await loadReports();
    navigate("reports");
    startRunPolling(summary.run_id);
  } catch (error) {
    statusPill.textContent = "Error";
    pipelineReport.className = "";
    pipelineReport.innerHTML = `
      <ul class="finding-list">
        <li class="finding severity-error">
          <strong>ui / request</strong>
          <span>${escapeHtml(error.message)}</span>
        </li>
      </ul>`;
  } finally {
    runForm.querySelector("button[type='submit']").disabled = false;
  }
});

modelSettingsForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  modelSettingsStatus.textContent = "Saving";
  const saved = await requestJson("/settings/model", {
    method: "PUT",
    body: JSON.stringify(modelSettingsPayload()),
  });
  applyModelSettings(saved);
});

document.querySelector("#since").value = isoDate(14);
requestJson("/settings/model")
  .then(applyModelSettings)
  .catch(() => {
    modelSettingsStatus.textContent = "Load failed";
  })
  .finally(() => {
    loadProjects().catch((error) => {
      projectStatus.textContent = "Load failed";
      pipelineReport.className = "";
      pipelineReport.innerHTML = `
        <ul class="finding-list">
          <li class="finding severity-error">
            <strong>project / load</strong>
            <span>${escapeHtml(error.message)}</span>
          </li>
        </ul>`;
    });
  });

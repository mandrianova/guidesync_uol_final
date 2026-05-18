const state = {
  mode: "release",
  taskPath: "",
};

const tabs = [...document.querySelectorAll(".tab")];
const releaseForm = document.querySelector("#releaseForm");
const initForm = document.querySelector("#initForm");
const jsonPreview = document.querySelector("#jsonPreview");
const taskPathLabel = document.querySelector("#taskPath");
const runStatus = document.querySelector("#runStatus");
const runOutput = document.querySelector("#runOutput");
const artifactList = document.querySelector("#artifactList");
const screenTitle = document.querySelector("#screenTitle");
const modeLabel = document.querySelector("#modeLabel");
const projectList = document.querySelector("#projectList");

function formData(form) {
  const data = {};
  for (const element of form.elements) {
    if (!element.name) continue;
    if (element.type === "checkbox") {
      data[element.name] = element.checked;
    } else {
      data[element.name] = element.value;
    }
  }
  return data;
}

function activeForm() {
  return state.mode === "release" ? releaseForm : initForm;
}

function setStatus(label, kind = "idle") {
  runStatus.textContent = label;
  runStatus.className = `status ${kind}`;
}

async function api(path, payload) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
  });
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || response.statusText);
  return body;
}

function pretty(payload) {
  return JSON.stringify(payload, null, 2);
}

function renderPreview(payload) {
  jsonPreview.textContent = pretty(payload.task || payload);
  state.taskPath = payload.task_path || state.taskPath;
  taskPathLabel.textContent = state.taskPath;
}

function artifactType(file) {
  const suffix = file.name.split(".").pop().toLowerCase();
  if (suffix === "html") return "html";
  if (suffix === "md") return "report";
  if (suffix === "json") return "json";
  return "image";
}

function renderArtifacts(files = []) {
  artifactList.replaceChildren(
    ...files.slice().reverse().map((file) => {
      const link = document.createElement("a");
      link.className = "artifact";
      link.href = `/api/artifact?path=${encodeURIComponent(file.path)}`;
      link.target = "_blank";
      link.rel = "noreferrer";

      const name = document.createElement("span");
      name.textContent = file.path;
      const type = document.createElement("strong");
      type.textContent = artifactType(file);
      link.append(name, type);
      return link;
    }),
  );
}

async function saveTask() {
  const path = state.mode === "release" ? "/api/tasks/release" : "/api/tasks/init";
  const result = await api(path, formData(activeForm()));
  renderPreview(result);
  await loadProjects();
  return result;
}

async function runTask() {
  try {
    artifactList.replaceChildren();
    runOutput.textContent = "";
    setStatus("Saving", "running");
    const saved = await saveTask();
    setStatus("Running", "running");
    const result = await api("/api/run", { task_path: saved.task_path });
    runOutput.textContent = [result.stdout, result.stderr].filter(Boolean).join("\n\n");
    renderArtifacts(result.artifacts);
    setStatus(result.returncode === 0 ? "Done" : `Exit ${result.returncode}`, result.returncode === 0 ? "ok" : "bad");
    await loadProjects();
  } catch (error) {
    setStatus("Failed", "bad");
    runOutput.textContent = error.message;
  }
}

function switchMode(mode) {
  state.mode = mode;
  tabs.forEach((tab) => tab.classList.toggle("active", tab.dataset.tab === mode));
  releaseForm.classList.toggle("active", mode === "release");
  initForm.classList.toggle("active", mode === "init");
  modeLabel.textContent = mode === "release" ? "Release task" : "Project init";
  screenTitle.textContent = mode === "release" ? "Create release notes task" : "Initialize project task";
  state.taskPath = "";
  taskPathLabel.textContent = "";
  jsonPreview.textContent = "{}";
}

function applyProject(project) {
  for (const form of [releaseForm, initForm]) {
    form.elements.project_id.value = project.id || "";
    form.elements.project_name.value = project.name || "";
    if (form.elements.project_root) form.elements.project_root.value = project.root || "";
    if (form.elements.languages) form.elements.languages.value = (project.languages || []).join(", ") || "en";
  }
}

async function loadProjects() {
  const response = await fetch("/api/projects");
  const data = await response.json();
  projectList.replaceChildren(
    ...data.projects.map((project) => {
      const button = document.createElement("button");
      button.className = "project-card";
      button.type = "button";
      button.innerHTML = `<b></b><small></small><small></small>`;
      button.querySelector("b").textContent = project.name;
      button.querySelectorAll("small")[0].textContent = project.id;
      button.querySelectorAll("small")[1].textContent = project.root || "No root configured";
      button.addEventListener("click", () => applyProject(project));
      return button;
    }),
  );
}

tabs.forEach((tab) => tab.addEventListener("click", () => switchMode(tab.dataset.tab)));
document.querySelector("#saveTask").addEventListener("click", async () => {
  try {
    setStatus("Saved", "ok");
    renderPreview(await saveTask());
  } catch (error) {
    setStatus("Failed", "bad");
    runOutput.textContent = error.message;
  }
});
document.querySelector("#runTask").addEventListener("click", runTask);
document.querySelector("#refreshProjects").addEventListener("click", loadProjects);

loadProjects();

import { LoadingOverlay, Stack } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api } from "./api/client";
import { WorkspaceShell } from "./components/WorkspaceShell";
import { ModelSettingsPage } from "./features/models/ModelSettingsPage";
import { ProjectOverview } from "./features/projects/ProjectOverview";
import { ProjectSettings } from "./features/projects/ProjectSettings";
import { ReportsPage } from "./features/reports/ReportsPage";
import { RunAnalysisPage } from "./features/runs/RunAnalysisPage";
import { terminalStatus } from "./lib/branches";
import { draftModelSettings } from "./lib/modelProfiles";
import { blankProject, cloneProject, projectPayload } from "./lib/projects";
import type {
  GuideSyncRunResult,
  KnowledgeIndexRun,
  ModelSettings,
  PageId,
  ProjectConfig,
  RunSummary
} from "./types";

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Unknown error";
}

export function App() {
  const [currentPage, setCurrentPage] = useState<PageId>("settings");
  const [projects, setProjects] = useState<ProjectConfig[]>([]);
  const [projectDraft, setProjectDraft] = useState<ProjectConfig>(() => blankProject());
  const [projectStatus, setProjectStatus] = useState("Draft");
  const [savingProject, setSavingProject] = useState(false);

  const [modelProfiles, setModelProfiles] = useState<ModelSettings[]>([]);
  const [selectedModelProfile, setSelectedModelProfile] = useState<ModelSettings>(() =>
    draftModelSettings()
  );

  const [reports, setReports] = useState<RunSummary[]>([]);
  const [reportsLoading, setReportsLoading] = useState(false);
  const [selectedRun, setSelectedRun] = useState<GuideSyncRunResult | null>(null);
  const [runStatus, setRunStatus] = useState("Ready");
  const [knowledgeRuns, setKnowledgeRuns] = useState<KnowledgeIndexRun[]>([]);
  const [initialLoading, setInitialLoading] = useState(true);

  const pollTimer = useRef<number | null>(null);

  const defaultModel = useMemo(
    () =>
      modelProfiles.find((profile) => profile.is_default) ||
      (selectedModelProfile.is_default ? selectedModelProfile : null),
    [modelProfiles, selectedModelProfile]
  );

  const stopRunPolling = useCallback(() => {
    if (pollTimer.current) {
      window.clearTimeout(pollTimer.current);
      pollTimer.current = null;
    }
  }, []);

  const refreshReports = useCallback(
    async (projectId = projectDraft.id) => {
      if (!projectId) {
        setReports([]);
        return;
      }
      setReportsLoading(true);
      try {
        setReports(await api.listProjectRuns(projectId));
      } catch (error) {
        notifications.show({
          color: "red",
          message: errorMessage(error),
          title: "Could not load reports"
        });
      } finally {
        setReportsLoading(false);
      }
    },
    [projectDraft.id]
  );

  const refreshKnowledgeRuns = useCallback(
    async (projectId = projectDraft.id) => {
      if (!projectId) {
        setKnowledgeRuns([]);
        return;
      }
      try {
        setKnowledgeRuns(await api.listKnowledgeRuns(projectId));
      } catch (error) {
        notifications.show({
          color: "red",
          message: errorMessage(error),
          title: "Could not load knowledge index runs"
        });
      }
    },
    [projectDraft.id]
  );

  const applyProject = useCallback(
    (project: ProjectConfig, status = "Saved") => {
      stopRunPolling();
      const draft = cloneProject(project);
      setProjectDraft(draft);
      setProjectStatus(status);
      setSelectedRun(null);
      setRunStatus("Ready");
      void refreshReports(draft.id);
      void refreshKnowledgeRuns(draft.id);
    },
    [refreshKnowledgeRuns, refreshReports, stopRunPolling]
  );

  const reloadProjects = useCallback(
    async (selectedId: string | null = projectDraft.id) => {
      const loadedProjects = await api.listProjects();
      setProjects(loadedProjects);
      const selected =
        loadedProjects.find((project) => project.id === selectedId) ||
        loadedProjects.find((project) => project.id === projectDraft.id) ||
        loadedProjects[0];
      applyProject(selected || blankProject(), selected ? "Saved" : "Draft");
    },
    [applyProject, projectDraft.id]
  );

  const reloadModelProfiles = useCallback(
    async (selectedId?: string) => {
      const profiles = await api.listModelProfiles();
      setModelProfiles(profiles);
      const selected =
        profiles.find((profile) => profile.id === selectedId) ||
        profiles.find((profile) => profile.id === selectedModelProfile.id) ||
        profiles.find((profile) => profile.is_default) ||
        profiles[0] ||
        draftModelSettings();
      setSelectedModelProfile(selected);
    },
    [selectedModelProfile.id]
  );

  useEffect(() => {
    let ignore = false;

    Promise.allSettled([api.listProjects(), api.listModelProfiles()])
      .then(([projectResult, modelResult]) => {
        if (ignore) {
          return;
        }
        if (projectResult.status === "fulfilled") {
          setProjects(projectResult.value);
          applyProject(projectResult.value[0] || blankProject(), projectResult.value[0] ? "Saved" : "Draft");
        } else {
          setProjectStatus("Load failed");
          notifications.show({
            color: "red",
            message: errorMessage(projectResult.reason),
            title: "Could not load projects"
          });
        }

        if (modelResult.status === "fulfilled") {
          const profiles = modelResult.value;
          setModelProfiles(profiles);
          setSelectedModelProfile(
            profiles.find((profile) => profile.is_default) || profiles[0] || draftModelSettings()
          );
        } else {
          notifications.show({
            color: "red",
            message: errorMessage(modelResult.reason),
            title: "Could not load model profiles"
          });
        }
      })
      .finally(() => {
        if (!ignore) {
          setInitialLoading(false);
        }
      });

    return () => {
      ignore = true;
    };
  }, [applyProject]);

  useEffect(() => stopRunPolling, [stopRunPolling]);

  const startRunPolling = useCallback(
    async (runId: string) => {
      stopRunPolling();

      const poll = async () => {
        try {
          const result = await api.getRun(runId);
          setSelectedRun(result);
          setRunStatus(result.status);
          await refreshReports(projectDraft.id);

          if (!terminalStatus(result.status)) {
            pollTimer.current = window.setTimeout(() => {
              void poll();
            }, 3000);
          }
        } catch (error) {
          setRunStatus("Poll error");
          notifications.show({
            color: "red",
            message: errorMessage(error),
            title: "Run polling failed"
          });
        }
      };

      await poll();
    },
    [projectDraft.id, refreshReports, stopRunPolling]
  );

  const selectProject = async (projectId: string, page?: PageId) => {
    try {
      const project = await api.getProject(projectId);
      applyProject(project);
      if (page) {
        setCurrentPage(page);
      }
    } catch (error) {
      notifications.show({
        color: "red",
        message: errorMessage(error),
        title: "Could not load project"
      });
    }
  };

  const saveProject = async () => {
    setSavingProject(true);
    setProjectStatus("Saving");
    try {
      const payload = projectPayload(projectDraft);
      const saved = projectDraft.id
        ? await api.updateProject(projectDraft.id, payload)
        : await api.createProject(payload);
      await reloadProjects(saved.id);
      setCurrentPage("run");
    } catch (error) {
      setProjectStatus("Error");
      notifications.show({
        color: "red",
        message: errorMessage(error),
        title: "Project save failed"
      });
    } finally {
      setSavingProject(false);
    }
  };

  const newProject = () => {
    applyProject(blankProject(), "Draft");
    setCurrentPage("settings");
  };

  const openRun = async (summary: RunSummary) => {
    await refreshReports(projectDraft.id);
    setCurrentPage("reports");
    await startRunPolling(summary.run_id);
  };

  const selectRun = async (runId: string) => {
    stopRunPolling();
    try {
      const result = await api.getRun(runId);
      setSelectedRun(result);
      setRunStatus(result.status);
      if (!terminalStatus(result.status)) {
        await startRunPolling(result.run_id);
      }
    } catch (error) {
      notifications.show({
        color: "red",
        message: errorMessage(error),
        title: "Could not load run"
      });
    }
  };

  const pageTitleProjectName = projectDraft.id ? projectDraft.name : "";

  return (
    <WorkspaceShell
      currentPage={currentPage}
      currentProject={projectDraft}
      defaultModel={defaultModel}
      onNavigate={(page) => {
        if (page === "reports") {
          void refreshReports(projectDraft.id);
        }
        if (page === "run") {
          void refreshKnowledgeRuns(projectDraft.id);
        }
        setCurrentPage(page);
      }}
      onNewProject={newProject}
      onSelectProject={(projectId) => void selectProject(projectId)}
      projects={projects}
    >
      <LoadingOverlay visible={initialLoading} />
      <Stack className="content-stack">
        {currentPage === "projects" ? (
          <ProjectOverview
            currentProjectId={projectDraft.id}
            onNavigate={setCurrentPage}
            onOpenProject={(projectId, page) => void selectProject(projectId, page)}
            projects={projects}
          />
        ) : null}

        {currentPage === "settings" ? (
          <ProjectSettings
            onChange={(project, status) => {
              setProjectDraft(project);
              if (status) {
                setProjectStatus(status);
              }
            }}
            onSave={() => void saveProject()}
            project={projectDraft}
            projectStatus={projectStatus}
            saving={savingProject}
          />
        ) : null}

        {currentPage === "run" ? (
          <RunAnalysisPage
            knowledgeRuns={knowledgeRuns}
            onKnowledgeRefresh={() => refreshKnowledgeRuns(projectDraft.id)}
            onRunCreated={openRun}
            onStatusChange={setRunStatus}
            project={projectDraft}
            runStatus={runStatus}
          />
        ) : null}

        {currentPage === "reports" ? (
          <ReportsPage
            loading={reportsLoading}
            onBackToList={() => {
              stopRunPolling();
              setSelectedRun(null);
            }}
            onRefresh={() => void refreshReports(projectDraft.id)}
            onSelectRun={(runId) => void selectRun(runId)}
            projectName={pageTitleProjectName}
            reports={reports}
            selectedRun={selectedRun}
          />
        ) : null}

        {currentPage === "app-settings" ? (
          <ModelSettingsPage
            onProfilesReload={reloadModelProfiles}
            onSelectedProfileChange={setSelectedModelProfile}
            profiles={modelProfiles}
            selectedProfile={selectedModelProfile}
          />
        ) : null}
      </Stack>
    </WorkspaceShell>
  );
}

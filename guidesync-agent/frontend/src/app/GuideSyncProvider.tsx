import { notifications } from "@mantine/notifications";
import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState
} from "react";

import { api } from "../api/client";
import { terminalStatus } from "../lib/branches";
import { draftModelSettings } from "../lib/modelProfiles";
import {
  blankProject,
  cloneProject,
  projectPayload,
  resolveProjectSelection
} from "../lib/projects";
import type {
  GuideSyncRunResult,
  KnowledgeIndexRun,
  ModelSettings,
  ProjectConfig,
  RunSummary
} from "../types";

const selectedProjectStorageKey = "guidesync:selected-project-id";

interface GuideSyncContextValue {
  defaultModel: ModelSettings | null;
  initialLoading: boolean;
  knowledgeRuns: KnowledgeIndexRun[];
  modelProfiles: ModelSettings[];
  projectDraft: ProjectConfig;
  projectStatus: string;
  projects: ProjectConfig[];
  reports: RunSummary[];
  reportsLoading: boolean;
  runStatus: string;
  savingProject: boolean;
  selectedModelProfile: ModelSettings;
  selectedRun: GuideSyncRunResult | null;
  clearSelectedRun: () => void;
  loadProject: (projectId: string) => Promise<void>;
  newProject: () => void;
  openRun: (summary: RunSummary) => Promise<void>;
  refreshKnowledgeRuns: (projectId: string | null) => Promise<void>;
  refreshReports: (projectId: string | null) => Promise<void>;
  reloadModelProfiles: (selectedId?: string) => Promise<void>;
  saveProject: () => Promise<ProjectConfig | null>;
  selectRun: (runId: string) => Promise<void>;
  setProjectDraft: (project: ProjectConfig, status?: string) => void;
  setRunStatus: (status: string) => void;
  setSelectedModelProfile: (profile: ModelSettings) => void;
}

const GuideSyncContext = createContext<GuideSyncContextValue | null>(null);

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Unknown error";
}

export function GuideSyncProvider({ children }: { children: ReactNode }) {
  const [projects, setProjects] = useState<ProjectConfig[]>([]);
  const [projectDraft, updateProjectDraft] = useState<ProjectConfig>(() => blankProject());
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
  const reportsProjectId = useRef<string | null>(null);

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

  const refreshReports = useCallback(async (projectId: string | null) => {
    reportsProjectId.current = projectId;
    if (!projectId) {
      setReports([]);
      return;
    }
    setReportsLoading(true);
    try {
      const loadedReports = await api.listProjectRuns(projectId);
      if (reportsProjectId.current === projectId) {
        setReports(loadedReports);
      }
    } catch (error) {
      if (reportsProjectId.current === projectId) {
        setReports([]);
        notifications.show({
          color: "red",
          message: errorMessage(error),
          title: "Could not load reports"
        });
      }
    } finally {
      if (reportsProjectId.current === projectId) {
        setReportsLoading(false);
      }
    }
  }, []);

  const refreshKnowledgeRuns = useCallback(async (projectId: string | null) => {
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
  }, []);

  const applyProject = useCallback(
    (project: ProjectConfig, status = "Saved") => {
      stopRunPolling();
      const draft = cloneProject(project);
      if (draft.id) {
        rememberSelectedProject(draft.id);
      }
      updateProjectDraft(draft);
      setProjectStatus(status);
      setSelectedRun(null);
      setRunStatus("Ready");
      void refreshReports(draft.id);
      void refreshKnowledgeRuns(draft.id);
    },
    [refreshKnowledgeRuns, refreshReports, stopRunPolling]
  );

  const reloadProjects = useCallback(
    async (selectedId: string | null = null) => {
      const loadedProjects = await api.listProjects();
      setProjects(loadedProjects);
      const selected = resolveProjectSelection(loadedProjects, selectedId);
      if (!selected) {
        forgetSelectedProject();
      }
      applyProject(selected || blankProject(), selected ? "Saved" : "Draft");
    },
    [applyProject]
  );

  const reloadModelProfiles = useCallback(async (selectedId?: string) => {
    const profiles = await api.listModelProfiles();
    setModelProfiles(profiles);
    const selected =
      profiles.find((profile) => profile.id === selectedId) ||
      profiles.find((profile) => profile.is_default) ||
      profiles[0] ||
      draftModelSettings();
    setSelectedModelProfile(selected);
  }, []);

  useEffect(() => {
    let ignore = false;

    Promise.allSettled([api.listProjects(), api.listModelProfiles()])
      .then(([projectResult, modelResult]) => {
        if (ignore) {
          return;
        }
        if (projectResult.status === "fulfilled") {
          const loadedProjects = projectResult.value;
          const selectedProject = resolveProjectSelection(
            loadedProjects,
            rememberedProjectId()
          );
          if (!selectedProject) {
            forgetSelectedProject();
          }
          setProjects(loadedProjects);
          applyProject(selectedProject || blankProject(), selectedProject ? "Saved" : "Draft");
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
    async (runId: string, projectId: string | null) => {
      stopRunPolling();

      const poll = async () => {
        try {
          const result = await api.getRun(runId);
          setSelectedRun(result);
          setRunStatus(result.status);
          await refreshReports(projectId);

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
    [refreshReports, stopRunPolling]
  );

  const loadProject = useCallback(
    async (projectId: string) => {
      try {
        const project = await api.getProject(projectId);
        applyProject(project);
      } catch (error) {
        notifications.show({
          color: "red",
          message: errorMessage(error),
          title: "Could not load project"
        });
      }
    },
    [applyProject]
  );

  const saveProject = useCallback(async () => {
    setSavingProject(true);
    setProjectStatus("Saving");
    try {
      const payload = projectPayload(projectDraft);
      const saved = projectDraft.id
        ? await api.updateProject(projectDraft.id, payload)
        : await api.createProject(payload);
      await reloadProjects(saved.id);
      return saved;
    } catch (error) {
      setProjectStatus("Error");
      notifications.show({
        color: "red",
        message: errorMessage(error),
        title: "Project save failed"
      });
      return null;
    } finally {
      setSavingProject(false);
    }
  }, [projectDraft, reloadProjects]);

  const newProject = useCallback(() => {
    applyProject(blankProject(), "Draft");
  }, [applyProject]);

  const openRun = useCallback(
    async (summary: RunSummary) => {
      await refreshReports(projectDraft.id);
      await startRunPolling(summary.run_id, projectDraft.id);
    },
    [projectDraft.id, refreshReports, startRunPolling]
  );

  const selectRun = useCallback(
    async (runId: string) => {
      stopRunPolling();
      try {
        const result = await api.getRun(runId);
        setSelectedRun(result);
        setRunStatus(result.status);
        if (!terminalStatus(result.status)) {
          await startRunPolling(result.run_id, projectDraft.id);
        }
      } catch (error) {
        notifications.show({
          color: "red",
          message: errorMessage(error),
          title: "Could not load run"
        });
      }
    },
    [projectDraft.id, startRunPolling, stopRunPolling]
  );

  const clearSelectedRun = useCallback(() => {
    stopRunPolling();
    setSelectedRun(null);
  }, [stopRunPolling]);

  const setProjectDraft = useCallback((project: ProjectConfig, status?: string) => {
    updateProjectDraft(project);
    if (status) {
      setProjectStatus(status);
    }
  }, []);

  const value = useMemo(
    () => ({
      clearSelectedRun,
      defaultModel,
      initialLoading,
      knowledgeRuns,
      loadProject,
      modelProfiles,
      newProject,
      openRun,
      projectDraft,
      projectStatus,
      projects,
      refreshKnowledgeRuns,
      refreshReports,
      reloadModelProfiles,
      reports,
      reportsLoading,
      runStatus,
      saveProject,
      savingProject,
      selectRun,
      selectedModelProfile,
      selectedRun,
      setProjectDraft,
      setRunStatus,
      setSelectedModelProfile
    }),
    [
      clearSelectedRun,
      defaultModel,
      initialLoading,
      knowledgeRuns,
      loadProject,
      modelProfiles,
      newProject,
      openRun,
      projectDraft,
      projectStatus,
      projects,
      refreshKnowledgeRuns,
      refreshReports,
      reloadModelProfiles,
      reports,
      reportsLoading,
      runStatus,
      saveProject,
      savingProject,
      selectRun,
      selectedModelProfile,
      selectedRun,
      setProjectDraft
    ]
  );

  return <GuideSyncContext.Provider value={value}>{children}</GuideSyncContext.Provider>;
}

function rememberedProjectId(): string | null {
  try {
    return window.localStorage.getItem(selectedProjectStorageKey);
  } catch {
    return null;
  }
}

function rememberSelectedProject(projectId: string): void {
  try {
    window.localStorage.setItem(selectedProjectStorageKey, projectId);
  } catch {
    // The current in-memory selection still works when browser storage is unavailable.
  }
}

function forgetSelectedProject(): void {
  try {
    window.localStorage.removeItem(selectedProjectStorageKey);
  } catch {
    // Empty project state still works when browser storage is unavailable.
  }
}

export function useGuideSync() {
  const context = useContext(GuideSyncContext);
  if (!context) {
    throw new Error("useGuideSync must be used inside GuideSyncProvider");
  }
  return context;
}

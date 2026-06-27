import { LoadingOverlay, Stack } from "@mantine/core";
import { Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";

import { WorkspaceShell } from "../components/WorkspaceShell";
import { KnowledgeRoutePage } from "../pages/KnowledgeRoutePage";
import { ModelSettingsRoutePage } from "../pages/ModelSettingsRoutePage";
import { ProjectOverviewRoutePage } from "../pages/ProjectOverviewRoutePage";
import { ProjectProfileRoutePage } from "../pages/ProjectProfileRoutePage";
import { ProjectSettingsRoutePage } from "../pages/ProjectSettingsRoutePage";
import { ReportsRoutePage } from "../pages/ReportsRoutePage";
import { RunAnalysisRoutePage } from "../pages/RunAnalysisRoutePage";
import { useGuideSync } from "./GuideSyncProvider";
import { pageForPath, pathForPage } from "./routePaths";
import { usePageNavigation } from "./usePageNavigation";

export function GuideSyncRoutes() {
  const navigate = useNavigate();
  const location = useLocation();
  const navigateToPage = usePageNavigation();
  const { defaultModel, initialLoading, loadProject, newProject, projectDraft, projects } =
    useGuideSync();

  const currentPage = pageForPath(location.pathname);

  return (
    <WorkspaceShell
      currentPage={currentPage}
      currentProject={projectDraft}
      defaultModel={defaultModel}
      onNavigate={navigateToPage}
      onNewProject={() => {
        newProject();
        navigate(pathForPage("settings"));
      }}
      onSelectProject={(projectId) => void loadProject(projectId)}
      projects={projects}
    >
      <LoadingOverlay visible={initialLoading} />
      <Stack className="content-stack">
        <Routes>
          <Route element={<Navigate replace to={pathForPage("settings")} />} path="/" />
          <Route element={<ProjectSettingsRoutePage />} path="/project" />
          <Route element={<ProjectProfileRoutePage />} path="/profile" />
          <Route element={<KnowledgeRoutePage />} path="/knowledge" />
          <Route element={<RunAnalysisRoutePage />} path="/run" />
          <Route element={<ReportsRoutePage />} path="/reports" />
          <Route element={<ModelSettingsRoutePage />} path="/models" />
          <Route element={<ProjectOverviewRoutePage />} path="/projects" />
          <Route element={<Navigate replace to={pathForPage("settings")} />} path="*" />
        </Routes>
      </Stack>
    </WorkspaceShell>
  );
}

import { useNavigate } from "react-router-dom";

import { useGuideSync } from "../app/GuideSyncProvider";
import { pathForPage } from "../app/routePaths";
import { usePageNavigation } from "../app/usePageNavigation";
import { ProjectOverview } from "../features/projects/ProjectOverview";
import type { PageId } from "../types";

export function ProjectOverviewRoutePage() {
  const navigate = useNavigate();
  const navigateToPage = usePageNavigation();
  const { loadProject, projectDraft, projects } = useGuideSync();

  const openProject = async (projectId: string, page: PageId) => {
    await loadProject(projectId);
    navigate(pathForPage(page));
  };

  return (
    <ProjectOverview
      currentProjectId={projectDraft.id}
      onNavigate={navigateToPage}
      onOpenProject={(projectId, page) => void openProject(projectId, page)}
      projects={projects}
    />
  );
}

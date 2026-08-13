import { useEffect, useMemo, useState } from "react";

import { api } from "../api/client";
import { useGuideSync } from "../app/GuideSyncProvider";
import { ProjectProfilePage } from "../features/profile/ProjectProfilePage";
import { activeWorkflowTaskStatus } from "../lib/workflow";
import type { ProjectPipelineState, ProjectProfileSnapshot } from "../types";

export function ProjectProfileRoutePage() {
  const { projectDraft } = useGuideSync();
  const [profile, setProfile] = useState<ProjectProfileSnapshot | null>(null);
  const [state, setState] = useState<ProjectPipelineState | null>(null);
  const [loading, setLoading] = useState(false);

  const refresh = async () => {
    if (!projectDraft.id) {
      setProfile(null);
      setState(null);
      return;
    }
    setLoading(true);
    try {
      const [nextState, nextProfile] = await Promise.allSettled([
        api.getWorkflowState(projectDraft.id),
        api.getProjectProfile(projectDraft.id)
      ]);
      setState(nextState.status === "fulfilled" ? nextState.value : null);
      setProfile(nextProfile.status === "fulfilled" ? nextProfile.value : null);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void refresh();
  }, [projectDraft.id]);

  const activeTask = useMemo(
    () =>
      state?.tasks
        .filter(
          (task) => task.kind === "project_profile" && activeWorkflowTaskStatus(task.status)
        )
        .at(-1) || null,
    [state]
  );

  useEffect(() => {
    if (!activeTask) {
      return;
    }
    const timer = window.setInterval(() => void refresh(), 3000);
    return () => window.clearInterval(timer);
  }, [activeTask?.id, activeTask?.status, projectDraft.id]);

  return (
    <ProjectProfilePage
      activeTask={activeTask}
      loading={loading}
      onRefresh={refresh}
      profile={profile}
      project={projectDraft}
      state={state}
    />
  );
}

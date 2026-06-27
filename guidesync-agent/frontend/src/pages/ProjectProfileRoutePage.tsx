import { useEffect, useState } from "react";

import { api } from "../api/client";
import { useGuideSync } from "../app/GuideSyncProvider";
import { ProjectProfilePage } from "../features/profile/ProjectProfilePage";
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

  return (
    <ProjectProfilePage
      loading={loading}
      onRefresh={refresh}
      profile={profile}
      project={projectDraft}
      state={state}
    />
  );
}

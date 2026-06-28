import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { api } from "../api/client";
import { useGuideSync } from "../app/GuideSyncProvider";
import { pathForPage } from "../app/routePaths";
import { RunAnalysisPage } from "../features/runs/RunAnalysisPage";
import type { ProjectPipelineState, RunSummary } from "../types";

export function RunAnalysisRoutePage() {
  const navigate = useNavigate();
  const {
    openRun,
    projectDraft,
    runStatus,
    setRunStatus
  } = useGuideSync();
  const [workflowState, setWorkflowState] = useState<ProjectPipelineState | null>(null);
  const [workflowStateLoading, setWorkflowStateLoading] = useState(false);

  const refreshWorkflowState = useCallback(async () => {
    if (!projectDraft.id) {
      setWorkflowState(null);
      setWorkflowStateLoading(false);
      return;
    }
    setWorkflowStateLoading(true);
    try {
      setWorkflowState(await api.getWorkflowState(projectDraft.id));
    } catch {
      setWorkflowState(null);
    } finally {
      setWorkflowStateLoading(false);
    }
  }, [projectDraft.id]);

  useEffect(() => {
    void refreshWorkflowState();
  }, [refreshWorkflowState]);

  const openCreatedRun = async (summary: RunSummary) => {
    await openRun(summary);
    navigate(pathForPage("reports"));
  };

  return (
    <RunAnalysisPage
      onRunCreated={openCreatedRun}
      onStatusChange={setRunStatus}
      onWorkflowStateRefresh={refreshWorkflowState}
      project={projectDraft}
      runStatus={runStatus}
      workflowState={workflowState}
      workflowStateLoading={workflowStateLoading}
    />
  );
}

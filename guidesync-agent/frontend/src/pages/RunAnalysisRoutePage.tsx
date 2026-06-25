import { useNavigate } from "react-router-dom";

import { useGuideSync } from "../app/GuideSyncProvider";
import { pathForPage } from "../app/routePaths";
import { RunAnalysisPage } from "../features/runs/RunAnalysisPage";
import type { RunSummary } from "../types";

export function RunAnalysisRoutePage() {
  const navigate = useNavigate();
  const {
    modelProfiles,
    openRun,
    projectDraft,
    runStatus,
    setRunStatus
  } = useGuideSync();

  const openCreatedRun = async (summary: RunSummary) => {
    await openRun(summary);
    navigate(pathForPage("reports"));
  };

  return (
    <RunAnalysisPage
      onRunCreated={openCreatedRun}
      onStatusChange={setRunStatus}
      modelProfiles={modelProfiles}
      project={projectDraft}
      runStatus={runStatus}
    />
  );
}

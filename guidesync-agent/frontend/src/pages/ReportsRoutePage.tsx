import { useEffect } from "react";

import { useGuideSync } from "../app/GuideSyncProvider";
import { ReportsPage } from "../features/reports/ReportsPage";

export function ReportsRoutePage() {
  const {
    clearSelectedRun,
    projectDraft,
    refreshReports,
    reports,
    reportsLoading,
    selectedRun,
    selectRun
  } = useGuideSync();

  useEffect(() => {
    void refreshReports(projectDraft.id);
  }, [projectDraft.id, refreshReports]);

  return (
    <ReportsPage
      loading={reportsLoading}
      onBackToList={clearSelectedRun}
      onRefresh={() => void refreshReports(projectDraft.id)}
      onSelectRun={(runId) => void selectRun(runId)}
      projectName={projectDraft.id ? projectDraft.name : ""}
      reports={reports}
      selectedRun={selectedRun}
    />
  );
}

import { notifications } from "@mantine/notifications";
import { useEffect, useMemo, useState } from "react";

import { api } from "../api/client";
import { useGuideSync } from "../app/GuideSyncProvider";
import { ReportsPage } from "../features/reports/ReportsPage";
import { terminalStatus } from "../lib/branches";
import type { ProjectWorkflowTask } from "../types";

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
  const [workflowTasks, setWorkflowTasks] = useState<ProjectWorkflowTask[]>([]);
  const [cancelling, setCancelling] = useState(false);

  useEffect(() => {
    void refreshReports(projectDraft.id);
  }, [projectDraft.id, refreshReports]);

  useEffect(() => {
    if (!projectDraft.id || !selectedRun) {
      setWorkflowTasks([]);
      return;
    }
    const loadTasks = async () => {
      setWorkflowTasks(await api.listWorkflowTasks(projectDraft.id as string));
    };
    void loadTasks();
    if (terminalStatus(selectedRun.status)) {
      return;
    }
    const timer = window.setInterval(() => void loadTasks(), 3000);
    return () => window.clearInterval(timer);
  }, [projectDraft.id, selectedRun]);

  const selectedTasks = useMemo(
    () =>
      workflowTasks.filter(
        (task) => "run_id" in task.input && task.input.run_id === selectedRun?.run_id
      ),
    [selectedRun?.run_id, workflowTasks]
  );

  const cancelSelectedRun = async () => {
    if (!selectedRun) {
      return;
    }
    setCancelling(true);
    try {
      await api.cancelRun(selectedRun.run_id);
      await selectRun(selectedRun.run_id);
      if (projectDraft.id) {
        setWorkflowTasks(await api.listWorkflowTasks(projectDraft.id));
      }
      notifications.show({
        color: "teal",
        message: "Unfinished analysis tasks were cancelled; completed artifacts were kept.",
        title: "Analysis cancelled"
      });
    } catch (error) {
      notifications.show({
        color: "red",
        message: error instanceof Error ? error.message : "Could not cancel the run",
        title: "Cancellation failed"
      });
    } finally {
      setCancelling(false);
    }
  };

  return (
    <ReportsPage
      loading={reportsLoading}
      cancelling={cancelling}
      onCancelRun={() => void cancelSelectedRun()}
      onBackToList={clearSelectedRun}
      onRefresh={() => void refreshReports(projectDraft.id)}
      onSelectRun={(runId) => void selectRun(runId)}
      projectName={projectDraft.id ? projectDraft.name : ""}
      reports={reports}
      selectedRun={selectedRun}
      workflowTasks={selectedTasks}
    />
  );
}

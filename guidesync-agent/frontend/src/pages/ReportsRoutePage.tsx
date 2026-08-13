import { notifications } from "@mantine/notifications";
import { useEffect, useMemo, useState } from "react";

import { api } from "../api/client";
import { useGuideSync } from "../app/GuideSyncProvider";
import { ReportsPage } from "../features/reports/ReportsPage";
import { terminalStatus } from "../lib/branches";
import { isVideoActiveStatus } from "../lib/videoPresentation";
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
  const [cancellingRunId, setCancellingRunId] = useState<string | null>(null);
  const [retryingRunId, setRetryingRunId] = useState<string | null>(null);
  const [videoActionRunId, setVideoActionRunId] = useState<string | null>(null);

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
    const presentationStatus = selectedRun.video_presentation?.status || "disabled";
    const presentationTerminal = !isVideoActiveStatus(presentationStatus);
    if (terminalStatus(selectedRun.status) && presentationTerminal) {
      return;
    }
    const refreshSelectedRun = async () => {
      await Promise.all([loadTasks(), selectRun(selectedRun.run_id)]);
    };
    const timer = window.setInterval(() => void refreshSelectedRun(), 3000);
    return () => window.clearInterval(timer);
  }, [projectDraft.id, selectRun, selectedRun]);

  const selectedTasks = useMemo(
    () =>
      workflowTasks.filter(
        (task) => "run_id" in task.input && task.input.run_id === selectedRun?.run_id
      ),
    [selectedRun?.run_id, workflowTasks]
  );
  useEffect(() => {
    const hasActiveReport = reports.some((report) =>
      !terminalStatus(report.status)
      || isVideoActiveStatus(report.video_presentation?.status || "disabled")
    );
    if (!projectDraft.id || !hasActiveReport) {
      return;
    }
    const timer = window.setInterval(() => void refreshReports(projectDraft.id), 3000);
    return () => window.clearInterval(timer);
  }, [projectDraft.id, reports, refreshReports]);

  const generateVideo = async (runId: string, regenerate: boolean) => {
    setVideoActionRunId(runId);
    try {
      await api.generateVideoPresentation(runId, regenerate);
      await refreshReports(projectDraft.id);
      if (selectedRun?.run_id === runId) {
        await selectRun(runId);
      }
      notifications.show({
        color: "teal",
        message: regenerate
          ? "A new video version has been queued. The current video remains available."
          : "Video generation has been queued.",
        title: regenerate ? "Video regeneration queued" : "Video generation queued"
      });
    } catch (error) {
      notifications.show({
        color: "red",
        message: error instanceof Error ? error.message : "Could not queue video generation",
        title: "Video action failed"
      });
    } finally {
      setVideoActionRunId(null);
    }
  };

  const retryRun = async (runId: string) => {
    setRetryingRunId(runId);
    try {
      const plan = await api.retryRun(runId);
      await refreshReports(projectDraft.id);
      if (plan.run) {
        await selectRun(plan.run.run_id);
      }
      notifications.show({
        color: "teal",
        message: "A new report run was queued; the failed run remains in history.",
        title: "Report retry queued"
      });
    } catch (error) {
      notifications.show({
        color: "red",
        message: error instanceof Error ? error.message : "Could not retry the report",
        title: "Report retry failed"
      });
    } finally {
      setRetryingRunId(null);
    }
  };

  const cancelRun = async (runId: string) => {
    setCancellingRunId(runId);
    try {
      await api.cancelRun(runId);
      await refreshReports(projectDraft.id);
      if (selectedRun?.run_id === runId) {
        await selectRun(runId);
      }
      if (projectDraft.id) {
        setWorkflowTasks(await api.listWorkflowTasks(projectDraft.id));
      }
      notifications.show({
        color: "teal",
        message: "Unfinished report tasks were stopped; completed artifacts were kept.",
        title: "Report stopped"
      });
    } catch (error) {
      notifications.show({
        color: "red",
        message: error instanceof Error ? error.message : "Could not cancel the run",
        title: "Cancellation failed"
      });
    } finally {
      setCancellingRunId(null);
    }
  };

  return (
    <ReportsPage
      loading={reportsLoading}
      cancellingRunId={cancellingRunId}
      onCancelRun={(runId) => void cancelRun(runId)}
      onBackToList={clearSelectedRun}
      onRefresh={() => void refreshReports(projectDraft.id)}
      onRetryRun={(runId) => void retryRun(runId)}
      onSelectRun={(runId) => void selectRun(runId)}
      onVideoAction={(runId, regenerate) => void generateVideo(runId, regenerate)}
      projectName={projectDraft.id ? projectDraft.name : ""}
      reports={reports}
      retryingRunId={retryingRunId}
      selectedRun={selectedRun}
      workflowTasks={selectedTasks}
      videoActionRunId={videoActionRunId}
    />
  );
}

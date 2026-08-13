import { useCallback, useEffect, useMemo, useState } from "react";

import { api } from "../api/client";
import { useGuideSync } from "../app/GuideSyncProvider";
import { KnowledgeBasePage } from "../features/knowledge/KnowledgeBasePage";
import { activeWorkflowTaskStatus } from "../lib/workflow";
import type { ProjectWorkflowTask } from "../types";

export function KnowledgeRoutePage() {
  const { knowledgeRuns, projectDraft, refreshKnowledgeRuns } = useGuideSync();
  const [workflowTasks, setWorkflowTasks] = useState<ProjectWorkflowTask[]>([]);

  const refresh = useCallback(async () => {
    if (!projectDraft.id) {
      setWorkflowTasks([]);
      await refreshKnowledgeRuns(null);
      return;
    }
    const projectId = projectDraft.id;
    const [, tasks] = await Promise.all([
      refreshKnowledgeRuns(projectId),
      api.listWorkflowTasks(projectId)
    ]);
    setWorkflowTasks(tasks);
  }, [projectDraft.id, refreshKnowledgeRuns]);

  const knowledgeTask = useMemo(
    () => {
      const tasks = workflowTasks.filter((task) => task.kind === "knowledge_index");
      return tasks.filter((task) => activeWorkflowTaskStatus(task.status)).at(-1) || tasks.at(-1) || null;
    },
    [workflowTasks]
  );

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (!knowledgeTask || !activeWorkflowTaskStatus(knowledgeTask.status)) {
      return;
    }
    const timer = window.setInterval(() => void refresh(), 3000);
    return () => window.clearInterval(timer);
  }, [knowledgeTask, refresh]);

  return (
    <KnowledgeBasePage
      knowledgeTask={knowledgeTask}
      onRefresh={refresh}
      project={projectDraft}
      runs={knowledgeRuns}
    />
  );
}

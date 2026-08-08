import { useCallback, useEffect, useMemo, useState } from "react";

import { api } from "../api/client";
import { useGuideSync } from "../app/GuideSyncProvider";
import { KnowledgeBasePage } from "../features/knowledge/KnowledgeBasePage";
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
    () => workflowTasks.filter((task) => task.kind === "knowledge_index").at(-1) || null,
    [workflowTasks]
  );

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (!knowledgeTask || !["queued", "running", "retrying"].includes(knowledgeTask.status)) {
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

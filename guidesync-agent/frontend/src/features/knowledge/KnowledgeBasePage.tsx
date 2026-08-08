import { Stack } from "@mantine/core";

import { PageHeader } from "../../components/PageHeader";
import type { KnowledgeIndexRun, ProjectConfig, ProjectWorkflowTask } from "../../types";
import { KnowledgePanel } from "./KnowledgePanel";

interface KnowledgeBasePageProps {
  knowledgeTask: ProjectWorkflowTask | null;
  project: ProjectConfig;
  runs: KnowledgeIndexRun[];
  onRefresh: () => Promise<void>;
}

export function KnowledgeBasePage({ knowledgeTask, project, runs, onRefresh }: KnowledgeBasePageProps) {
  return (
    <Stack gap="lg">
      <PageHeader title={project.id ? `Knowledge base · ${project.name}` : "Knowledge base"} />
      <KnowledgePanel
        knowledgeTask={knowledgeTask}
        onRefresh={onRefresh}
        projectId={project.id}
        runs={runs}
      />
    </Stack>
  );
}

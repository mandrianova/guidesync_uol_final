import { Stack } from "@mantine/core";

import { PageHeader } from "../../components/PageHeader";
import type { KnowledgeIndexRun, ProjectConfig } from "../../types";
import { KnowledgePanel } from "./KnowledgePanel";

interface KnowledgeBasePageProps {
  project: ProjectConfig;
  runs: KnowledgeIndexRun[];
  onRefresh: () => Promise<void>;
}

export function KnowledgeBasePage({ project, runs, onRefresh }: KnowledgeBasePageProps) {
  return (
    <Stack gap="lg">
      <PageHeader title={project.id ? `Knowledge base · ${project.name}` : "Knowledge base"} />
      <KnowledgePanel onRefresh={onRefresh} projectId={project.id} runs={runs} />
    </Stack>
  );
}

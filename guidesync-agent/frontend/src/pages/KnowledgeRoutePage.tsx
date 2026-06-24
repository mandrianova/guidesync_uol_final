import { useEffect } from "react";

import { useGuideSync } from "../app/GuideSyncProvider";
import { KnowledgeBasePage } from "../features/knowledge/KnowledgeBasePage";

export function KnowledgeRoutePage() {
  const { knowledgeRuns, projectDraft, refreshKnowledgeRuns } = useGuideSync();

  useEffect(() => {
    void refreshKnowledgeRuns(projectDraft.id);
  }, [projectDraft.id, refreshKnowledgeRuns]);

  return (
    <KnowledgeBasePage
      onRefresh={() => refreshKnowledgeRuns(projectDraft.id)}
      project={projectDraft}
      runs={knowledgeRuns}
    />
  );
}

import { useCallback } from "react";
import { useNavigate } from "react-router-dom";

import type { PageId } from "../types";
import { useGuideSync } from "./GuideSyncProvider";
import { pathForPage } from "./routePaths";

export function usePageNavigation() {
  const navigate = useNavigate();
  const { projectDraft, refreshKnowledgeRuns, refreshReports } = useGuideSync();

  return useCallback(
    (page: PageId) => {
      if (page === "reports") {
        void refreshReports(projectDraft.id);
      }
      if (page === "knowledge") {
        void refreshKnowledgeRuns(projectDraft.id);
      }
      navigate(pathForPage(page));
    },
    [navigate, projectDraft.id, refreshKnowledgeRuns, refreshReports]
  );
}

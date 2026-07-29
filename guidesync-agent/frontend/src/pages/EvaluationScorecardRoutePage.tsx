import { notifications } from "@mantine/notifications";
import { useEffect, useState } from "react";

import { api } from "../api/client";
import { useGuideSync } from "../app/GuideSyncProvider";
import { EvaluationScorecardPage } from "../features/evaluation/EvaluationScorecardPage";
import type {
  EvaluationComparisonRecord,
  EvaluationExperimentRecord,
  EvaluationRunRecord
} from "../types";

export function EvaluationScorecardRoutePage() {
  const { projectDraft } = useGuideSync();
  const [experiments, setExperiments] = useState<EvaluationExperimentRecord[]>([]);
  const [selectedExperimentId, setSelectedExperimentId] = useState<string | null>(null);
  const [runs, setRuns] = useState<EvaluationRunRecord[]>([]);
  const [comparisons, setComparisons] = useState<EvaluationComparisonRecord[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let ignore = false;
    setExperiments([]);
    setSelectedExperimentId(null);
    setRuns([]);
    setComparisons([]);
    if (!projectDraft.id) {
      return () => {
        ignore = true;
      };
    }
    setLoading(true);
    api
      .listEvaluationExperiments(projectDraft.id)
      .then((page) => {
        if (!ignore) {
          setExperiments(page.items);
          setSelectedExperimentId(page.items[0]?.manifest.id ?? null);
        }
      })
      .catch((error) => {
        if (!ignore) {
          notifications.show({
            color: "red",
            message: error instanceof Error ? error.message : "Could not load experiments",
            title: "Evaluation data unavailable"
          });
        }
      })
      .finally(() => {
        if (!ignore) {
          setLoading(false);
        }
      });
    return () => {
      ignore = true;
    };
  }, [projectDraft.id]);

  useEffect(() => {
    let ignore = false;
    setRuns([]);
    setComparisons([]);
    if (!selectedExperimentId) {
      return () => {
        ignore = true;
      };
    }
    setLoading(true);
    Promise.all([
      api.listEvaluationRuns(selectedExperimentId, { limit: 500 }),
      api.listEvaluationComparisons(selectedExperimentId, 500)
    ])
      .then(([runPage, comparisonPage]) => {
        if (!ignore) {
          setRuns(runPage.items);
          setComparisons(comparisonPage.items);
        }
      })
      .catch((error) => {
        if (!ignore) {
          notifications.show({
            color: "red",
            message: error instanceof Error ? error.message : "Could not load scorecards",
            title: "Evaluation scorecards unavailable"
          });
        }
      })
      .finally(() => {
        if (!ignore) {
          setLoading(false);
        }
      });
    return () => {
      ignore = true;
    };
  }, [selectedExperimentId]);

  const experiment =
    experiments.find((record) => record.manifest.id === selectedExperimentId) ?? null;

  return (
    <EvaluationScorecardPage
      comparisons={comparisons}
      experiment={experiment}
      experiments={experiments}
      loading={loading}
      onSelectExperiment={setSelectedExperimentId}
      project={projectDraft}
      runs={runs}
      selectedExperimentId={selectedExperimentId}
    />
  );
}

import {
  Alert,
  Box,
  Group,
  Paper,
  Select,
  SimpleGrid,
  Stack,
  Text,
  Title
} from "@mantine/core";
import {
  IconAlertTriangle,
  IconFlask
} from "@tabler/icons-react";
import { useEffect, useMemo, useState } from "react";

import { EmptyState } from "../../components/EmptyState";
import { PageHeader } from "../../components/PageHeader";
import { SectionPanel } from "../../components/SectionPanel";
import { StatusBadge } from "../../components/StatusBadge";
import { formatDateTime } from "../../lib/dates";
import type {
  EvaluationComparisonRecord,
  EvaluationExperimentRecord,
  EvaluationMeasurementStatus,
  EvaluationMetric,
  EvaluationRunRecord,
  PipelineStage,
  ProjectConfig,
  StageEvaluationResult
} from "../../types";
import {
  CausalEvidencePanel,
  EfficiencyPanel,
  EndToEndPanel,
  EvidenceReferences,
  formatMetric,
  humanize,
  LedgerFact,
  ProvenanceStrip,
  rawMetric
} from "./EvaluationScorecardPanels";

const pipelineStages: PipelineStage[] = [
  "input_freeze",
  "project_profile",
  "knowledge_index",
  "nlp_annotation",
  "retrieval",
  "change_analysis",
  "edit_planning",
  "documentation_generation",
  "validation",
  "post_edit_reindex",
  "end_to_end"
];

interface EvaluationScorecardPageProps {
  comparisons: EvaluationComparisonRecord[];
  experiment: EvaluationExperimentRecord | null;
  experiments: EvaluationExperimentRecord[];
  loading: boolean;
  project: ProjectConfig;
  runs: EvaluationRunRecord[];
  selectedExperimentId: string | null;
  onSelectExperiment: (experimentId: string) => void;
}

export function EvaluationScorecardPage({
  comparisons,
  experiment,
  experiments,
  loading,
  project,
  runs,
  selectedExperimentId,
  onSelectExperiment
}: EvaluationScorecardPageProps) {
  const [caseId, setCaseId] = useState<string | null>(null);
  const [conditionId, setConditionId] = useState<string | null>(null);
  const [repetition, setRepetition] = useState<string | null>("1");

  useEffect(() => {
    const firstCase = experiment?.manifest.cases[0]?.id ?? null;
    const fullCondition =
      experiment?.manifest.conditions.find(
        (protocol) => protocol.condition.kind === "full"
      )?.condition.id ?? null;
    setCaseId(firstCase);
    setConditionId(fullCondition);
    setRepetition("1");
  }, [experiment?.manifest.id]);

  const selectedRun = useMemo(
    () =>
      runs.find(
        (record) =>
          record.run.manifest.case_id === caseId &&
          record.run.manifest.condition_id === conditionId &&
          record.run.manifest.repetition === Number(repetition)
      ) ?? null,
    [caseId, conditionId, repetition, runs]
  );
  const selectedCase =
    experiment?.manifest.cases.find((item) => item.id === caseId) ?? null;
  const stageResults = normalizeStageResults(selectedRun);
  const endToEnd = stageResults.get("end_to_end");

  return (
    <Stack gap="lg">
      <PageHeader
        label="Evaluation lab"
        title={project.id ? `Pipeline evidence · ${project.name}` : "Pipeline evidence"}
      />

      {!project.id ? (
        <EmptyState>Save a project before recording evaluation experiments.</EmptyState>
      ) : !experiment ? (
        <EmptyState>
          {loading
            ? "Loading evaluation experiments."
            : "No evaluation experiment has been recorded for this project yet."}
        </EmptyState>
      ) : (
        <>
          <Paper className="evaluation-thesis" p="lg" withBorder>
            <Stack gap="md">
              <Group align="flex-start" justify="space-between">
                <div>
                  <Text className="eyebrow" size="xs">
                    Experiment question
                  </Text>
                  <Title order={2}>Can every pipeline stage prove its value?</Title>
                  <Text c="dimmed" mt={6} maw={760}>
                    Health shows whether a stage ran correctly. Quality measures its
                    output against frozen labels. Causal deltas show what changes when
                    the stage is removed.
                  </Text>
                </div>
                <IconFlask className="evaluation-thesis-icon" size={38} />
              </Group>

              <SimpleGrid cols={{ base: 2, md: 5 }} spacing="xs">
                <LedgerFact label="Cases" value={String(experiment.manifest.cases.length)} />
                <LedgerFact
                  label="Conditions"
                  value={String(experiment.manifest.conditions.length)}
                />
                <LedgerFact
                  label="Runs"
                  value={`${experiment.completed_run_count}/${expectedRunCount(experiment)}`}
                />
                <LedgerFact label="Failed" value={String(experiment.failed_run_count)} />
                <LedgerFact
                  label="Paired comparisons"
                  value={String(experiment.comparison_count)}
                />
              </SimpleGrid>

              <SimpleGrid cols={{ base: 1, sm: 2, lg: 4 }}>
                <Select
                  data={experiments.map((record) => ({
                    label: `${record.manifest.id} · ${formatDateTime(record.updated_at)}`,
                    value: record.manifest.id
                  }))}
                  label="Frozen experiment"
                  onChange={(value) => value && onSelectExperiment(value)}
                  searchable
                  value={selectedExperimentId}
                />
                <Select
                  data={experiment.manifest.cases.map((item) => ({
                    label: item.id,
                    value: item.id
                  }))}
                  label="Evaluation case"
                  onChange={setCaseId}
                  value={caseId}
                />
                <Select
                  data={experiment.manifest.conditions.map((protocol) => ({
                    label: `${protocol.condition.id} · ${protocol.condition.label}`,
                    value: protocol.condition.id
                  }))}
                  label="Condition"
                  onChange={setConditionId}
                  value={conditionId}
                />
                <Select
                  data={Array.from(
                    { length: experiment.manifest.repetitions },
                    (_, index) => ({
                      label: `Repetition ${index + 1}`,
                      value: String(index + 1)
                    })
                  )}
                  label="Repeat"
                  onChange={setRepetition}
                  value={repetition}
                />
              </SimpleGrid>
            </Stack>
          </Paper>

          <ProvenanceStrip experiment={experiment} selectedCase={selectedCase} />

          {selectedRun?.run.status === "failed" ? (
            <Alert color="red" icon={<IconAlertTriangle size={20} />} title="Run failed">
              {selectedRun.run.failure}
            </Alert>
          ) : !selectedRun ? (
            <Alert color="yellow" icon={<IconAlertTriangle size={20} />} title="Run missing">
              This case, condition, and repetition has no persisted result. Missing
              observations are not converted to zero.
            </Alert>
          ) : null}

          <SectionPanel
            description="The evidence ledger keeps operational health separate from intrinsic output quality."
            title="Stage evidence ledger"
          >
            <Stack className="evaluation-ledger" gap={0}>
              {pipelineStages.map((stage, index) => (
                <StageLedgerRow
                  goldRef={selectedCase?.gold_artifact_ref}
                  index={index}
                  key={stage}
                  result={stageResults.get(stage)}
                  stage={stage}
                />
              ))}
            </Stack>
          </SectionPanel>

          <SimpleGrid cols={{ base: 1, lg: 2 }}>
            <EndToEndPanel result={endToEnd} selectedCase={selectedCase} />
            <EfficiencyPanel run={selectedRun} />
          </SimpleGrid>

          <CausalEvidencePanel comparisons={comparisons} />
        </>
      )}
    </Stack>
  );
}

function StageLedgerRow({
  goldRef,
  index,
  result,
  stage
}: {
  goldRef?: string;
  index: number;
  result?: StageEvaluationResult;
  stage: PipelineStage;
}) {
  const status: EvaluationMeasurementStatus = result?.status ?? "not_evaluated";
  const references = [...(result?.artifact_refs ?? []), ...(goldRef ? [goldRef] : [])];
  return (
    <Box className={`evaluation-stage-row status-${status}`}>
      <Box className="evaluation-stage-spine">
        <Text className="evaluation-stage-number" size="xs">
          {String(index + 1).padStart(2, "0")}
        </Text>
        {index < pipelineStages.length - 1 ? <span /> : null}
      </Box>
      <Box className="evaluation-stage-name">
        <Text fw={850}>{humanize(stage)}</Text>
        <StatusBadge status={humanize(status)} />
      </Box>
      <MetricGroup
        emptyStatus={status}
        findings={[]}
        label="Health"
        metrics={result?.health_metrics ?? []}
        references={references}
      />
      <MetricGroup
        emptyStatus={status}
        findings={result?.findings ?? []}
        label="Intrinsic quality"
        metrics={result?.quality_metrics ?? []}
        references={references}
      />
    </Box>
  );
}

function MetricGroup({
  emptyStatus,
  findings,
  label,
  metrics,
  references
}: {
  emptyStatus: EvaluationMeasurementStatus;
  findings: string[];
  label: string;
  metrics: EvaluationMetric[];
  references: string[];
}) {
  return (
    <Stack className="evaluation-metric-group" gap="xs">
      <Text c="dimmed" fw={800} size="xs">
        {label}
      </Text>
      {metrics.length ? (
        metrics.map((metric) => (
          <Paper className={`evaluation-metric status-${metric.status}`} key={metric.name} p="sm">
            <Group align="flex-start" justify="space-between" wrap="nowrap">
              <div>
                <Text fw={800} size="sm">
                  {humanize(metric.name)}
                </Text>
                <Text c="dimmed" size="xs">
                  {rawMetric(metric)}
                </Text>
              </div>
              <Text className="evaluation-metric-value" fw={900}>
                {formatMetric(metric)}
              </Text>
            </Group>
            <EvidenceReferences compact references={references} />
            {metric.warnings.map((warning) => (
              <Text c="orange.8" key={warning} size="xs">
                {warning}
              </Text>
            ))}
          </Paper>
        ))
      ) : (
        <Text c="dimmed" size="sm">
          {emptyStatus === "measured"
            ? "No metric was defined for this group."
            : humanize(emptyStatus)}
        </Text>
      )}
      {findings.map((finding) => (
        <Text c="orange.8" key={finding} size="xs">
          {finding}
        </Text>
      ))}
    </Stack>
  );
}

function normalizeStageResults(
  run: EvaluationRunRecord | null
): Map<PipelineStage, StageEvaluationResult> {
  return new Map(
    (run?.run.scorecard?.stage_results ?? []).map((result) => [
      result.stage,
      {
        ...result,
        artifact_refs: result.artifact_refs ?? [],
        findings: result.findings ?? [],
        health_metrics: (result.health_metrics ?? []).map(normalizeMetric),
        quality_metrics: (result.quality_metrics ?? []).map(normalizeMetric)
      }
    ])
  );
}

function normalizeMetric(
  metric: Omit<EvaluationMetric, "warnings"> & { warnings?: string[] }
): EvaluationMetric {
  return { ...metric, warnings: metric.warnings ?? [] };
}

function expectedRunCount(experiment: EvaluationExperimentRecord): number {
  return (
    experiment.manifest.conditions.reduce(
      (total, protocol) =>
        total +
        (protocol.bounded_case_ids?.length || experiment.manifest.cases.length),
      0
    ) * experiment.manifest.repetitions
  );
}

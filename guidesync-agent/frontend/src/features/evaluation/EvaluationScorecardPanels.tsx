import {
  Anchor,
  Badge,
  Box,
  Group,
  Paper,
  SimpleGrid,
  Stack,
  Text
} from "@mantine/core";
import {
  IconArrowDown,
  IconLink,
  IconReceipt2
} from "@tabler/icons-react";

import { EmptyState } from "../../components/EmptyState";
import { SectionPanel } from "../../components/SectionPanel";
import { StatusBadge } from "../../components/StatusBadge";
import type {
  EvaluationComparisonRecord,
  EvaluationExperimentRecord,
  EvaluationMetric,
  EvaluationRunRecord,
  StageEvaluationResult
} from "../../types";

export function ProvenanceStrip({
  experiment,
  selectedCase
}: {
  experiment: EvaluationExperimentRecord;
  selectedCase: EvaluationExperimentRecord["manifest"]["cases"][number] | null;
}) {
  const goldStatus = selectedCase?.gold_adjudication_status;
  const status =
    goldStatus === "adjudicated"
      ? "adjudicated"
      : goldStatus === "single_annotator"
        ? "provisional"
        : "draft";
  return (
    <Paper className="evaluation-provenance" p="md" withBorder>
      <Group align="center" justify="space-between">
        <Group gap="xl">
          <ProvenanceFact
            label="Application"
            value={shortChecksum(experiment.manifest.configuration.application_commit)}
          />
          <ProvenanceFact
            label="Evaluator"
            value={experiment.manifest.configuration.evaluator_version}
          />
          <ProvenanceFact
            label="Manifest"
            value={shortChecksum(experiment.manifest_checksum)}
          />
          <ProvenanceFact
            label="Gold labels"
            value={selectedCase?.gold_version ?? "Missing"}
          />
        </Group>
        <Group gap="xs">
          <StatusBadge status={status} />
          {selectedCase ? (
            <EvidenceReferences references={[selectedCase.gold_artifact_ref]} />
          ) : null}
        </Group>
      </Group>
    </Paper>
  );
}

export function EndToEndPanel({
  result,
  selectedCase
}: {
  result?: StageEvaluationResult;
  selectedCase: EvaluationExperimentRecord["manifest"]["cases"][number] | null;
}) {
  return (
    <SectionPanel
      description="Final documentation quality, reported without collapsing the dimensions into one score."
      title="End-to-end quality"
    >
      <Stack gap="sm">
        {result?.quality_metrics.length ? (
          result.quality_metrics.map((metric) => (
            <Paper className="evaluation-outcome-row" key={metric.name} p="sm" withBorder>
              <Group justify="space-between">
                <div>
                  <Text fw={850}>{humanize(metric.name)}</Text>
                  <Text c="dimmed" size="xs">
                    {rawMetric(metric)}
                  </Text>
                </div>
                <Text fw={900}>{formatMetric(metric)}</Text>
              </Group>
              <EvidenceReferences
                compact
                references={[
                  ...(result.artifact_refs ?? []),
                  ...(selectedCase ? [selectedCase.gold_artifact_ref] : [])
                ]}
              />
            </Paper>
          ))
        ) : (
          <EmptyState>End-to-end quality was not evaluated for this run.</EmptyState>
        )}
      </Stack>
    </SectionPanel>
  );
}

export function EfficiencyPanel({ run }: { run: EvaluationRunRecord | null }) {
  const usage = run?.run.usage;
  return (
    <SectionPanel
      description="Observed execution cost stays beside quality, not inside it."
      title="Efficiency"
    >
      <SimpleGrid cols={2}>
        <LedgerFact
          label="Latency"
          value={
            run?.run.latency_ms == null
              ? "Not measured"
              : `${(run.run.latency_ms / 1000).toFixed(2)} s`
          }
        />
        <LedgerFact
          label="Tokens"
          value={usage ? usage.total_tokens.toLocaleString() : "Not measured"}
        />
        <LedgerFact
          label="Model calls"
          value={usage ? String(usage.calls) : "Not measured"}
        />
        <LedgerFact
          label="Estimated tokens"
          value={usage ? usage.estimated_tokens.toLocaleString() : "Not measured"}
        />
      </SimpleGrid>
      {run ? (
        <EvidenceReferences
          references={[...(run.run.artifact_refs ?? []), ...(run.run.transcript_refs ?? [])]}
        />
      ) : null}
    </SectionPanel>
  );
}

export function CausalEvidencePanel({
  comparisons
}: {
  comparisons: EvaluationComparisonRecord[];
}) {
  const intervals = comparisons.flatMap((record) =>
    (record.report.intervals ?? []).map((interval) => ({
      comparison: record,
      interval
    }))
  );
  return (
    <SectionPanel
      description="Paired full-versus-ablation deltas answer whether removing a stage changes the result."
      title="Causal contribution"
    >
      {!intervals.length ? (
        <EmptyState>
          No paired ablation comparison has been recorded. Stage necessity is not yet
          supported.
        </EmptyState>
      ) : (
        <SimpleGrid cols={{ base: 1, md: 2 }}>
          {intervals.map(({ comparison, interval }) => (
            <Paper
              className={`evaluation-causal-card status-${interval.status}`}
              key={`${comparison.id}:${interval.selector.stage}:${interval.selector.metric_name}`}
              p="md"
              withBorder
            >
              <Stack gap="sm">
                <Group justify="space-between">
                  <Badge color="violet" variant="light">
                    {comparison.report.full_condition_id} vs{" "}
                    {comparison.report.ablation_condition_id}
                  </Badge>
                  <StatusBadge status={humanize(interval.status)} />
                </Group>
                <div>
                  <Text c="dimmed" fw={800} size="xs">
                    {humanize(interval.selector.stage)} · {interval.selector.group}
                  </Text>
                  <Text fw={850}>{humanize(interval.selector.metric_name)}</Text>
                </div>
                <Group align="end" gap="xs">
                  <IconArrowDown color="var(--guidesync-causal)" size={22} />
                  <Text className="evaluation-delta" fw={900}>
                    {interval.mean_delta == null
                      ? "Not measured"
                      : signedPercent(interval.mean_delta)}
                  </Text>
                </Group>
                <Text c="dimmed" size="sm">
                  {interval.lower_bound == null || interval.upper_bound == null
                    ? "Confidence interval unavailable."
                    : `${Math.round(interval.confidence_level * 100)}% CI ${signedPercent(
                        interval.lower_bound
                      )} to ${signedPercent(interval.upper_bound)}`}
                </Text>
                <Text c="dimmed" size="xs">
                  {interval.paired_count} paired runs · {interval.case_count} independent
                  cases · {comparison.report.excluded_pair_ids?.length ?? 0} excluded
                </Text>
                <EvidenceReferences
                  compact
                  references={(comparison.report.observations ?? [])
                    .filter((item) => item.selector.metric_name === interval.selector.metric_name)
                    .flatMap((item) => [item.full_run_id, item.ablation_run_id])}
                />
                {[
                  ...(interval.warnings ?? []),
                  ...(comparison.report.warnings ?? [])
                ].map((warning) => (
                  <Text c="orange.8" key={warning} size="xs">
                    {warning}
                  </Text>
                ))}
              </Stack>
            </Paper>
          ))}
        </SimpleGrid>
      )}
    </SectionPanel>
  );
}

export function EvidenceReferences({
  compact = false,
  references
}: {
  compact?: boolean;
  references: string[];
}) {
  const unique = Array.from(new Set(references.filter(Boolean)));
  if (!unique.length) {
    return (
      <Text c="dimmed" size="xs">
        Evidence reference missing
      </Text>
    );
  }
  return (
    <Group className={compact ? "evaluation-evidence compact" : "evaluation-evidence"} gap={5}>
      <IconLink size={13} />
      {unique.slice(0, compact ? 2 : 4).map((reference) =>
        isNavigableReference(reference) ? (
          <Anchor href={reference} key={reference} size="xs" target="_blank">
            {shortReference(reference)}
          </Anchor>
        ) : (
          <Text className="evaluation-reference" key={reference} size="xs" title={reference}>
            {shortReference(reference)}
          </Text>
        )
      )}
      {unique.length > (compact ? 2 : 4) ? (
        <Text c="dimmed" size="xs">
          +{unique.length - (compact ? 2 : 4)}
        </Text>
      ) : null}
    </Group>
  );
}

export function LedgerFact({ label, value }: { label: string; value: string }) {
  return (
    <Box className="evaluation-ledger-fact">
      <Text c="dimmed" fw={800} size="xs">
        {label}
      </Text>
      <Text fw={900}>{value}</Text>
    </Box>
  );
}

function ProvenanceFact({ label, value }: { label: string; value: string }) {
  return (
    <Group gap={6}>
      <IconReceipt2 color="var(--guidesync-muted)" size={15} />
      <Text c="dimmed" size="xs">
        {label}
      </Text>
      <Text fw={800} size="xs">
        {value}
      </Text>
    </Group>
  );
}

export function formatMetric(metric: EvaluationMetric): string {
  if (metric.status !== "measured" || metric.value == null) {
    return humanize(metric.status);
  }
  if (metric.unit === "ratio") {
    return `${(metric.value * 100).toFixed(1)}%`;
  }
  const value = Number.isInteger(metric.value) ? metric.value : Number(metric.value.toFixed(3));
  return `${value.toLocaleString()} ${metric.unit}`;
}

export function rawMetric(metric: EvaluationMetric): string {
  if (metric.numerator == null || metric.denominator == null) {
    return "Raw counts unavailable";
  }
  return `${metric.numerator.toLocaleString()} / ${metric.denominator.toLocaleString()}`;
}

export function humanize(value: string): string {
  return value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function signedPercent(value: number): string {
  return `${value >= 0 ? "+" : ""}${(value * 100).toFixed(1)} pp`;
}

function shortChecksum(value: string): string {
  return value.length > 16 ? `${value.slice(0, 12)}…` : value;
}

function shortReference(value: string): string {
  return value.length > 30 ? `${value.slice(0, 27)}…` : value;
}

function isNavigableReference(value: string): boolean {
  return value.startsWith("/") || /^https?:\/\//i.test(value);
}

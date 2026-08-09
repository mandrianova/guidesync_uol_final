import {
  Anchor,
  Badge,
  Group,
  List,
  Paper,
  SimpleGrid,
  Stack,
  Text,
  Title
} from "@mantine/core";
import { useEffect, useState } from "react";

import { api, artifactUrl } from "../../api/client";
import { EmptyState } from "../../components/EmptyState";
import { StatusBadge } from "../../components/StatusBadge";
import { readableModelLabel } from "../../lib/modelProfiles";
import type {
  BrowserScreenshotEvidence,
  GuideSyncRunResult,
  RunTokenUsageSummary,
  ValidationFinding
} from "../../types";

function severityClass(severity: string): string {
  if (severity === "error") {
    return "severity-error";
  }
  if (severity === "warning") {
    return "severity-warning";
  }
  if (severity === "info") {
    return "severity-info";
  }
  return "severity-ok";
}

function FindingItem({ finding }: { finding: ValidationFinding }) {
  return (
    <Paper className={`finding-item ${severityClass(finding.severity)}`} p="sm" withBorder>
      <Text fw={800} size="sm">
        {finding.severity} / {finding.check}
      </Text>
      <Text size="sm">{finding.message}</Text>
      {finding.evidence_refs?.length ? (
        <Text className="report-breakable" c="dimmed" size="xs">
          evidence: {finding.evidence_refs.join(", ")}
        </Text>
      ) : null}
      {finding.artifact_refs?.length ? (
        <Text className="report-breakable" c="dimmed" size="xs">
          artifacts: {finding.artifact_refs.join(", ")}
        </Text>
      ) : null}
    </Paper>
  );
}

interface PipelineReportProps {
  result: GuideSyncRunResult | null;
}

interface ScreenshotArtifactLinks {
  prepared: string | null;
  raw: string | null;
}

export function screenshotArtifactLinks(
  runId: string,
  artifacts: Record<string, string>,
  screenshot: BrowserScreenshotEvidence
): ScreenshotArtifactLinks {
  const preparedName = screenshot.prepared_artifact_name;
  const rawName = screenshot.raw_artifact_name;
  return {
    prepared:
      preparedName && artifacts[preparedName]
        ? artifactUrl(runId, preparedName)
        : null,
    raw: rawName && artifacts[rawName] ? artifactUrl(runId, rawName) : null
  };
}

export function screenshotStatusColor(
  status: BrowserScreenshotEvidence["validation_status"]
): string {
  if (status === "passed") {
    return "teal";
  }
  if (status === "failed") {
    return "red";
  }
  if (status === "skipped") {
    return "gray";
  }
  return "yellow";
}

export function PipelineReport({ result }: PipelineReportProps) {
  const [tokenUsage, setTokenUsage] = useState<RunTokenUsageSummary | null>(null);
  const [tokenUsageError, setTokenUsageError] = useState<string | null>(null);

  useEffect(() => {
    let ignore = false;
    setTokenUsage(null);
    setTokenUsageError(null);
    if (!result?.run_id) {
      return () => {
        ignore = true;
      };
    }
    api.getRunModelUsageSummary(result.run_id)
      .then((summary) => {
        if (!ignore) {
          setTokenUsage(summary);
        }
      })
      .catch((error) => {
        if (!ignore) {
          setTokenUsageError(error instanceof Error ? error.message : "Could not load token usage");
        }
      });
    return () => {
      ignore = true;
    };
  }, [result?.run_id]);

  if (!result) {
    return <EmptyState>Select a report to inspect pipeline health.</EmptyState>;
  }

  const findings = result.findings || [];
  const warnings = result.evidence?.warnings || [];
  const visibleWarnings = warnings.slice(0, 8);
  const hiddenWarningCount = warnings.length - visibleWarnings.length;
  const provider = result.provider_metadata;
  const effectiveModel = result.request.effective_model_configuration;
  const screenshots = result.evidence?.browser_screenshots || [];
  const fallbackProviderLabel =
    provider?.provider || provider?.model
      ? readableModelLabel({
          provider: provider.provider as "mock" | "pydantic_ai" | "local_http",
          model: provider.model,
          base_url: null
        })
      : "n/a";
  const providerLabel = effectiveModel
    ? readableModelLabel(effectiveModel)
    : fallbackProviderLabel;

  return (
    <Stack gap="md">
      <SimpleGrid cols={{ base: 1, sm: 3 }}>
        <Paper className="metric-card" p="md" withBorder>
          <Text c="dimmed" size="sm">
            Status
          </Text>
          <Group mt={4}>
            <StatusBadge status={result.status} />
          </Group>
        </Paper>
        <Paper className="metric-card" p="md" withBorder>
          <Text c="dimmed" size="sm">
            Model used
          </Text>
          <Text className="report-breakable" fw={800} mt={4}>
            {providerLabel}
          </Text>
        </Paper>
        <Paper className="metric-card" p="md" withBorder>
          <Text c="dimmed" size="sm">
            Evidence
          </Text>
          <Text fw={800} mt={4}>
            {result.evidence?.commits?.length || 0} commits ·{" "}
            {result.evidence?.documentation?.length || 0} context items ·{" "}
            {result.evidence?.browser_screenshots?.length || 0} screenshots
          </Text>
        </Paper>
      </SimpleGrid>

      <SimpleGrid cols={{ base: 1, sm: 2 }}>
        <Paper className="metric-card" p="md" withBorder>
          <Text c="dimmed" size="sm">
            Model snapshot
          </Text>
          <Text className="report-breakable" fw={800} mt={4}>
            {effectiveModel
              ? `${effectiveModel.timeout_seconds}s · max ${effectiveModel.max_concurrent_agents ?? 1} concurrent agent${(effectiveModel.max_concurrent_agents ?? 1) === 1 ? "" : "s"} · ${effectiveModel.thinking ?? "default thinking"}`
              : "n/a"}
          </Text>
        </Paper>
        <Paper className="metric-card" p="md" withBorder>
          <Text c="dimmed" size="sm">
            Run options
          </Text>
          <Text fw={800} mt={4}>
            {result.request.screenshot_policy || "disabled"} screenshots
          </Text>
          {result.request.task_interface_url ? (
            <Text className="report-breakable" c="dimmed" size="sm">
              {result.request.task_interface_url}
            </Text>
          ) : null}
          {result.request.project_profile_snapshot_id ? (
            <Text className="report-breakable" c="dimmed" size="sm">
              {result.request.project_profile_snapshot_id}
            </Text>
          ) : null}
        </Paper>
      </SimpleGrid>

      <TokenUsagePanel error={tokenUsageError} summary={tokenUsage} />

      {screenshots.length ? (
        <Paper className="metric-card" p="md" withBorder>
          <Group justify="space-between">
            <Title order={3}>Screenshot evidence</Title>
            <Badge color="gray" variant="light">
              {screenshots.length} capture{screenshots.length === 1 ? "" : "s"}
            </Badge>
          </Group>
          <Stack gap="md" mt="sm">
            {screenshots.map((screenshot) => (
              <ScreenshotEvidenceCard
                artifacts={result.artifacts}
                key={screenshot.capture_id || `${screenshot.scenario}-${screenshot.path}`}
                runId={result.run_id}
                screenshot={screenshot}
              />
            ))}
          </Stack>
        </Paper>
      ) : null}

      <div>
        <Title order={3}>Validation findings</Title>
        <Stack gap="xs" mt="sm">
          {findings.length ? (
            findings.map((finding) => (
              <FindingItem
                finding={finding}
                key={`${finding.severity}-${finding.check}-${finding.message}`}
              />
            ))
          ) : (
            <Paper className="finding-item severity-ok" p="sm" withBorder>
              <Text fw={800} size="sm">
                pass
              </Text>
              <Text size="sm">No validation findings.</Text>
            </Paper>
          )}
          {visibleWarnings.map((warning) => (
            <Paper className="finding-item severity-warning" key={warning} p="sm" withBorder>
              <Text fw={800} size="sm">
                evidence warning
              </Text>
              <Text className="report-breakable" size="sm">{warning}</Text>
            </Paper>
          ))}
          {hiddenWarningCount > 0 ? (
            <Paper className="finding-item severity-info" p="sm" withBorder>
              <Text fw={800} size="sm">
                evidence warning
              </Text>
              <Text size="sm">{hiddenWarningCount} more warnings hidden.</Text>
            </Paper>
          ) : null}
        </Stack>
      </div>

      {result.evidence?.repositories?.length ? (
        <List c="dimmed" size="sm">
          {result.evidence.repositories.map((repository) => (
            <List.Item key={repository}>{repository}</List.Item>
          ))}
        </List>
      ) : null}
    </Stack>
  );
}

function ScreenshotEvidenceCard({
  artifacts,
  runId,
  screenshot
}: {
  artifacts: Record<string, string>;
  runId: string;
  screenshot: BrowserScreenshotEvidence;
}) {
  const links = screenshotArtifactLinks(runId, artifacts, screenshot);
  const viewport = screenshot.viewport || {};
  const errors = [
    ...(screenshot.console_errors || []),
    ...(screenshot.page_errors || []),
    ...(screenshot.failed_requests || [])
  ];
  const warnings = [
    ...(screenshot.validation_reasons || []),
    ...(screenshot.semantic_mismatches || []),
    ...(screenshot.vision_warnings || [])
  ];
  const crop = screenshot.crop;
  const masks = (screenshot.masks || []).map(
    (mask) => `${mask.reason}: ${mask.locator_kind}=${mask.locator}`
  );

  return (
    <Paper className="screenshot-evidence-card" p="md" withBorder>
      <SimpleGrid cols={{ base: 1, md: links.prepared ? 2 : 1 }}>
        {links.prepared ? (
          <a
            aria-label={`Open prepared screenshot for ${screenshot.scenario}`}
            className="screenshot-evidence-preview"
            href={links.prepared}
            rel="noreferrer"
            target="_blank"
          >
            <img
              alt={screenshot.alt_text || `Prepared capture: ${screenshot.scenario}`}
              src={links.prepared}
            />
          </a>
        ) : null}
        <Stack gap="xs">
          <Group justify="space-between" wrap="wrap">
            <div>
              <Text fw={800}>{screenshot.scenario}</Text>
              <Text className="report-breakable" c="dimmed" size="sm">
                {screenshot.title || screenshot.route || screenshot.url}
              </Text>
            </div>
            <Group gap="xs">
              <Badge
                color={screenshotStatusColor(screenshot.validation_status)}
                variant="light"
              >
                {screenshot.validation_status || "not validated"}
              </Badge>
              <Badge color={screenshot.publication_approved ? "teal" : "gray"} variant="outline">
                {screenshot.publication_approved ? "publication approved" : "internal only"}
              </Badge>
            </Group>
          </Group>

          <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="xs">
            <EvidenceValue label="Scenario ID" value={screenshot.scenario_id} />
            <EvidenceValue label="Plan item" value={screenshot.plan_item_id} />
            <EvidenceValue label="Change ID" value={screenshot.change_id} />
            <EvidenceValue label="Claim ID" value={screenshot.claim_id} />
          </SimpleGrid>

          <Text size="sm">
            <strong>Requested:</strong> {screenshot.requested_state || "n/a"}
          </Text>
          <Text size="sm">
            <strong>Observed:</strong> {screenshot.observed_state || screenshot.ui_state || "n/a"}
          </Text>
          <Text c="dimmed" size="xs">
            {screenshot.route || screenshot.url} · {viewport.width || "?"}×
            {viewport.height || "?"} · {screenshot.theme} · attempt {screenshot.attempts}
          </Text>

          <Group gap="sm">
            {links.prepared ? (
              <Anchor href={links.prepared} rel="noreferrer" size="sm" target="_blank">
                Prepared image
              </Anchor>
            ) : null}
            {links.raw ? (
              <Anchor href={links.raw} rel="noreferrer" size="sm" target="_blank">
                Raw audit image
              </Anchor>
            ) : null}
          </Group>
        </Stack>
      </SimpleGrid>

      <details className="screenshot-evidence-details">
        <summary>Validation, policy, and capture metadata</summary>
        <SimpleGrid cols={{ base: 1, sm: 2 }} mt="sm">
          <Stack gap={4}>
            <EvidenceList label="Matched" values={screenshot.matched_text} />
            <EvidenceList label="Missing" values={screenshot.missing_text} />
            <EvidenceList label="Rejected matches" values={screenshot.matched_rejected_text} />
            <EvidenceList label="Warnings" values={warnings} />
            <EvidenceList label="Browser errors" values={errors} />
          </Stack>
          <Stack gap={4}>
            <EvidenceValue label="Capture ID" value={screenshot.capture_id} />
            <EvidenceValue label="Image hash" value={screenshot.prepared_image_hash} />
            <EvidenceValue label="Raw hash" value={screenshot.raw_image_hash} />
            <EvidenceValue
              label="Prepared size"
              value={
                screenshot.image_width && screenshot.image_height
                  ? `${screenshot.image_width}×${screenshot.image_height}`
                  : null
              }
            />
            <EvidenceValue
              label="Crop"
              value={
                crop
                  ? `${crop.mode} · ${crop.x ?? 0},${crop.y ?? 0} · ${crop.width ?? "?"}×${crop.height ?? "?"}`
                  : null
              }
            />
            <EvidenceList label="Masks" values={masks} />
            <EvidenceValue label="Capture target" value={screenshot.capture_target} />
            <EvidenceValue label="DOM hash" value={screenshot.dom_hash} />
            <EvidenceValue label="ARIA hash" value={screenshot.aria_hash} />
            <EvidenceValue label="Browser" value={screenshot.browser_identity} />
            <EvidenceValue label="Build" value={screenshot.build_identity} />
            <EvidenceValue
              label="Policy"
              value={
                screenshot.policy_audit
                  ? `${screenshot.policy_audit.decision} · ${screenshot.policy_audit.permission} · ${screenshot.policy_audit.risk} · ${screenshot.policy_audit.resource_scope}`
                  : null
              }
            />
            <EvidenceValue label="Worker path" value={screenshot.path} />
          </Stack>
        </SimpleGrid>
      </details>
    </Paper>
  );
}

function EvidenceValue({ label, value }: { label: string; value?: string | null }) {
  return (
    <Text className="report-breakable" c="dimmed" size="xs">
      <strong>{label}:</strong> {value || "n/a"}
    </Text>
  );
}

function EvidenceList({ label, values }: { label: string; values?: string[] }) {
  return (
    <Text className="report-breakable" c="dimmed" size="xs">
      <strong>{label}:</strong> {values?.length ? values.join(", ") : "none"}
    </Text>
  );
}

function TokenUsagePanel({
  error,
  summary
}: {
  error: string | null;
  summary: RunTokenUsageSummary | null;
}) {
  if (error) {
    return (
      <Paper className="finding-item severity-warning" p="md" withBorder>
        <Text fw={800}>Token usage unavailable</Text>
        <Text size="sm">{error}</Text>
      </Paper>
    );
  }
  if (!summary || summary.calls === 0) {
    return (
      <Paper className="metric-card" p="md" withBorder>
        <Text c="dimmed" size="sm">
          Token usage
        </Text>
        <Text fw={800} mt={4}>
          No model usage recorded yet.
        </Text>
      </Paper>
    );
  }
  return (
    <Paper className="metric-card" p="md" withBorder>
      <Title order={3}>Token usage</Title>
      <SimpleGrid cols={{ base: 1, sm: 3 }} mt="sm">
        <div>
          <Text c="dimmed" size="sm">
            Total
          </Text>
          <Text fw={800}>{summary.total_tokens}</Text>
        </div>
        <div>
          <Text c="dimmed" size="sm">
            Calls
          </Text>
          <Text fw={800}>{summary.calls}</Text>
        </div>
        <div>
          <Text c="dimmed" size="sm">
            Estimated
          </Text>
          <Text fw={800}>{summary.estimated_tokens}</Text>
        </div>
      </SimpleGrid>
      <SimpleGrid cols={{ base: 1, sm: 2 }} mt="md">
        <TokenUsageBreakdown title="By role" items={summary.by_role || []} />
        <TokenUsageBreakdown title="By model" items={summary.by_model || []} />
        <TokenUsageBreakdown title="By provider" items={summary.by_provider || []} />
        <TokenUsageBreakdown title="By workflow task" items={summary.by_workflow_task || []} />
      </SimpleGrid>
      {summary.warnings?.length ? (
        <Stack gap={4} mt="md">
          {summary.warnings.slice(0, 4).map((warning) => (
            <Text c="yellow.8" key={warning} size="sm">
              {warning}
            </Text>
          ))}
        </Stack>
      ) : null}
    </Paper>
  );
}

function TokenUsageBreakdown({
  items,
  title
}: {
  items: NonNullable<RunTokenUsageSummary["by_role"]>;
  title: string;
}) {
  return (
    <div>
      <Text c="dimmed" size="sm">
        {title}
      </Text>
      <Stack gap={3} mt={4}>
        {items.length ? (
          items.slice(0, 5).map((item) => (
            <Group className="token-usage-row" justify="space-between" key={item.key} wrap="nowrap">
              <Text className="token-usage-key" size="sm">
                {item.key}
              </Text>
              <Text className="token-usage-value" fw={800} size="sm">
                {item.total_tokens}
              </Text>
            </Group>
          ))
        ) : (
          <Text c="dimmed" size="sm">
            n/a
          </Text>
        )}
      </Stack>
    </div>
  );
}

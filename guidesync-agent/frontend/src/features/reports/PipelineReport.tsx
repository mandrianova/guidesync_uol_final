import { Group, List, Paper, SimpleGrid, Stack, Text, Title } from "@mantine/core";

import { EmptyState } from "../../components/EmptyState";
import { StatusBadge } from "../../components/StatusBadge";
import { readableModelLabel } from "../../lib/modelProfiles";
import type { GuideSyncRunResult, ValidationFinding } from "../../types";

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
        <Text c="dimmed" size="xs">
          evidence: {finding.evidence_refs.join(", ")}
        </Text>
      ) : null}
      {finding.artifact_refs?.length ? (
        <Text c="dimmed" size="xs">
          artifacts: {finding.artifact_refs.join(", ")}
        </Text>
      ) : null}
    </Paper>
  );
}

interface PipelineReportProps {
  result: GuideSyncRunResult | null;
}

export function PipelineReport({ result }: PipelineReportProps) {
  if (!result) {
    return <EmptyState>Select a report to inspect pipeline health.</EmptyState>;
  }

  const findings = result.findings || [];
  const warnings = result.evidence?.warnings || [];
  const visibleWarnings = warnings.slice(0, 8);
  const hiddenWarningCount = warnings.length - visibleWarnings.length;
  const provider = result.provider_metadata;
  const effectiveModel = result.request.effective_model_configuration;
  const requestedModel = result.request.requested_model_settings;
  const screenshots = result.evidence?.browser_screenshots || [];
  const providerLabel = effectiveModel
    ? readableModelLabel(effectiveModel)
    : provider?.provider || provider?.model
      ? readableModelLabel({
          provider: provider.provider as "mock" | "pydantic_ai" | "local_http",
          model: provider.model,
          base_url: requestedModel?.base_url || null
        })
      : "n/a";

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
          <Text fw={800} mt={4}>
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
          <Text fw={800} mt={4}>
            {effectiveModel
              ? `${effectiveModel.timeout_seconds}s · ${effectiveModel.thinking ?? "default thinking"}`
              : "n/a"}
          </Text>
          {requestedModel?.metadata ? (
            <Text c="dimmed" size="sm">
              {Object.entries(requestedModel.metadata)
                .filter(([, value]) => value !== null && value !== "")
                .map(([key, value]) => `${key}: ${value}`)
                .join(" · ") || "No requested overrides"}
            </Text>
          ) : null}
        </Paper>
        <Paper className="metric-card" p="md" withBorder>
          <Text c="dimmed" size="sm">
            Run options
          </Text>
          <Text fw={800} mt={4}>
            {result.request.screenshot_policy || "disabled"} screenshots
          </Text>
          {result.request.task_interface_url ? (
            <Text c="dimmed" size="sm">
              {result.request.task_interface_url}
            </Text>
          ) : null}
          {result.request.project_profile_snapshot_id ? (
            <Text c="dimmed" size="sm">
              {result.request.project_profile_snapshot_id}
            </Text>
          ) : null}
        </Paper>
      </SimpleGrid>

      {screenshots.length ? (
        <Paper className="metric-card" p="md" withBorder>
          <Title order={3}>Screenshots</Title>
          <Stack gap="xs" mt="sm">
            {screenshots.map((screenshot) => (
              <Paper key={`${screenshot.scenario}-${screenshot.path}`} p="sm" withBorder>
                <Text fw={800}>{screenshot.scenario}</Text>
                <Text c="dimmed" size="sm">
                  {screenshot.title || screenshot.url}
                </Text>
                <Text size="sm">{screenshot.path}</Text>
                {screenshot.image_hash ? (
                  <Text c="dimmed" size="xs">
                    hash {screenshot.image_hash.slice(0, 12)}
                    {screenshot.blank ? " · blank" : ""}
                  </Text>
                ) : null}
                {screenshot.missing_text?.length ? (
                  <Text c="yellow.8" size="sm">
                    Missing: {screenshot.missing_text.join(", ")}
                  </Text>
                ) : null}
              </Paper>
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
              <Text size="sm">{warning}</Text>
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

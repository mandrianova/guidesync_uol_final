import { Group, List, Paper, SimpleGrid, Stack, Text, Title } from "@mantine/core";

import { EmptyState } from "../../components/EmptyState";
import { StatusBadge } from "../../components/StatusBadge";
import { readableModelName, readableProvider } from "../../lib/modelProfiles";
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
  const providerLabel =
    provider?.provider || provider?.model
      ? `${readableProvider({
          provider: provider.provider as "mock" | "pydantic_ai" | "local_http",
          model: provider.model,
          base_url: null
        })} · ${readableModelName(provider.model)}`
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

import { Button, Group, Paper, SimpleGrid, Stack, Text, Title } from "@mantine/core";
import { IconArrowLeft, IconRefresh } from "@tabler/icons-react";

import { ArtifactActions } from "../../components/ArtifactActions";
import { EmptyState } from "../../components/EmptyState";
import { PageHeader } from "../../components/PageHeader";
import { SectionPanel } from "../../components/SectionPanel";
import { StatusBadge } from "../../components/StatusBadge";
import { formatDateTime } from "../../lib/dates";
import { readableModelLabel } from "../../lib/modelProfiles";
import type { GuideSyncRunResult, RunSummary } from "../../types";
import { ChangeReport } from "./ChangeReport";
import { PipelineReport } from "./PipelineReport";

interface ReportsPageProps {
  loading: boolean;
  projectName: string;
  reports: RunSummary[];
  selectedRun: GuideSyncRunResult | null;
  onBackToList: () => void;
  onRefresh: () => void;
  onSelectRun: (runId: string) => void;
}

export function ReportsPage({
  loading,
  projectName,
  reports,
  selectedRun,
  onBackToList,
  onRefresh,
  onSelectRun
}: ReportsPageProps) {
  return (
    <Stack gap="lg">
      <PageHeader title={projectName ? `Reports · ${projectName}` : "Reports"} />

      {!selectedRun ? (
        <SectionPanel
          actions={
            <Button
              leftSection={<IconRefresh size={17} />}
              loading={loading}
              onClick={onRefresh}
              variant="light"
            >
              Refresh
            </Button>
          }
          description="Saved analysis runs for this project."
          title="Report history"
        >
          {!reports.length ? (
            <EmptyState>No saved reports for this project yet.</EmptyState>
          ) : (
            <Stack gap="xs">
              {reports.map((report) => {
                const provider = report.effective_model_configuration
                  ? readableModelLabel(report.effective_model_configuration)
                  : report.provider || report.model
                    ? readableModelLabel({
                        provider: (report.provider || "pydantic_ai") as "mock" | "pydantic_ai" | "local_http",
                        model: report.model || "",
                        base_url: null
                      })
                    : "n/a";
                return (
                  <Paper
                    className="report-row"
                    key={report.run_id}
                    p="md"
                    withBorder
                  >
                    <Group align="center" justify="space-between" wrap="nowrap">
                      <div>
                        <Text fw={800}>{report.title}</Text>
                        <Text c="dimmed" size="sm">
                          Created {formatDateTime(report.created_at)}
                        </Text>
                      </div>
                      <Stack align="flex-end" gap={3}>
                        <StatusBadge status={report.status} />
                        <Text c="dimmed" size="sm">
                          {provider} · {formatDateTime(report.updated_at)}
                        </Text>
                      </Stack>
                      <Group
                        gap="xs"
                        justify="flex-end"
                        wrap="wrap"
                      >
                        <Button onClick={() => onSelectRun(report.run_id)} size="sm" variant="light">
                          View
                        </Button>
                        <ArtifactActions artifacts={report.artifacts || {}} runId={report.run_id} />
                      </Group>
                    </Group>
                  </Paper>
                );
              })}
            </Stack>
          )}
        </SectionPanel>
      ) : (
        <SectionPanel
          actions={
            <Group>
              <Button leftSection={<IconArrowLeft size={17} />} onClick={onBackToList} variant="light">
                Back to reports
              </Button>
              <ArtifactActions artifacts={selectedRun.artifacts || {}} runId={selectedRun.run_id} />
            </Group>
          }
          description="Generated release notes draft for review."
          title={selectedRun.request?.report?.title || "Selected report"}
        >
          <SimpleGrid cols={{ base: 1, xl: 2 }} spacing="lg">
            <Stack gap="md">
              <Title order={3}>Analysis status</Title>
              <Text c="dimmed" size="sm">
                Run state, evidence coverage, and warnings.
              </Text>
              <PipelineReport result={selectedRun} />
            </Stack>
            <Stack gap="md">
              <Title order={3}>Release notes draft</Title>
              <Text c="dimmed" size="sm">
                Generated release notes draft for review.
              </Text>
              <ChangeReport result={selectedRun} />
            </Stack>
          </SimpleGrid>
        </SectionPanel>
      )}
    </Stack>
  );
}

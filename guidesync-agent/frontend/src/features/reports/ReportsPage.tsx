import { Button, Group, Paper, Stack, Text, Title } from "@mantine/core";
import { IconArrowLeft, IconPlayerStop, IconRefresh } from "@tabler/icons-react";

import { ArtifactActions } from "../../components/ArtifactActions";
import { EmptyState } from "../../components/EmptyState";
import { PageHeader } from "../../components/PageHeader";
import { SectionPanel } from "../../components/SectionPanel";
import { StatusBadge } from "../../components/StatusBadge";
import { terminalStatus } from "../../lib/branches";
import { formatDateTime } from "../../lib/dates";
import { readableModelLabel } from "../../lib/modelProfiles";
import type { GuideSyncRunResult, ProjectWorkflowTask, RunSummary } from "../../types";
import { ChangeReport } from "./ChangeReport";
import { PipelineReport } from "./PipelineReport";

interface ReportsPageProps {
  cancelling: boolean;
  loading: boolean;
  projectName: string;
  reports: RunSummary[];
  selectedRun: GuideSyncRunResult | null;
  workflowTasks: ProjectWorkflowTask[];
  onBackToList: () => void;
  onCancelRun: () => void;
  onRefresh: () => void;
  onSelectRun: (runId: string) => void;
}

export function ReportsPage({
  cancelling,
  loading,
  projectName,
  reports,
  selectedRun,
  workflowTasks,
  onBackToList,
  onCancelRun,
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
                        <ArtifactActions
                          artifacts={report.artifacts || {}}
                          runId={report.run_id}
                          showPublicationState
                        />
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
              {!terminalStatus(selectedRun.status) ? (
                <Button
                  color="red"
                  leftSection={<IconPlayerStop size={17} />}
                  loading={cancelling}
                  onClick={onCancelRun}
                  variant="light"
                >
                  Cancel analysis
                </Button>
              ) : null}
              <ArtifactActions
                artifacts={selectedRun.artifacts || {}}
                runId={selectedRun.run_id}
                showPublicationState
              />
            </Group>
          }
          description="Generated release notes draft for review."
          title={selectedRun.request?.report?.title || "Selected report"}
        >
          <Stack className="report-detail-layout" gap="xl">
            <section className="report-detail-section">
              <Title order={3}>Release notes draft</Title>
              <Text c="dimmed" size="sm">
                Generated release notes draft for review.
              </Text>
              <ChangeReport result={selectedRun} />
            </section>
            <section className="report-detail-section report-detail-section-secondary">
              <Title order={3}>Analysis status</Title>
              <Text c="dimmed" size="sm">
                Run state, evidence coverage, and warnings.
              </Text>
              {workflowTasks.length ? (
                <Stack gap="xs" mt="sm">
                  {workflowTasks.map((task) => (
                    <Paper key={task.id} p="sm" withBorder>
                      <Group align="flex-start" justify="space-between">
                        <div>
                          <Text fw={700}>{humanize(task.kind)}</Text>
                          <Text c="dimmed" size="sm">
                            {task.progress.message}
                          </Text>
                          {task.last_heartbeat_at ? (
                            <Text c="dimmed" size="xs">
                              Active {formatDateTime(task.last_heartbeat_at)}
                            </Text>
                          ) : null}
                        </div>
                        <Stack align="flex-end" gap={3}>
                          <StatusBadge status={task.status} />
                          <Text c="dimmed" size="xs">
                            {humanize(task.progress.stage)}
                          </Text>
                        </Stack>
                      </Group>
                    </Paper>
                  ))}
                </Stack>
              ) : null}
              <PipelineReport result={selectedRun} />
            </section>
          </Stack>
        </SectionPanel>
      )}
    </Stack>
  );
}

function humanize(value: string): string {
  return value.replaceAll("_", " ").replace(/^./, (letter) => letter.toUpperCase());
}

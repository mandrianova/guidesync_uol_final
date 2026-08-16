import { Button, Group, Paper, Stack, Text, Title } from "@mantine/core";
import { IconArrowLeft, IconPlayerStop, IconRefresh } from "@tabler/icons-react";

import { ArtifactActions } from "../../components/ArtifactActions";
import { EmptyState } from "../../components/EmptyState";
import { PageHeader } from "../../components/PageHeader";
import { SectionPanel } from "../../components/SectionPanel";
import { StatusBadge } from "../../components/StatusBadge";
import { retryableReportStatus, terminalStatus } from "../../lib/branches";
import { formatDateTime } from "../../lib/dates";
import { readableModelLabel } from "../../lib/modelProfiles";
import { describeReportChangeScope } from "../../lib/reportScope";
import { workflowTaskResultSummary } from "../../lib/workflow";
import type { GuideSyncRunResult, ProjectWorkflowTask, RunSummary } from "../../types";
import { ChangeReport } from "./ChangeReport";
import { PipelineReport } from "./PipelineReport";

interface ReportsPageProps {
  cancellingRunId: string | null;
  loading: boolean;
  projectName: string;
  reports: RunSummary[];
  selectedRun: GuideSyncRunResult | null;
  workflowTasks: ProjectWorkflowTask[];
  onBackToList: () => void;
  onCancelRun: (runId: string) => void;
  onRefresh: () => void;
  onRetryRun: (runId: string) => void;
  onRetryScreenshots: (runId: string) => void;
  onRetrySynthesis: (runId: string) => void;
  onSelectRun: (runId: string) => void;
  onVideoAction: (runId: string, regenerate: boolean) => void;
  retryingRunId: string | null;
  stageActionRunId: string | null;
  videoActionRunId: string | null;
}

export function ReportsPage({
  cancellingRunId,
  loading,
  projectName,
  reports,
  selectedRun,
  workflowTasks,
  onBackToList,
  onCancelRun,
  onRefresh,
  onRetryRun,
  onRetryScreenshots,
  onRetrySynthesis,
  onSelectRun,
  onVideoAction,
  retryingRunId,
  stageActionRunId,
  videoActionRunId
}: ReportsPageProps) {
  const selectedSummary = selectedRun
    ? reports.find((report) => report.run_id === selectedRun.run_id)
    : undefined;
  const selectedPublicationAvailable = Boolean(selectedSummary?.publication_available);
  const selectedScope = describeReportChangeScope(selectedSummary?.change_scope);

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
          description="Report runs for this project."
          title="Report history"
        >
          {!reports.length ? (
            <EmptyState>No reports for this project yet.</EmptyState>
          ) : (
            <Stack gap="xs">
              {reports.map((report) => {
                const changeScope = describeReportChangeScope(report.change_scope);
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
                        {changeScope ? (
                          <Text c="dimmed" className="report-breakable" size="sm">
                            {changeScope.label}: {changeScope.value}
                          </Text>
                        ) : null}
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
                        {retryableReportStatus(report.status) ? (
                          <Button
                            loading={retryingRunId === report.run_id}
                            onClick={() => onRetryRun(report.run_id)}
                            size="sm"
                            variant="light"
                          >
                            Retry
                          </Button>
                        ) : null}
                        {!terminalStatus(report.status) ? (
                          <Button
                            color="red"
                            leftSection={<IconPlayerStop size={16} />}
                            loading={cancellingRunId === report.run_id}
                            onClick={() => onCancelRun(report.run_id)}
                            size="sm"
                            variant="light"
                          >
                            Stop
                          </Button>
                        ) : null}
                        <Button onClick={() => onSelectRun(report.run_id)} size="sm" variant="light">
                          View
                        </Button>
                        <ArtifactActions
                          artifacts={report.artifacts || {}}
                          publicationAvailable={report.publication_available}
                          runId={report.run_id}
                          showPublicationState
                          videoPresentation={report.video_presentation}
                          videoActionLoading={videoActionRunId === report.run_id}
                          onVideoAction={(regenerate) => onVideoAction(report.run_id, regenerate)}
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
                  loading={cancellingRunId === selectedRun.run_id}
                  onClick={() => onCancelRun(selectedRun.run_id)}
                  variant="light"
                >
                  Stop report
                </Button>
              ) : null}
              {retryableReportStatus(selectedRun.status) ? (
                <Button
                  loading={retryingRunId === selectedRun.run_id}
                  onClick={() => onRetryRun(selectedRun.run_id)}
                  variant="light"
                >
                  Retry report
                </Button>
              ) : null}
              {selectedRun.status === "failed" && !selectedRun.update ? (
                <Button
                  loading={stageActionRunId === selectedRun.run_id}
                  onClick={() => onRetrySynthesis(selectedRun.run_id)}
                  variant="light"
                >
                  Retry final stage
                </Button>
              ) : null}
              {selectedRun.status === "completed"
              && Boolean(selectedRun.request.task_interface_url)
              && Boolean(selectedRun.update?.screenshot_requests?.length) ? (
                <Button
                  loading={stageActionRunId === selectedRun.run_id}
                  onClick={() => onRetryScreenshots(selectedRun.run_id)}
                  variant="light"
                >
                  Retry screenshots
                </Button>
              ) : null}
              <ArtifactActions
                artifacts={selectedRun.artifacts || {}}
                publicationAvailable={selectedPublicationAvailable}
                runId={selectedRun.run_id}
                showPublicationState
                videoPresentation={selectedRun.video_presentation}
                videoActionLoading={videoActionRunId === selectedRun.run_id}
                onVideoAction={(regenerate) => onVideoAction(selectedRun.run_id, regenerate)}
              />
            </Group>
          }
          description="Generated release notes draft for review."
          title={selectedRun.request?.report?.title || "Selected report"}
        >
          <Stack className="report-detail-layout" gap="xl">
            {selectedScope ? (
              <Paper className="report-scope" p="sm" withBorder>
                <Text c="dimmed" size="xs">
                  {selectedScope.label}
                </Text>
                <Text fw={700}>{selectedScope.value}</Text>
              </Paper>
            ) : null}
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
              {selectedRun.video_presentation?.status !== "disabled" ? (
                <Paper mt="sm" p="sm" withBorder>
                  <Group align="flex-start" justify="space-between">
                    <div>
                      <Text fw={700}>Video presentation</Text>
                      <Text c="dimmed" size="sm">
                        {selectedRun.video_presentation.tts_backend || "TTS pending"}
                        {selectedRun.video_presentation.tts_model
                          ? ` · ${selectedRun.video_presentation.tts_model}`
                          : ""}
                        {selectedRun.video_presentation.duration_seconds
                          ? ` · ${selectedRun.video_presentation.duration_seconds.toFixed(1)}s`
                          : ""}
                      </Text>
                      {selectedRun.video_presentation.error_message ? (
                        <Text c="red" size="sm">
                          {selectedRun.video_presentation.error_message}
                        </Text>
                      ) : null}
                    </div>
                    <StatusBadge status={selectedRun.video_presentation.status} />
                  </Group>
                </Paper>
              ) : null}
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
                          {task.error_message ? (
                            <Text c="red" className="report-breakable" size="sm">
                              {task.error_message}
                            </Text>
                          ) : null}
                          {workflowTaskResultSummary(task) ? (
                            <Text className="report-breakable" mt={4} size="sm">
                              {workflowTaskResultSummary(task)}
                            </Text>
                          ) : null}
                          {task.warnings.map((warning) => (
                            <Text
                              c="orange.8"
                              className="report-breakable"
                              key={warning}
                              size="sm"
                            >
                              {warning}
                            </Text>
                          ))}
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

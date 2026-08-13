import { Badge, Button, Group, Paper, SimpleGrid, Stack, Text } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconPlayerStop, IconRefresh, IconSitemap } from "@tabler/icons-react";
import { useState } from "react";

import { api } from "../../api/client";
import { EmptyState } from "../../components/EmptyState";
import { MarkdownBlock } from "../../components/MarkdownBlock";
import { PageHeader } from "../../components/PageHeader";
import { SectionPanel } from "../../components/SectionPanel";
import { StatusBadge } from "../../components/StatusBadge";
import { formatDateTime } from "../../lib/dates";
import type {
  ProjectConfig,
  ProjectPipelineState,
  ProjectProfileSnapshot,
  ProjectWorkflowTask
} from "../../types";

interface ProjectProfilePageProps {
  activeTask: ProjectWorkflowTask | null;
  loading: boolean;
  profile: ProjectProfileSnapshot | null;
  project: ProjectConfig;
  state: ProjectPipelineState | null;
  onRefresh: () => Promise<void>;
}

export function ProjectProfilePage({
  activeTask,
  loading,
  profile,
  project,
  state,
  onRefresh
}: ProjectProfilePageProps) {
  const [queueing, setQueueing] = useState(false);
  const [stopping, setStopping] = useState(false);

  const rebuild = async () => {
    if (!project.id) {
      return;
    }
    setQueueing(true);
    try {
      await api.enqueueProfileRebuild(project.id);
      await onRefresh();
      notifications.show({
        color: "teal",
        message: "Profile rebuild was added to the project workflow queue.",
        title: "Project profile"
      });
    } catch (error) {
      notifications.show({
        color: "red",
        message: error instanceof Error ? error.message : "Could not queue profile rebuild",
        title: "Profile rebuild failed"
      });
    } finally {
      setQueueing(false);
    }
  };

  const stop = async () => {
    if (!project.id || !activeTask) {
      return;
    }
    setStopping(true);
    try {
      await api.cancelWorkflowTask(project.id, activeTask.id);
      await onRefresh();
      notifications.show({
        color: "teal",
        message: "Profile generation was stopped.",
        title: "Project profile"
      });
    } catch (error) {
      notifications.show({
        color: "red",
        message: error instanceof Error ? error.message : "Could not stop profile generation",
        title: "Stop failed"
      });
    } finally {
      setStopping(false);
    }
  };

  return (
    <Stack gap="lg">
      <PageHeader title={project.id ? `Project profile · ${project.name}` : "Project profile"} />
      <SectionPanel
        actions={<StatusBadge status={profile?.status || state?.blocked_reason || "No profile"} />}
        description="Review the agent-generated project brief and documentation categories."
        title="Project profile"
      >
        <Stack gap="md">
          <Group>
            <Button
              disabled={!project.id || Boolean(activeTask)}
              leftSection={<IconSitemap size={18} />}
              loading={queueing}
              onClick={rebuild}
              variant="light"
            >
              Rebuild profile
            </Button>
            {activeTask ? (
              <Button
                color="red"
                leftSection={<IconPlayerStop size={17} />}
                loading={stopping}
                onClick={stop}
                variant="light"
              >
                Stop profile
              </Button>
            ) : null}
            <Button
              disabled={!project.id}
              leftSection={<IconRefresh size={17} />}
              loading={loading}
              onClick={() => void onRefresh()}
              variant="subtle"
            >
              Refresh
            </Button>
          </Group>

          {!project.id ? (
            <EmptyState>Save the project before building a project profile.</EmptyState>
          ) : !profile ? (
            <EmptyState>No project profile has been created yet.</EmptyState>
          ) : (
            <Stack gap="md">
              <Paper className="row-card" p="md" withBorder>
                <Stack gap="xs">
                  <Group justify="space-between">
                    <Text fw={850}>{profile.id}</Text>
                    <StatusBadge status={profile.status} />
                  </Group>
                  <Text>{profile.summary || "No summary recorded."}</Text>
                  <Text c="dimmed" size="sm">
                    Version {profile.version} · {formatDateTime(profile.completed_at)}
                  </Text>
                </Stack>
              </Paper>

              <TextPanel
                title="Project description"
                value={profile.project_description || "None recorded."}
              />

              <SimpleGrid cols={{ base: 1, md: 2 }}>
                <TextListPanel title="Project structure" values={profile.project_structure} />
                <TextListPanel title="Architecture" values={profile.architecture} />
                <ValuePanel title="Core concepts" values={profile.core_concepts} />
                <ValuePanel title="Documentation categories" values={profile.taxonomy.categories} />
              </SimpleGrid>

              {profile.warnings.length ? <ValuePanel title="Warnings" values={profile.warnings} /> : null}
              {profile.error_message ? (
                <ValuePanel title="Errors" values={[profile.error_message]} />
              ) : null}
              {profile.validation_findings.length ? (
                <ValuePanel
                  title="Validation findings"
                  values={profile.validation_findings.map(
                    (finding) => `${finding.severity} · ${finding.check}: ${finding.message}`
                  )}
                />
              ) : null}
            </Stack>
          )}

          <Paper className="row-card" p="md" withBorder>
            <Stack gap="xs">
              <Text fw={850}>Workflow queue</Text>
              {state?.tasks.length ? (
                <>
                  {state.tasks.slice(0, 8).map((task) => (
                    <Group key={task.id} justify="space-between">
                      <Text size="sm">
                        {task.sequence}. {task.kind.replaceAll("_", " ")}
                      </Text>
                      <StatusBadge status={task.status} />
                    </Group>
                  ))}
                </>
              ) : (
                <Text c="dimmed" size="sm">
                  No queued project workflow tasks.
                </Text>
              )}
            </Stack>
          </Paper>
        </Stack>
      </SectionPanel>
    </Stack>
  );
}

function TextPanel({ title, value }: { title: string; value: string }) {
  const empty = value === "None recorded.";
  return (
    <Paper className="row-card" p="md" withBorder>
      <Stack gap={6}>
        <Text fw={850}>{title}</Text>
        {empty ? (
          <Text c="dimmed" size="sm">
            {value}
          </Text>
        ) : (
          <MarkdownBlock markdown={value} variant="plain" />
        )}
      </Stack>
    </Paper>
  );
}

function TextListPanel({ title, values }: { title: string; values: string[] }) {
  const markdown = values.filter((value) => value.trim()).join("\n\n");
  return (
    <Paper className="row-card" p="md" withBorder>
      <Stack gap={6}>
        <Text fw={850}>{title}</Text>
        {markdown ? (
          <MarkdownBlock markdown={markdown} variant="plain" />
        ) : (
          <Text c="dimmed" size="sm">
            None recorded.
          </Text>
        )}
      </Stack>
    </Paper>
  );
}

function ValuePanel({ title, values }: { title: string; values: string[] }) {
  return (
    <Paper className="row-card" p="md" withBorder>
      <Stack gap={6}>
        <Text fw={850}>{title}</Text>
        {values.length ? (
          <Group gap={6}>
            {values.map((value, index) => (
              <Badge key={`${value}:${index}`} variant="light">
                {value}
              </Badge>
            ))}
          </Group>
        ) : (
          <Text c="dimmed" size="sm">
            None recorded.
          </Text>
        )}
      </Stack>
    </Paper>
  );
}

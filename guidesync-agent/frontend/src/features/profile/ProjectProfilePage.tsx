import { Badge, Button, Group, Paper, SimpleGrid, Stack, Text } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconRefresh, IconSitemap } from "@tabler/icons-react";
import { useState } from "react";

import { api } from "../../api/client";
import { EmptyState } from "../../components/EmptyState";
import { PageHeader } from "../../components/PageHeader";
import { SectionPanel } from "../../components/SectionPanel";
import { StatusBadge } from "../../components/StatusBadge";
import { formatDateTime } from "../../lib/dates";
import type { ProjectConfig, ProjectPipelineState, ProjectProfileSnapshot } from "../../types";

interface ProjectProfilePageProps {
  loading: boolean;
  profile: ProjectProfileSnapshot | null;
  project: ProjectConfig;
  state: ProjectPipelineState | null;
  onRefresh: () => Promise<void>;
}

export function ProjectProfilePage({
  loading,
  profile,
  project,
  state,
  onRefresh
}: ProjectProfilePageProps) {
  const [queueing, setQueueing] = useState(false);

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

  return (
    <Stack gap="lg">
      <PageHeader title={project.id ? `Project profile · ${project.name}` : "Project profile"} />
      <SectionPanel
        actions={<StatusBadge status={profile?.status || state?.blocked_reason || "No profile"} />}
        description="Review the agent-generated project profile and controlled taxonomy."
        title="Project profile"
      >
        <Stack gap="md">
          <Group>
            <Button
              disabled={!project.id}
              leftSection={<IconSitemap size={18} />}
              loading={queueing}
              onClick={rebuild}
              variant="light"
            >
              Rebuild profile
            </Button>
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
                  <Group gap={6}>
                    <Badge variant="light">
                      {String(profile.model_metadata.provider || "unknown provider")}
                    </Badge>
                    <Badge variant="light">
                      {String(profile.model_metadata.model || "unknown model")}
                    </Badge>
                    <Badge variant="outline">
                      Confidence {profile.taxonomy.confidence.toFixed(2)}
                    </Badge>
                  </Group>
                </Stack>
              </Paper>

              <SimpleGrid cols={{ base: 1, md: 2 }}>
                <TextPanel
                  title="Project description"
                  value={profile.project_description || "None recorded."}
                />
                <TextPanel
                  title="Agent context"
                  value={profile.agent_context || "None recorded."}
                />
              </SimpleGrid>

              <SimpleGrid cols={{ base: 1, md: 2 }}>
                <TextListPanel title="Project structure" values={profile.project_structure} />
                <TextListPanel title="Architecture" values={profile.architecture} />
                <ValuePanel title="Core concepts" values={profile.core_concepts} />
                <ValuePanel title="Workflows" values={profile.workflows} />
                <ValuePanel title="Categories" values={profile.taxonomy.categories} />
                <ValuePanel title="Components" values={profile.taxonomy.components} />
                <ValuePanel title="Documentation areas" values={profile.taxonomy.documentation_areas} />
                <ValuePanel title="Domain terms" values={profile.taxonomy.domain_terms} />
              </SimpleGrid>

              <Paper className="row-card" p="md" withBorder>
                <Stack gap="xs">
                  <Text fw={850}>Source refs</Text>
                  {profile.source_refs.map((source, index) => (
                    <Group key={`${source.repository_id}:${index}`} justify="space-between">
                      <Text size="sm">{source.repository_name}</Text>
                      <Text c="dimmed" size="sm">
                        {source.commit_sha ? source.commit_sha.slice(0, 8) : "no commit"}
                      </Text>
                    </Group>
                  ))}
                </Stack>
              </Paper>

              <ValuePanel title="Warnings" values={profile.warnings} />
              <ValuePanel
                title="Errors"
                values={profile.error_message ? [profile.error_message] : []}
              />
              <ValuePanel
                title="Validation findings"
                values={profile.validation_findings.map(
                  (finding) => `${finding.severity} · ${finding.check}: ${finding.message}`
                )}
              />
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
  return (
    <Paper className="row-card" p="md" withBorder>
      <Stack gap={6}>
        <Text fw={850}>{title}</Text>
        <Text
          c={value === "None recorded." ? "dimmed" : undefined}
          size="sm"
          style={{ whiteSpace: "pre-wrap" }}
        >
          {value}
        </Text>
      </Stack>
    </Paper>
  );
}

function TextListPanel({ title, values }: { title: string; values: string[] }) {
  return (
    <Paper className="row-card" p="md" withBorder>
      <Stack gap={6}>
        <Text fw={850}>{title}</Text>
        {values.length ? (
          <Stack gap={4}>
            {values.map((value, index) => (
              <Text key={`${value}:${index}`} size="sm">
                {value}
              </Text>
            ))}
          </Stack>
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

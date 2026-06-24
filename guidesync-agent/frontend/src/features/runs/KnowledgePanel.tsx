import { Button, Group, NumberInput, Paper, Stack, Text } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconDatabase, IconRefresh } from "@tabler/icons-react";
import { useState } from "react";

import { api } from "../../api/client";
import { EmptyState } from "../../components/EmptyState";
import { SectionPanel } from "../../components/SectionPanel";
import { StatusBadge } from "../../components/StatusBadge";
import { formatDateTime } from "../../lib/dates";
import type { KnowledgeIndexRun } from "../../types";

interface KnowledgePanelProps {
  projectId: string | null;
  runs: KnowledgeIndexRun[];
  onRefresh: () => Promise<void>;
}

export function KnowledgePanel({ projectId, runs, onRefresh }: KnowledgePanelProps) {
  const [maxFiles, setMaxFiles] = useState(500);
  const [building, setBuilding] = useState(false);
  const latest = runs[0];
  const status = !projectId ? "Save project first" : building ? "Indexing" : latest?.status || "Not indexed";

  const buildKnowledge = async () => {
    if (!projectId) {
      return;
    }
    setBuilding(true);
    try {
      await api.createKnowledgeRun(projectId, maxFiles);
      await onRefresh();
      notifications.show({
        color: "teal",
        message: "Knowledge index run created",
        title: "Knowledge base"
      });
    } catch (error) {
      notifications.show({
        color: "red",
        message: error instanceof Error ? error.message : "Could not build knowledge base",
        title: "Knowledge base failed"
      });
    } finally {
      setBuilding(false);
    }
  };

  return (
    <SectionPanel
      actions={<StatusBadge status={status} />}
      description="Index the saved project repositories and product context before analysis."
      title="Knowledge base"
    >
      <Stack gap="md">
        <Group align="end">
          <NumberInput
            allowDecimal={false}
            clampBehavior="strict"
            disabled={!projectId}
            label="Max files"
            max={10000}
            min={1}
            onChange={(value) => setMaxFiles(Number(value) || 500)}
            value={maxFiles}
            w={180}
          />
          <Button
            disabled={!projectId}
            leftSection={<IconDatabase size={18} />}
            loading={building}
            onClick={buildKnowledge}
            variant="light"
          >
            Build knowledge base
          </Button>
          <Button
            disabled={!projectId}
            leftSection={<IconRefresh size={17} />}
            onClick={onRefresh}
            variant="subtle"
          >
            Refresh
          </Button>
        </Group>

        {!projectId ? (
          <EmptyState>Save the project before building its knowledge base.</EmptyState>
        ) : !runs.length ? (
          <EmptyState>No knowledge index runs for this project yet.</EmptyState>
        ) : (
          <Stack gap="xs">
            {runs.slice(0, 5).map((run) => {
              const summary = run.summary;
              const warnings = summary.warnings || [];
              return (
                <Paper className="row-card" key={run.id} p="md" withBorder>
                  <Group align="flex-start" justify="space-between">
                    <div>
                      <Text fw={800}>{run.id}</Text>
                      <Text c="dimmed" size="sm">
                        {formatDateTime(run.completed_at) || "Running"}
                      </Text>
                    </div>
                    <StatusBadge status={run.status} />
                    <Stack gap={2} ta="right">
                      <Text size="sm">
                        {summary.repositories} repos · {summary.files} files
                      </Text>
                      <Text c="dimmed" size="sm">
                        {summary.nodes} nodes · {summary.edges} edges · {summary.chunks} chunks
                      </Text>
                      {warnings.length ? (
                        <Text c="yellow.8" size="sm">
                          {warnings.length} warning{warnings.length === 1 ? "" : "s"} · {warnings[0]}
                        </Text>
                      ) : null}
                    </Stack>
                  </Group>
                </Paper>
              );
            })}
          </Stack>
        )}
      </Stack>
    </SectionPanel>
  );
}

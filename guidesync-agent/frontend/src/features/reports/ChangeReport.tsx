import { Group, Paper, Stack, Text, Title } from "@mantine/core";
import { useEffect, useState } from "react";

import { artifactUrl, requestText } from "../../api/client";
import { ArtifactActions } from "../../components/ArtifactActions";
import { EmptyState } from "../../components/EmptyState";
import { MarkdownBlock } from "../../components/MarkdownBlock";
import type { GuideSyncRunResult } from "../../types";

interface ChangeReportProps {
  result: GuideSyncRunResult | null;
}

export function ChangeReport({ result }: ChangeReportProps) {
  const [artifactMarkdown, setArtifactMarkdown] = useState<string | null>(null);
  const [artifactError, setArtifactError] = useState<string | null>(null);

  useEffect(() => {
    let ignore = false;
    setArtifactMarkdown(null);
    setArtifactError(null);

    if (!result?.artifacts["report.md"]) {
      return () => {
        ignore = true;
      };
    }

    requestText(artifactUrl(result.run_id, "report.md"))
      .then((markdown) => {
        if (!ignore) {
          setArtifactMarkdown(markdown);
        }
      })
      .catch((error) => {
        if (!ignore) {
          setArtifactError(error instanceof Error ? error.message : "Could not load markdown artifact");
        }
      });

    return () => {
      ignore = true;
    };
  }, [result]);

  if (!result) {
    return <EmptyState>Select a report to view the generated release notes.</EmptyState>;
  }

  const update = result.update;

  if (!update) {
    return <EmptyState>No release notes were generated.</EmptyState>;
  }

  return (
    <Stack gap="md">
      <Group justify="space-between">
        <div>
          <Title order={3}>{update.title}</Title>
          <Text c="dimmed" mt={4}>
            {update.summary}
          </Text>
        </div>
        <ArtifactActions artifacts={result.artifacts || {}} runId={result.run_id} />
      </Group>

      <Paper className="metric-card" p="md" withBorder>
        <Text c="dimmed" size="sm">
          User-facing change
        </Text>
        <Text fw={800} mt={4}>
          {update.user_facing_change}
        </Text>
      </Paper>

      {artifactError ? (
        <EmptyState>Could not load markdown artifact: {artifactError}</EmptyState>
      ) : (
        <MarkdownBlock markdown={artifactMarkdown || update.proposed_update_markdown} />
      )}

      <div>
        <Title order={3}>Evidence used</Title>
        <Stack gap="xs" mt="sm">
          {update.evidence_used.length ? (
            update.evidence_used.map((reference) => (
              <Paper
                className="row-card"
                key={`${reference.source}-${reference.detail}`}
                p="sm"
                withBorder
              >
                <Text fw={800} size="sm">
                  {reference.source}
                </Text>
                <Text size="sm">{reference.detail}</Text>
                <Text c="dimmed" size="xs">
                  {reference.relevance}
                </Text>
              </Paper>
            ))
          ) : (
            <EmptyState>No evidence references.</EmptyState>
          )}
        </Stack>
      </div>
    </Stack>
  );
}

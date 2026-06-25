import { Code, Group, List, Paper, SimpleGrid, Stack, Text, Title } from "@mantine/core";
import { useEffect, useState } from "react";

import { artifactUrl, requestText } from "../../api/client";
import { ArtifactActions } from "../../components/ArtifactActions";
import { EmptyState } from "../../components/EmptyState";
import { MarkdownBlock } from "../../components/MarkdownBlock";
import type { GuideSyncRunResult } from "../../types";

interface FileSummaryArtifact {
  summaries?: Array<{
    path: string;
    status: string;
    technical_summary: string;
    product_impact: string;
    docs_to_search?: string[];
    needs_main_agent_review?: boolean;
  }>;
}

interface RetrievedDocsArtifact {
  results?: Array<{
    node?: { path?: string | null; name?: string; summary?: string };
    chunk?: { heading?: string | null; path?: string | null } | null;
    matched_text?: string;
  }>;
}

interface ProjectProfileArtifact {
  summary?: string;
  architecture?: string[];
  workflows?: string[];
  key_terms?: string[];
}

interface InspectionArtifacts {
  patch: string | null;
  fileSummaries: FileSummaryArtifact | null;
  retrievedDocs: RetrievedDocsArtifact | null;
  projectProfile: ProjectProfileArtifact | null;
}

interface ChangeReportProps {
  result: GuideSyncRunResult | null;
}

export function ChangeReport({ result }: ChangeReportProps) {
  const [artifactMarkdown, setArtifactMarkdown] = useState<string | null>(null);
  const [inspectionArtifacts, setInspectionArtifacts] = useState<InspectionArtifacts>({
    patch: null,
    fileSummaries: null,
    retrievedDocs: null,
    projectProfile: null
  });
  const [artifactError, setArtifactError] = useState<string | null>(null);

  useEffect(() => {
    let ignore = false;
    setArtifactMarkdown(null);
    setInspectionArtifacts({
      patch: null,
      fileSummaries: null,
      retrievedDocs: null,
      projectProfile: null
    });
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

    loadInspectionArtifacts(result)
      .then((artifacts) => {
        if (!ignore) {
          setInspectionArtifacts(artifacts);
        }
      })
      .catch(() => {
        if (!ignore) {
          setInspectionArtifacts({
            patch: null,
            fileSummaries: null,
            retrievedDocs: null,
            projectProfile: null
          });
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
  const edit = update?.documentation_edit;

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

      {edit ? (
        <Paper className="metric-card" p="md" withBorder>
          <Title order={3}>Documentation edit</Title>
          <SimpleGrid cols={{ base: 1, sm: 2 }} mt="sm">
            <div>
              <Text c="dimmed" size="sm">
                Target
              </Text>
              <Text fw={800}>{edit.target_path}</Text>
            </div>
            <div>
              <Text c="dimmed" size="sm">
                Commit
              </Text>
              <Text fw={800}>{edit.commit_sha || "patch only"}</Text>
            </div>
          </SimpleGrid>
          <List mt="sm" spacing={4}>
            {edit.changed_docs.map((path) => (
              <List.Item key={path}>{path}</List.Item>
            ))}
          </List>
          {edit.knowledge_index_run_id ? (
            <Text c="dimmed" mt="xs" size="sm">
              Knowledge index run: {edit.knowledge_index_run_id}
            </Text>
          ) : null}
        </Paper>
      ) : null}

      {inspectionArtifacts.patch ? (
        <Paper className="metric-card" p="md" withBorder>
          <Title order={3}>Documentation diff</Title>
          <Code block mt="sm">
            {inspectionArtifacts.patch}
          </Code>
        </Paper>
      ) : null}

      {inspectionArtifacts.fileSummaries?.summaries?.length ? (
        <Paper className="metric-card" p="md" withBorder>
          <Title order={3}>Per-file summaries</Title>
          <Stack gap="xs" mt="sm">
            {inspectionArtifacts.fileSummaries.summaries.map((summary) => (
              <Paper key={`${summary.path}-${summary.status}`} p="sm" withBorder>
                <Text fw={800}>
                  {summary.status} · {summary.path}
                </Text>
                <Text size="sm">{summary.technical_summary}</Text>
                <Text c="dimmed" size="sm">
                  {summary.product_impact}
                </Text>
                {summary.docs_to_search?.length ? (
                  <Text c="dimmed" size="xs">
                    docs search: {summary.docs_to_search.join(", ")}
                  </Text>
                ) : null}
              </Paper>
            ))}
          </Stack>
        </Paper>
      ) : null}

      {inspectionArtifacts.retrievedDocs?.results?.length ? (
        <Paper className="metric-card" p="md" withBorder>
          <Title order={3}>Knowledge references</Title>
          <Stack gap="xs" mt="sm">
            {inspectionArtifacts.retrievedDocs.results.map((reference, index) => (
              <Paper key={`${reference.node?.path || "doc"}-${index}`} p="sm" withBorder>
                <Text fw={800}>{reference.node?.path || reference.node?.name || "Document"}</Text>
                <Text c="dimmed" size="sm">
                  {reference.chunk?.heading || reference.node?.summary || "Matched document"}
                </Text>
                {reference.matched_text ? <Text size="sm">{reference.matched_text}</Text> : null}
              </Paper>
            ))}
          </Stack>
        </Paper>
      ) : null}

      {inspectionArtifacts.projectProfile ? (
        <Paper className="metric-card" p="md" withBorder>
          <Title order={3}>Project profile snapshot</Title>
          <Text mt="sm">{inspectionArtifacts.projectProfile.summary}</Text>
          {inspectionArtifacts.projectProfile.key_terms?.length ? (
            <Text c="dimmed" mt="xs" size="sm">
              Terms: {inspectionArtifacts.projectProfile.key_terms.join(", ")}
            </Text>
          ) : null}
        </Paper>
      ) : null}

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

async function loadInspectionArtifacts(result: GuideSyncRunResult): Promise<InspectionArtifacts> {
  const [patch, fileSummaries, retrievedDocs, projectProfile] = await Promise.all([
    loadOptionalText(result, "documentation.patch"),
    loadOptionalJson<FileSummaryArtifact>(result, "file-summaries.json"),
    loadOptionalJson<RetrievedDocsArtifact>(result, "retrieved-docs.json"),
    loadOptionalJson<ProjectProfileArtifact>(result, "project-profile.json")
  ]);
  return { patch, fileSummaries, retrievedDocs, projectProfile };
}

async function loadOptionalText(
  result: GuideSyncRunResult,
  filename: string
): Promise<string | null> {
  if (!result.artifacts[filename]) {
    return null;
  }
  try {
    return await requestText(artifactUrl(result.run_id, filename));
  } catch {
    return null;
  }
}

async function loadOptionalJson<T>(
  result: GuideSyncRunResult,
  filename: string
): Promise<T | null> {
  const text = await loadOptionalText(result, filename);
  if (!text) {
    return null;
  }
  try {
    return JSON.parse(text) as T;
  } catch {
    return null;
  }
}

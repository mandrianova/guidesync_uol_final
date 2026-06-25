import { Badge, Button, Group, NumberInput, Paper, Stack, Text, TextInput } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconDatabase, IconRefresh, IconSearch } from "@tabler/icons-react";
import { useEffect, useState } from "react";

import { api } from "../../api/client";
import { EmptyState } from "../../components/EmptyState";
import { SectionPanel } from "../../components/SectionPanel";
import { StatusBadge } from "../../components/StatusBadge";
import { formatDateTime } from "../../lib/dates";
import type {
  KnowledgeDocumentRefs,
  KnowledgeIndexRun,
  KnowledgeSearchResult,
  KnowledgeTag
} from "../../types";

interface KnowledgePanelProps {
  projectId: string | null;
  runs: KnowledgeIndexRun[];
  onRefresh: () => Promise<void>;
}

export function KnowledgePanel({ projectId, runs, onRefresh }: KnowledgePanelProps) {
  const [maxFiles, setMaxFiles] = useState(500);
  const [building, setBuilding] = useState(false);
  const [metadataLoading, setMetadataLoading] = useState(false);
  const [documentRefs, setDocumentRefs] = useState<KnowledgeDocumentRefs>({
    documents: [],
    sections: []
  });
  const [tags, setTags] = useState<KnowledgeTag[]>([]);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<KnowledgeSearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const latest = runs[0];
  const status = !projectId ? "Save project first" : building ? "Indexing" : latest?.status || "Not indexed";

  useEffect(() => {
    void refreshKnowledgeMetadata();
  }, [projectId, latest?.id]);

  const refreshKnowledgeMetadata = async () => {
    if (!projectId) {
      setDocumentRefs({ documents: [], sections: [] });
      setTags([]);
      setSearchResults([]);
      return;
    }
    setMetadataLoading(true);
    try {
      const [nextRefs, nextTags] = await Promise.all([
        api.listKnowledgeDocuments(projectId),
        api.listKnowledgeTags(projectId)
      ]);
      setDocumentRefs(nextRefs);
      setTags(nextTags);
    } catch {
      setDocumentRefs({ documents: [], sections: [] });
      setTags([]);
    } finally {
      setMetadataLoading(false);
    }
  };

  const buildKnowledge = async () => {
    if (!projectId) {
      return;
    }
    setBuilding(true);
    try {
      await api.createKnowledgeRun(projectId, maxFiles);
      await onRefresh();
      await refreshKnowledgeMetadata();
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

  const searchKnowledge = async () => {
    if (!projectId || !searchQuery.trim()) {
      setSearchResults([]);
      return;
    }
    setSearching(true);
    try {
      const results = await api.searchKnowledge(projectId, searchQuery.trim(), 8);
      setSearchResults(results);
    } catch (error) {
      notifications.show({
        color: "red",
        message: error instanceof Error ? error.message : "Could not search knowledge base",
        title: "Knowledge search failed"
      });
    } finally {
      setSearching(false);
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
            loading={metadataLoading}
            onClick={() => {
              void onRefresh();
              void refreshKnowledgeMetadata();
            }}
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
                        {summary.repositories} repos · {summary.documents} docs · {summary.sections} sections
                      </Text>
                      <Text c="dimmed" size="sm">
                        {summary.indexed_commit_sha
                          ? `Commit ${shortSha(summary.indexed_commit_sha)}`
                          : "No commit snapshot"}
                      </Text>
                      {summary.changed_documentation_files.length ? (
                        <Text c="dimmed" size="sm">
                          Changed {summary.changed_documentation_files.join(", ")}
                        </Text>
                      ) : null}
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

        {projectId && latest ? (
          <Stack gap="md">
            {tags.length ? (
              <Group gap={6}>
                {tags.slice(0, 16).map((tag) => (
                  <Badge key={`${tag.category}:${tag.value}`} variant={tag.category === "category" ? "light" : "outline"}>
                    {tag.value} {tag.count}
                  </Badge>
                ))}
              </Group>
            ) : null}

            <Group align="end">
              <TextInput
                leftSection={<IconSearch size={16} />}
                onChange={(event) => setSearchQuery(event.currentTarget.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") {
                    void searchKnowledge();
                  }
                }}
                placeholder="Search docs refs"
                value={searchQuery}
                w={{ base: "100%", sm: 360 }}
              />
              <Button
                disabled={!searchQuery.trim()}
                loading={searching}
                onClick={() => void searchKnowledge()}
                variant="light"
              >
                Search
              </Button>
            </Group>

            {searchResults.length ? (
              <Stack gap="xs">
                {searchResults.map((result) => (
                  <Paper className="row-card" key={`${result.node.id}:${result.chunk?.id || "node"}`} p="md" withBorder>
                    <Group align="flex-start" justify="space-between">
                      <div>
                        <Text fw={800}>
                          {result.chunk?.heading || result.node.name}
                        </Text>
                        <Text c="dimmed" size="sm">
                          {result.node.path || result.chunk?.path} {lineRange(result.node.start_line, result.node.end_line)}
                        </Text>
                        <Text size="sm">{result.matched_text}</Text>
                      </div>
                      <Text c="dimmed" size="sm">
                        {result.score.toFixed(1)}
                      </Text>
                    </Group>
                  </Paper>
                ))}
              </Stack>
            ) : null}

            <Stack gap="xs">
              {documentRefs.documents.slice(0, 12).map((document) => {
                const sections = documentRefs.sections.filter(
                  (section) => section.document_id === document.id
                );
                return (
                  <Paper className="row-card" key={document.id} p="md" withBorder>
                    <Stack gap="xs">
                      <Group align="flex-start" justify="space-between">
                        <div>
                          <Text fw={800}>{document.path}</Text>
                          <Text c="dimmed" size="sm">
                            {document.section_count} sections · {document.source_commit ? shortSha(document.source_commit) : "no commit"}
                          </Text>
                        </div>
                        <Group gap={6}>
                          {document.tags.slice(0, 4).map((tag) => (
                            <Badge key={tag} variant="light">
                              {tag}
                            </Badge>
                          ))}
                        </Group>
                      </Group>
                      {sections.slice(0, 4).map((section) => (
                        <Group gap="xs" key={section.id}>
                          <Text fw={700} size="sm">
                            {section.heading}
                          </Text>
                          <Text c="dimmed" size="sm">
                            {lineRange(section.start_line, section.end_line)}
                          </Text>
                        </Group>
                      ))}
                    </Stack>
                  </Paper>
                );
              })}
            </Stack>
          </Stack>
        ) : null}
      </Stack>
    </SectionPanel>
  );
}

function shortSha(value: string): string {
  return value.includes(",") ? value : value.slice(0, 8);
}

function lineRange(start: number | null, end: number | null): string {
  if (!start) {
    return "";
  }
  if (!end || end === start) {
    return `line ${start}`;
  }
  return `lines ${start}-${end}`;
}

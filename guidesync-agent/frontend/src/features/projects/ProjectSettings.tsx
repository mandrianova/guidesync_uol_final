import {
  ActionIcon,
  Box,
  Button,
  Divider,
  Group,
  Select,
  SimpleGrid,
  Stack,
  Text,
  TextInput,
  Textarea,
  Tooltip
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconDeviceFloppy, IconPlus, IconRefresh, IconTrash } from "@tabler/icons-react";
import { useState } from "react";

import { api } from "../../api/client";
import { PageHeader } from "../../components/PageHeader";
import { SectionPanel } from "../../components/SectionPanel";
import { StatusBadge } from "../../components/StatusBadge";
import {
  projectPayload,
  repositoryCacheStatusLabel,
  uid
} from "../../lib/projects";
import type { Audience, ProjectConfig, ProjectRepository } from "../../types";

interface ProjectSettingsProps {
  project: ProjectConfig;
  projectStatus: string;
  saving: boolean;
  onChange: (project: ProjectConfig, status?: string) => void;
  onSave: () => void;
}

const AUDIENCE_OPTIONS: Array<{ value: Audience; label: string }> = [
  { value: "end_users", label: "End users" },
  { value: "developers", label: "Developers" },
  { value: "business_analysts", label: "Business analysts" }
];

function pathsToText(paths: string[]): string {
  return paths.join(", ");
}

function textToPaths(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function blankRepository(index: number, analysisPaths: string[]): ProjectRepository {
  return {
    id: uid("repo"),
    name: `repository-${index}`,
    url: "",
    default_branch: "main",
    analysis_paths: analysisPaths,
    credential_ref: null,
    cache_status: "not_synced",
    local_path: null,
    current_commit: null,
    cache_warnings: []
  };
}

export function ProjectSettings({
  project,
  projectStatus,
  saving,
  onChange,
  onSave
}: ProjectSettingsProps) {
  const [syncingRepositoryId, setSyncingRepositoryId] = useState<string | null>(null);
  const status = project.id ? "Unsaved" : "Draft";
  const payload = projectPayload(project);
  const canSave = Boolean(payload.name && payload.repositories.length);
  const knowledgeRepositoryId =
    project.knowledge_base_repository_id || project.repositories[0]?.id || null;
  const knowledgeRepository = project.repositories.find(
    (repository) => repository.id === knowledgeRepositoryId
  );
  const displayedAnalysisPaths = project.analysis_paths.length
    ? project.analysis_paths
    : project.repositories[0]?.analysis_paths || [];
  const knowledgeRepositoryOptions = project.repositories.map((repository) => ({
    value: repository.id,
    label: repository.name || repository.url || repository.id
  }));

  const updateProject = (patch: Partial<ProjectConfig>) => {
    onChange({ ...project, ...patch }, status);
  };

  const updateRepository = (index: number, patch: Partial<ProjectRepository>) => {
    onChange(
      {
        ...project,
        repositories: project.repositories.map((repository, currentIndex) =>
          currentIndex === index ? { ...repository, ...patch } : repository
        )
      },
      status
    );
  };

  const updateAnalysisPaths = (analysisPaths: string[]) => {
    onChange(
      {
        ...project,
        analysis_paths: analysisPaths,
        repositories: project.repositories.map((repository) => ({
          ...repository,
          analysis_paths: analysisPaths
        }))
      },
      status
    );
  };

  const addRepository = () => {
    const repository = blankRepository(project.repositories.length + 1, project.analysis_paths);
    onChange(
      {
        ...project,
        knowledge_base_repository_id: project.knowledge_base_repository_id || repository.id,
        repositories: [...project.repositories, repository]
      },
      status
    );
  };

  const removeRepository = (index: number) => {
    if (project.repositories.length <= 1) {
      onChange(project, "Keep at least one repository");
      return;
    }
    const removed = project.repositories[index];
    const repositories = project.repositories.filter((_, currentIndex) => currentIndex !== index);
    onChange(
      {
        ...project,
        knowledge_base_repository_id:
          removed?.id === project.knowledge_base_repository_id
            ? repositories[0]?.id || null
            : project.knowledge_base_repository_id,
        repositories
      },
      status
    );
  };

  const syncRepository = async (repository: ProjectRepository) => {
    if (!project.id) {
      onChange(project, "Save project first");
      return;
    }
    setSyncingRepositoryId(repository.id);
    try {
      const synced = await api.syncRepository(project.id, repository.id);
      onChange(
        {
          ...project,
          repositories: project.repositories.map((item) =>
            item.id === synced.id ? synced : item
          )
        },
        synced.cache_status === "ready"
          ? "Synced"
          : synced.cache_status === "syncing"
            ? "Sync queued"
            : "Sync failed"
      );
      if (synced.cache_status === "syncing") {
        const finalStatus = await waitForRepositoryStatus(project.id, repository.id);
        onChange(
          {
            ...project,
            repositories: project.repositories.map((item) =>
              item.id === finalStatus.id ? finalStatus : item
            )
          },
          finalStatus.cache_status === "ready"
            ? "Synced"
            : finalStatus.cache_status === "syncing"
              ? "Sync queued"
              : "Sync failed"
        );
      }
    } catch (error) {
      notifications.show({
        color: "red",
        message: error instanceof Error ? error.message : "Could not sync repository",
        title: "Repository sync failed"
      });
    } finally {
      setSyncingRepositoryId(null);
    }
  };

  return (
    <Stack gap="lg">
      <PageHeader title={project.id ? `Project settings · ${project.name}` : "Project settings"} />
      <SectionPanel
        actions={<StatusBadge status={projectStatus} />}
        description="Configure audience, repository sources, and documentation rules."
        title="Project settings"
      >
        <Stack gap="md">
          <SimpleGrid cols={{ base: 1, md: 3 }}>
            <TextInput
              label="Project name"
              onChange={(event) => updateProject({ name: event.currentTarget.value })}
              value={project.name}
            />
            <TextInput
              label="Description"
              onChange={(event) => updateProject({ description: event.currentTarget.value })}
              value={project.description || ""}
            />
            <Select
              allowDeselect={false}
              data={AUDIENCE_OPTIONS}
              label="Audience"
              onChange={(value) => value && updateProject({ audience: value as Audience })}
              value={project.audience}
            />
          </SimpleGrid>

          <TextInput
            description="Used as the default for optional release-report screenshots. Each run can override it."
            label="Product UI URL"
            onChange={(event) =>
              updateProject({ task_interface_url: event.currentTarget.value || null })
            }
            placeholder="https://product.example.com/"
            value={project.task_interface_url || ""}
          />

          <Textarea
            autosize
            label="Documentation instructions"
            minRows={4}
            onChange={(event) =>
              updateProject({ documentation_instructions: event.currentTarget.value })
            }
            value={project.documentation_instructions}
          />

          <Divider />

          <Group justify="space-between">
            <div>
              <Text fw={800}>Repositories</Text>
              <Text c="dimmed" size="sm">
                Clone URL, default branch, and local cache state.
              </Text>
            </div>
            <Button leftSection={<IconPlus size={17} />} onClick={addRepository} variant="light">
              Add repository
            </Button>
          </Group>

          <Stack gap="md">
            {project.repositories.map((repository, index) => (
              <Box className="repository-editor" key={repository.id}>
                <Stack gap="sm">
                  <Group align="flex-start" justify="space-between">
                    <div>
                      <Text fw={800}>Repository {index + 1}</Text>
                      <Text c="dimmed" size="sm">
                        {repository.url || "No clone URL set"}
                      </Text>
                    </div>
                    <Group gap="xs">
                      <StatusBadge status={repositoryCacheStatusLabel(repository)} />
                      <Tooltip label="Sync repository cache">
                        <ActionIcon
                          aria-label="Sync repository cache"
                          loading={syncingRepositoryId === repository.id}
                          onClick={() => void syncRepository(repository)}
                          variant="subtle"
                        >
                          <IconRefresh size={18} />
                        </ActionIcon>
                      </Tooltip>
                      <Tooltip label="Remove repository">
                        <ActionIcon
                          aria-label="Remove repository"
                          color="red"
                          onClick={() => removeRepository(index)}
                          variant="subtle"
                        >
                          <IconTrash size={18} />
                        </ActionIcon>
                      </Tooltip>
                    </Group>
                  </Group>

                  <SimpleGrid cols={{ base: 1, md: 2 }}>
                    <TextInput
                      label="Name"
                      onChange={(event) =>
                        updateRepository(index, { name: event.currentTarget.value })
                      }
                      value={repository.name}
                    />
                    <TextInput
                      label="Default branch"
                      onChange={(event) =>
                        updateRepository(index, { default_branch: event.currentTarget.value })
                      }
                      value={repository.default_branch || "main"}
                    />
                  </SimpleGrid>
                  <TextInput
                    label="Clone URL"
                    onChange={(event) => updateRepository(index, { url: event.currentTarget.value })}
                    value={repository.url}
                  />
                  <Group gap="xs">
                    <Text c="dimmed" size="sm">
                      Local checkout:
                    </Text>
                    <Text size="sm">{repository.local_path || "not created"}</Text>
                    {repository.current_commit ? (
                      <Text c="dimmed" size="sm">
                        {repository.current_commit}
                      </Text>
                    ) : null}
                  </Group>
                </Stack>
              </Box>
            ))}
          </Stack>

          <Divider />

          <SimpleGrid cols={{ base: 1, md: 2 }}>
            <TextInput
              label="Analysis paths"
              onChange={(event) => updateAnalysisPaths(textToPaths(event.currentTarget.value))}
              placeholder="docs/, src/package/"
              value={pathsToText(displayedAnalysisPaths)}
            />
            <TextInput
              label="Credential reference"
              onChange={(event) =>
                updateProject({ credential_ref: event.currentTarget.value || null })
              }
              value={project.credential_ref || ""}
            />
          </SimpleGrid>

          <Divider />

          <div>
            <Text fw={800}>Knowledge base</Text>
            <Text c="dimmed" size="sm">
              Documentation repository, ref, and path.
            </Text>
          </div>
          <SimpleGrid cols={{ base: 1, md: 3 }}>
            <Select
              allowDeselect={false}
              data={knowledgeRepositoryOptions}
              label="Repository"
              onChange={(value) => updateProject({ knowledge_base_repository_id: value })}
              value={knowledgeRepositoryId}
            />
            <TextInput
              label="Ref"
              onChange={(event) =>
                updateProject({ knowledge_base_ref: event.currentTarget.value || null })
              }
              value={project.knowledge_base_ref || knowledgeRepository?.default_branch || ""}
            />
            <TextInput
              label="Knowledge base path"
              onChange={(event) => updateProject({ knowledge_base_path: event.currentTarget.value })}
              value={project.knowledge_base_path ?? "docs/"}
            />
          </SimpleGrid>
          <Group gap="xs">
            <Text c="dimmed" size="sm">
              Repository cache:
            </Text>
            {knowledgeRepository ? (
              <StatusBadge status={repositoryCacheStatusLabel(knowledgeRepository)} />
            ) : (
              <StatusBadge status="Not synced" />
            )}
          </Group>

          <Button
            disabled={!canSave}
            leftSection={<IconDeviceFloppy size={18} />}
            loading={saving}
            onClick={onSave}
          >
            Save project
          </Button>
        </Stack>
      </SectionPanel>
    </Stack>
  );
}

async function waitForRepositoryStatus(
  projectId: string,
  repositoryId: string
): Promise<ProjectRepository> {
  let current = await api.getRepositoryStatus(projectId, repositoryId);
  for (let attempt = 0; attempt < 10 && current.cache_status === "syncing"; attempt += 1) {
    await delay(1000);
    current = await api.getRepositoryStatus(projectId, repositoryId);
  }
  return current;
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

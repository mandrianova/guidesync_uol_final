import {
  ActionIcon,
  Button,
  Divider,
  Group,
  SimpleGrid,
  Stack,
  Text,
  TextInput,
  Textarea,
  Tooltip
} from "@mantine/core";
import { IconDeviceFloppy, IconPlus, IconTrash } from "@tabler/icons-react";

import { PageHeader } from "../../components/PageHeader";
import { SectionPanel } from "../../components/SectionPanel";
import { StatusBadge } from "../../components/StatusBadge";
import { projectPayload, uid } from "../../lib/projects";
import type { ProjectConfig, ProjectRepository } from "../../types";

interface ProjectSettingsProps {
  project: ProjectConfig;
  projectStatus: string;
  saving: boolean;
  onChange: (project: ProjectConfig, status?: string) => void;
  onSave: () => void;
}

function pathsToText(paths: string[]): string {
  return paths.join(", ");
}

function textToPaths(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

export function ProjectSettings({
  project,
  projectStatus,
  saving,
  onChange,
  onSave
}: ProjectSettingsProps) {
  const status = project.id ? "Unsaved" : "Draft";

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

  const addRepository = () => {
    const nextIndex = project.repositories.length + 1;
    onChange(
      {
        ...project,
        repositories: [
          ...project.repositories,
          {
            id: uid("repo"),
            name: `repository-${nextIndex}`,
            url: "",
            default_branch: "main",
            paths: []
          }
        ]
      },
      status
    );
  };

  const removeRepository = (index: number) => {
    if (project.repositories.length <= 1) {
      onChange(project, "Keep at least one repository");
      return;
    }
    onChange(
      {
        ...project,
        repositories: project.repositories.filter((_, currentIndex) => currentIndex !== index)
      },
      status
    );
  };

  const updateDocumentation = (content: string) => {
    const firstDocument = project.documentation[0] || {
      id: "doc-primary",
      name: "product-context",
      description: "Editable product context stored in the database.",
      content: ""
    };
    onChange(
      {
        ...project,
        documentation: [{ ...firstDocument, content }]
      },
      status
    );
  };

  const payload = projectPayload(project);
  const canSave = Boolean(payload.name && payload.repositories.length);

  return (
    <Stack gap="lg">
      <PageHeader title={project.id ? `Project settings · ${project.name}` : "Project settings"} />
      <SectionPanel
        actions={<StatusBadge status={projectStatus} />}
        description="Add repositories and product context for this project."
        title="Project settings"
      >
        <Stack gap="md">
          <SimpleGrid cols={{ base: 1, md: 2 }}>
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
          </SimpleGrid>

          <Divider />

          <Group justify="space-between">
            <div>
              <Text fw={800}>Repositories</Text>
              <Text c="dimmed" size="sm">
                Use public GitHub repositories for now.
              </Text>
            </div>
            <Button leftSection={<IconPlus size={17} />} onClick={addRepository} variant="light">
              Add repository
            </Button>
          </Group>

          <Stack gap="sm">
            {project.repositories.map((repository, index) => (
              <SectionPanel
                actions={
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
                }
                className="nested-panel"
                description={repository.url || "Public GitHub URL"}
                key={repository.id}
                title={`Repository ${index + 1}`}
              >
                <Stack gap="sm">
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
                    label="GitHub URL"
                    onChange={(event) => updateRepository(index, { url: event.currentTarget.value })}
                    value={repository.url}
                  />
                  <TextInput
                    label="Path filters"
                    onChange={(event) =>
                      updateRepository(index, { paths: textToPaths(event.currentTarget.value) })
                    }
                    placeholder="Optional: docs/, src/package/"
                    value={pathsToText(repository.paths)}
                  />
                </Stack>
              </SectionPanel>
            ))}
          </Stack>

          <Textarea
            autosize
            label="Product context"
            minRows={8}
            onChange={(event) => updateDocumentation(event.currentTarget.value)}
            value={project.documentation[0]?.content || ""}
          />

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

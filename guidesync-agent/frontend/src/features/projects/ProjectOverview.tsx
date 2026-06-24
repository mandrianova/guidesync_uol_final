import { Button, Group, Paper, SimpleGrid, Stack, Text, Title } from "@mantine/core";
import { IconEdit, IconFileText, IconPlayerPlay } from "@tabler/icons-react";

import { EmptyState } from "../../components/EmptyState";
import { PageHeader } from "../../components/PageHeader";
import { SectionPanel } from "../../components/SectionPanel";
import { repositoryCountLabel } from "../../lib/projects";
import type { PageId, ProjectConfig } from "../../types";

interface ProjectOverviewProps {
  currentProjectId: string | null;
  projects: ProjectConfig[];
  onOpenProject: (projectId: string, page: PageId) => void;
  onNavigate: (page: PageId) => void;
}

export function ProjectOverview({
  currentProjectId,
  projects,
  onOpenProject,
  onNavigate
}: ProjectOverviewProps) {
  return (
    <Stack gap="lg">
      <PageHeader title="Projects" />
      <SectionPanel
        actions={
          <Button leftSection={<IconEdit size={17} />} onClick={() => onNavigate("settings")} variant="light">
            Edit selected project
          </Button>
        }
        description="Select a project, then run an analysis or review generated reports."
        title="Saved projects"
      >
        {!projects.length ? (
          <EmptyState>Create a project to start tracking repository changes.</EmptyState>
        ) : (
          <SimpleGrid cols={{ base: 1, sm: 2, xl: 3 }} spacing="md">
            {projects.map((project) => (
              <Paper
                className={project.id === currentProjectId ? "project-card active" : "project-card"}
                key={project.id || project.name}
                p="md"
                withBorder
              >
                <Stack gap="md" h="100%" justify="space-between">
                  <div>
                    <Title order={3}>{project.name}</Title>
                    <Text c="dimmed" mt={6} size="sm">
                      {project.description || "No description added yet."}
                    </Text>
                  </div>

                  <Group gap="xs">
                    <Text className="metric-pill">{repositoryCountLabel(project.repositories.length)}</Text>
                    <Text className="metric-pill">
                      {project.documentation.length} context items
                    </Text>
                  </Group>

                  <Group gap="xs">
                    <Button
                      disabled={!project.id}
                      leftSection={<IconPlayerPlay size={16} />}
                      onClick={() => project.id && onOpenProject(project.id, "run")}
                      size="sm"
                    >
                      Draft notes
                    </Button>
                    <Button
                      disabled={!project.id}
                      leftSection={<IconFileText size={16} />}
                      onClick={() => project.id && onOpenProject(project.id, "reports")}
                      size="sm"
                      variant="light"
                    >
                      Reports
                    </Button>
                    <Button
                      disabled={!project.id}
                      leftSection={<IconEdit size={16} />}
                      onClick={() => project.id && onOpenProject(project.id, "settings")}
                      size="sm"
                      variant="subtle"
                    >
                      Edit
                    </Button>
                  </Group>
                </Stack>
              </Paper>
            ))}
          </SimpleGrid>
        )}
      </SectionPanel>
    </Stack>
  );
}

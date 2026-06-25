import { useEffect, useMemo, useState } from "react";
import { Button, Group, Paper, SimpleGrid, Stack, Text, Title } from "@mantine/core";
import {
  IconDatabase,
  IconEdit,
  IconFileText,
  IconPlayerPlay,
  IconRefresh,
  IconSitemap
} from "@tabler/icons-react";

import { EmptyState } from "../../components/EmptyState";
import { PageHeader } from "../../components/PageHeader";
import { SectionPanel } from "../../components/SectionPanel";
import { api } from "../../api/client";
import { audienceLabel, profileStatusLabel, repositoryCountLabel } from "../../lib/projects";
import type { PageId, ProjectConfig, ProjectProfileSnapshot } from "../../types";

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
  const [profiles, setProfiles] = useState<Record<string, ProjectProfileSnapshot | null>>({});
  const [rebuildingProfiles, setRebuildingProfiles] = useState<Set<string>>(new Set());
  const projectIds = useMemo(
    () => projects.map((project) => project.id).filter((id): id is string => Boolean(id)),
    [projects]
  );
  const projectIdsKey = projectIds.join("|");

  useEffect(() => {
    let cancelled = false;
    async function loadProfiles() {
      const loadedProfiles = await Promise.all(
        projectIds.map(async (projectId) => {
          try {
            return [projectId, await api.getProjectProfile(projectId)] as const;
          } catch {
            return [projectId, null] as const;
          }
        })
      );
      if (!cancelled) {
        setProfiles(Object.fromEntries(loadedProfiles));
      }
    }

    void loadProfiles();
    return () => {
      cancelled = true;
    };
  }, [projectIdsKey]);

  async function rebuildProfile(projectId: string) {
    setRebuildingProfiles((current) => new Set(current).add(projectId));
    try {
      const profile = await api.rebuildProjectProfile(projectId);
      setProfiles((current) => ({ ...current, [projectId]: profile }));
    } finally {
      setRebuildingProfiles((current) => {
        const next = new Set(current);
        next.delete(projectId);
        return next;
      });
    }
  }

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
            {projects.map((project) => {
              const profile = project.id ? profiles[project.id] : null;
              return (
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
                      <Text className="metric-pill">
                        {repositoryCountLabel(project.repositories.length)}
                      </Text>
                      <Text className="metric-pill">
                        {audienceLabel(project.audience)}
                      </Text>
                      <Text className="metric-pill">
                        {project.knowledge_base_path || "docs/"}
                      </Text>
                      <Text className="metric-pill">
                        {project.analysis_paths.length} analysis paths
                      </Text>
                    </Group>

                    <Stack gap={4}>
                      <Group gap="xs">
                        <IconSitemap size={16} />
                        <Text fw={600} size="sm">
                          {profile
                            ? `v${profile.version} ${profileStatusLabel(profile.status)}`
                            : "Profile not built"}
                        </Text>
                      </Group>
                      {profile?.summary ? (
                        <Text c="dimmed" lineClamp={2} size="sm">
                          {profile.summary}
                        </Text>
                      ) : null}
                      {profile?.uncertainty_notes.length ? (
                        <Text c="dimmed" lineClamp={1} size="xs">
                          {profile.uncertainty_notes[0]}
                        </Text>
                      ) : null}
                    </Stack>

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
                        leftSection={<IconDatabase size={16} />}
                        onClick={() => project.id && onOpenProject(project.id, "knowledge")}
                        size="sm"
                        variant="light"
                      >
                        Knowledge
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
                        leftSection={<IconRefresh size={16} />}
                        loading={Boolean(project.id && rebuildingProfiles.has(project.id))}
                        onClick={() => project.id && void rebuildProfile(project.id)}
                        size="sm"
                        variant="light"
                      >
                        Profile
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
              );
            })}
          </SimpleGrid>
        )}
      </SectionPanel>
    </Stack>
  );
}

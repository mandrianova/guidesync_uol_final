import {
  AppShell,
  Burger,
  Button,
  Group,
  Menu,
  NavLink,
  ScrollArea,
  Stack,
  Text,
  TextInput,
  ThemeIcon,
  Tooltip,
  Title
} from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import {
  IconBook2,
  IconBrain,
  IconChevronDown,
  IconDatabase,
  IconFileText,
  IconFlask,
  IconLayoutDashboard,
  IconPlayerPlay,
  IconPlus,
  IconSearch,
  IconSitemap,
  IconSettings,
  IconSparkles
} from "@tabler/icons-react";
import { type ReactNode, useEffect, useMemo, useRef, useState } from "react";

import { readableModelName, readableProvider } from "../lib/modelProfiles";
import {
  filterProjects,
  readableRepositoryLabel,
  repositoryCountLabel
} from "../lib/projects";
import type { ModelSettings, PageId, ProjectConfig } from "../types";

const navItems: Array<{ page: PageId; label: string; icon: typeof IconSettings }> = [
  { page: "settings", label: "Project settings", icon: IconSettings },
  { page: "profile", label: "Project profile", icon: IconSitemap },
  { page: "knowledge", label: "Knowledge base", icon: IconDatabase },
  { page: "evaluation", label: "Evaluation", icon: IconFlask },
  { page: "run", label: "Run analysis", icon: IconPlayerPlay },
  { page: "reports", label: "Reports", icon: IconFileText }
];

interface WorkspaceShellProps {
  children: ReactNode;
  currentPage: PageId;
  currentProject: ProjectConfig;
  defaultModel: ModelSettings | null;
  projects: ProjectConfig[];
  onNavigate: (page: PageId) => void;
  onNewProject: () => void;
  onSelectProject: (projectId: string) => void;
}

export function WorkspaceShell({
  children,
  currentPage,
  currentProject,
  defaultModel,
  projects,
  onNavigate,
  onNewProject,
  onSelectProject
}: WorkspaceShellProps) {
  const [opened, { toggle, close }] = useDisclosure(false);
  const [projectMenuOpened, setProjectMenuOpened] = useState(false);
  const [projectFilter, setProjectFilter] = useState("");
  const selectedProjectItem = useRef<HTMLButtonElement>(null);
  const visibleProjects = useMemo(
    () => filterProjects(projects, projectFilter),
    [projectFilter, projects]
  );

  useEffect(() => {
    if (!projectMenuOpened || projectFilter) {
      return;
    }
    const frame = window.requestAnimationFrame(() => {
      selectedProjectItem.current?.scrollIntoView({ block: "nearest" });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [projectFilter, projectMenuOpened]);

  const modelLabel = defaultModel
    ? `${readableProvider(defaultModel)} · ${readableModelName(defaultModel.model)}`
    : "No model profile selected";

  return (
    <AppShell
      navbar={{ width: 304, breakpoint: "md", collapsed: { mobile: !opened } }}
      padding="lg"
    >
      <AppShell.Navbar className="workspace-rail" p="md">
        <ScrollArea flex={1}>
          <Stack gap="lg">
            <Group align="flex-start" gap="sm" wrap="nowrap">
              <ThemeIcon color="teal" radius="md" size={42} variant="light">
                <IconSparkles size={22} />
              </ThemeIcon>
              <div>
                <Text className="rail-eyebrow" size="xs">
                  GuideSync
                </Text>
                <Title c="white" order={2}>
                  Release notes workspace
                </Title>
                <Text c="blue.1" mt={8} size="sm">
                  Track product changes and prepare reviewable release notes.
                </Text>
              </div>
            </Group>

            <Stack className="rail-section" gap="sm">
              <Text c="blue.1" fw={750} size="sm">
                Project
              </Text>
              <Group gap="xs" wrap="nowrap">
                <Menu
                  onChange={(nextOpened) => {
                    setProjectMenuOpened(nextOpened);
                    if (!nextOpened) {
                      setProjectFilter("");
                    }
                  }}
                  opened={projectMenuOpened}
                  position="bottom-start"
                  width={272}
                >
                  <Menu.Target>
                    <Button
                      color="gray"
                      disabled={!projects.length}
                      fullWidth
                      justify="space-between"
                      onKeyDown={(event) => {
                        if (
                          !projectMenuOpened &&
                          (event.key === "Enter" || event.key === " ")
                        ) {
                          event.preventDefault();
                          setProjectMenuOpened(true);
                        }
                      }}
                      rightSection={<IconChevronDown size={16} />}
                      variant="light"
                    >
                      <Text className="project-selector-label" component="span" truncate>
                        {projects.length
                          ? currentProject.name || "Select project"
                          : "No projects yet"}
                      </Text>
                    </Button>
                  </Menu.Target>
                  <Menu.Dropdown>
                    <TextInput
                      aria-label="Filter projects"
                      leftSection={<IconSearch size={14} />}
                      mb="xs"
                      onChange={(event) => setProjectFilter(event.currentTarget.value)}
                      placeholder="Filter projects"
                      size="xs"
                      value={projectFilter}
                    />
                    <ScrollArea.Autosize
                      mah="min(58dvh, 28rem)"
                      offsetScrollbars
                      scrollbarSize={8}
                      type="auto"
                    >
                      {visibleProjects.length ? (
                        visibleProjects.map((project) => {
                          const selected = project.id === currentProject.id;
                          const selectProject = () => {
                            if (project.id) {
                              onSelectProject(project.id);
                              setProjectMenuOpened(false);
                              setProjectFilter("");
                            }
                          };
                          return (
                            <Menu.Item
                              aria-current={selected ? "true" : undefined}
                              key={project.id || project.name}
                              onClick={selectProject}
                              onKeyDown={(event) => {
                                if (event.key === "Enter") {
                                  event.preventDefault();
                                  selectProject();
                                }
                              }}
                              ref={selected ? selectedProjectItem : undefined}
                            >
                              <Text fw={750} lineClamp={2} size="sm" title={project.name}>
                                {project.name}
                              </Text>
                              <Text c="dimmed" size="xs">
                                {repositoryCountLabel(project.repositories.length)}
                              </Text>
                            </Menu.Item>
                          );
                        })
                      ) : (
                        <Text c="dimmed" px="xs" py="sm" size="sm">
                          No matching projects
                        </Text>
                      )}
                    </ScrollArea.Autosize>
                  </Menu.Dropdown>
                </Menu>
                <Tooltip label="New project">
                  <Button
                    aria-label="New project"
                    color="teal"
                    onClick={onNewProject}
                    px="sm"
                    variant="light"
                  >
                    <IconPlus size={18} />
                  </Button>
                </Tooltip>
              </Group>
              <Group gap={6}>
                {currentProject.repositories.length ? (
                  <>
                    <Text className="repo-chip">{repositoryCountLabel(currentProject.repositories.length)}</Text>
                    {currentProject.repositories.slice(0, 3).map((repository) => (
                      <Text className="repo-chip" key={repository.id} title={repository.url}>
                        {readableRepositoryLabel(repository)}
                      </Text>
                    ))}
                  </>
                ) : (
                  <Text c="blue.1" size="sm">
                    No repositories configured
                  </Text>
                )}
              </Group>
              <button
                className={currentPage === "app-settings" ? "model-summary-button active" : "model-summary-button"}
                onClick={() => onNavigate("app-settings")}
                type="button"
              >
                <IconBrain size={18} />
                <span>
                  <Text c="teal.1" size="xs">
                    Model
                  </Text>
                  <Text className="model-summary-text" fw={750} size="sm">
                    {modelLabel}
                  </Text>
                </span>
              </button>
            </Stack>

            <Stack className="rail-section" gap={4}>
              {navItems.map((item) => {
                const Icon = item.icon;
                return (
                  <NavLink
                    active={currentPage === item.page}
                    color="teal"
                    key={item.page}
                    label={item.label}
                    leftSection={<Icon size={19} />}
                    onClick={() => {
                      onNavigate(item.page);
                      close();
                    }}
                  />
                );
              })}
              <NavLink
                active={currentPage === "projects"}
                color="teal"
                label="Saved projects"
                leftSection={<IconLayoutDashboard size={19} />}
                onClick={() => onNavigate("projects")}
              />
            </Stack>

            <Button
              component="a"
              href="/docs"
              justify="flex-start"
              leftSection={<IconBook2 size={18} />}
              mt="xl"
              variant="subtle"
            >
              Developer API
            </Button>
          </Stack>
        </ScrollArea>
      </AppShell.Navbar>

      <AppShell.Header className="mobile-header" hiddenFrom="md">
        <Group h="100%" px="md">
          <Burger opened={opened} onClick={toggle} size="sm" />
          <Title order={3}>GuideSync</Title>
        </Group>
      </AppShell.Header>

      <AppShell.Main className="workspace-main">{children}</AppShell.Main>
    </AppShell>
  );
}

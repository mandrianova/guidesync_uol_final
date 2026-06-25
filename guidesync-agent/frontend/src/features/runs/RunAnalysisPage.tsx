import {
  Button,
  Group,
  Paper,
  Radio,
  SimpleGrid,
  Stack,
  Text,
  TextInput,
  Textarea,
  Title
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconPlayerPlay } from "@tabler/icons-react";
import { useMemo, useState } from "react";

import { api } from "../../api/client";
import { PageHeader } from "../../components/PageHeader";
import { SectionPanel } from "../../components/SectionPanel";
import { StatusBadge } from "../../components/StatusBadge";
import type { BranchSortMode } from "../../lib/branches";
import { isoDate } from "../../lib/dates";
import { projectPayload } from "../../lib/projects";
import type { BranchInfo, ProjectConfig, RunMode, RunSummary } from "../../types";
import { BranchPicker } from "./BranchPicker";

interface RunAnalysisPageProps {
  project: ProjectConfig;
  runStatus: string;
  onRunCreated: (summary: RunSummary) => Promise<void>;
  onStatusChange: (status: string) => void;
}

export function RunAnalysisPage({
  project,
  runStatus,
  onRunCreated,
  onStatusChange
}: RunAnalysisPageProps) {
  const [goal, setGoal] = useState(
    "Analyze repository changes and draft user-facing release notes grounded in the stored product context."
  );
  const [mode, setMode] = useState<RunMode>("default_branch_period");
  const [since, setSince] = useState(isoDate(14));
  const [until, setUntil] = useState("");
  const [branchCache, setBranchCache] = useState<Record<string, BranchInfo[]>>({});
  const [branchWarnings, setBranchWarnings] = useState<Record<string, string>>({});
  const [branchSortByRepo, setBranchSortByRepo] = useState<Record<string, BranchSortMode>>({});
  const [selectedBranchesByRepo, setSelectedBranchesByRepo] = useState<Record<string, string[]>>({});
  const [loadingBranches, setLoadingBranches] = useState<Record<string, boolean>>({});
  const [submitting, setSubmitting] = useState(false);

  const repositories = useMemo(() => projectPayload(project).repositories, [project]);

  const loadBranches = async (repositoryId: string, defaultBranch: string) => {
    if (!project.id) {
      setBranchWarnings((current) => ({
        ...current,
        [repositoryId]: "Save the project before loading branches."
      }));
      return;
    }
    setLoadingBranches((current) => ({ ...current, [repositoryId]: true }));
    setBranchWarnings((current) => ({ ...current, [repositoryId]: "" }));
    try {
      const result = await api.listBranches(project.id, repositoryId);
      const branches = result.branches || [];
      setBranchCache((current) => ({ ...current, [repositoryId]: branches }));
      setBranchWarnings((current) => ({ ...current, [repositoryId]: result.warning || "" }));
      if (branches.some((branch) => branch.name === defaultBranch)) {
        setSelectedBranchesByRepo((current) => ({
          ...current,
          [repositoryId]: current[repositoryId]?.length ? current[repositoryId] : [defaultBranch]
        }));
      }
    } catch (error) {
      setBranchCache((current) => ({ ...current, [repositoryId]: [] }));
      setBranchWarnings((current) => ({
        ...current,
        [repositoryId]: `Could not load branches: ${
          error instanceof Error ? error.message : "unknown error"
        }`
      }));
    } finally {
      setLoadingBranches((current) => ({ ...current, [repositoryId]: false }));
    }
  };

  const submitRun = async () => {
    if (!project.id) {
      onStatusChange("Save project first");
      notifications.show({
        color: "yellow",
        message: "Save the project before creating an analysis run.",
        title: "Run analysis"
      });
      return;
    }

    const branches = mode === "select_branches" ? selectedBranchesByRepo : {};
    if (mode === "select_branches") {
      const missingRepositories = repositories.filter(
        (repository) => !branches[repository.id]?.length
      );
      if (missingRepositories.length) {
        onStatusChange("Select branches");
        return;
      }
    }

    setSubmitting(true);
    onStatusChange("Creating");
    try {
      const summary = await api.createProjectRun(project.id, {
        mode,
        goal,
        since: mode === "default_branch_period" ? since || null : null,
        until: mode === "default_branch_period" ? until || null : null,
        branches
      });
      onStatusChange(summary.status);
      await onRunCreated(summary);
    } catch (error) {
      onStatusChange("Error");
      notifications.show({
        color: "red",
        message: error instanceof Error ? error.message : "Could not create analysis run",
        title: "Run request failed"
      });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Stack gap="lg">
      <PageHeader title={project.id ? `Run analysis · ${project.name}` : "Run analysis"} />
      <SectionPanel
        actions={<StatusBadge status={runStatus} />}
        description="Choose what changed, then generate release notes for review."
        title="Run analysis"
      >
        <Stack gap="md">
          <Textarea
            autosize
            label="Goal"
            minRows={3}
            onChange={(event) => setGoal(event.currentTarget.value)}
            value={goal}
          />

          <Radio.Group label="Analysis mode" onChange={(value) => setMode(value as RunMode)} value={mode}>
            <Group mt="xs">
              <Radio value="default_branch_period" label="Period on default branch" />
              <Radio value="select_branches" label="Specific branches" />
            </Group>
          </Radio.Group>

          {mode === "default_branch_period" ? (
            <SimpleGrid cols={{ base: 1, sm: 2 }}>
              <TextInput
                label="Since"
                onChange={(event) => setSince(event.currentTarget.value)}
                type="date"
                value={since}
              />
              <TextInput
                label="Until"
                onChange={(event) => setUntil(event.currentTarget.value)}
                type="date"
                value={until}
              />
            </SimpleGrid>
          ) : (
            <div>
              <Title order={3}>Branches by repository</Title>
              <Text c="dimmed" size="sm">
                Load branches, sort them, then choose what to analyze.
              </Text>
            </div>
          )}

          <Stack gap="sm">
            {repositories.map((repository) => {
              const defaultBranch = repository.default_branch || "main";
              return (
                <Paper className="row-card" key={repository.id} p="md" withBorder>
                  <Stack gap="sm">
                    <Group align="flex-start" justify="space-between">
                      <div>
                        <Title order={3}>{repository.name}</Title>
                        <Text c="dimmed" size="sm">
                          {repository.url}
                        </Text>
                      </div>
                      <StatusBadge status={defaultBranch} />
                    </Group>

                    {mode === "select_branches" ? (
                      <BranchPicker
                        branchSort={branchSortByRepo[repository.id] || "updated_desc"}
                        branches={branchCache[repository.id] || []}
                        loading={Boolean(loadingBranches[repository.id])}
                        onLoadBranches={() => loadBranches(repository.id, defaultBranch)}
                        onSelectedBranchesChange={(branches) =>
                          setSelectedBranchesByRepo((current) => ({
                            ...current,
                            [repository.id]: branches
                          }))
                        }
                        onSortChange={(sortMode) =>
                          setBranchSortByRepo((current) => ({
                            ...current,
                            [repository.id]: sortMode
                          }))
                        }
                        repository={repository}
                        selectedBranches={selectedBranchesByRepo[repository.id] || []}
                        warning={branchWarnings[repository.id]}
                      />
                    ) : (
                      <Text c="dimmed" size="sm">
                        Analyzing {defaultBranch} with the selected period.
                      </Text>
                    )}
                  </Stack>
                </Paper>
              );
            })}
          </Stack>

          <Button
            disabled={!repositories.length}
            leftSection={<IconPlayerPlay size={18} />}
            loading={submitting}
            onClick={submitRun}
          >
            Run analysis
          </Button>
        </Stack>
      </SectionPanel>
    </Stack>
  );
}

import {
  Alert,
  Button,
  Group,
  NumberInput,
  Paper,
  PasswordInput,
  Radio,
  Select,
  SimpleGrid,
  Stack,
  Text,
  TextInput,
  Textarea,
  Title
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconAlertCircle, IconListCheck } from "@tabler/icons-react";
import { useEffect, useMemo, useState } from "react";

import { api } from "../../api/client";
import { PageHeader } from "../../components/PageHeader";
import { SectionPanel } from "../../components/SectionPanel";
import { StatusBadge } from "../../components/StatusBadge";
import type { BranchSortMode } from "../../lib/branches";
import { isoDate } from "../../lib/dates";
import { projectPayload } from "../../lib/projects";
import type {
  BranchInfo,
  ProjectConfig,
  ProjectPipelineState,
  RunMode,
  RunSummary,
  TaskInterfaceAuthMode,
  TaskInterfaceAuthType
} from "../../types";
import { BranchPicker } from "./BranchPicker";

interface RunAnalysisPageProps {
  project: ProjectConfig;
  runStatus: string;
  workflowState: ProjectPipelineState | null;
  workflowStateLoading: boolean;
  onRunCreated: (summary: RunSummary) => Promise<void>;
  onStatusChange: (status: string) => void;
  onWorkflowStateRefresh: () => Promise<void>;
}

export function RunAnalysisPage({
  project,
  runStatus,
  workflowState,
  workflowStateLoading,
  onRunCreated,
  onStatusChange,
  onWorkflowStateRefresh
}: RunAnalysisPageProps) {
  const [goal, setGoal] = useState(
    "Analyze repository changes and draft user-facing release notes grounded in the stored product context."
  );
  const [mode, setMode] = useState<RunMode>("default_branch_period");
  const [since, setSince] = useState(isoDate(14));
  const [until, setUntil] = useState("");
  const [maxCommits, setMaxCommits] = useState<number | string>(40);
  const [branchCache, setBranchCache] = useState<Record<string, BranchInfo[]>>({});
  const [branchWarnings, setBranchWarnings] = useState<Record<string, string>>({});
  const [branchSortByRepo, setBranchSortByRepo] = useState<Record<string, BranchSortMode>>({});
  const [selectedBranchesByRepo, setSelectedBranchesByRepo] = useState<Record<string, string[]>>({});
  const [loadingBranches, setLoadingBranches] = useState<Record<string, boolean>>({});
  const [taskInterfaceUrl, setTaskInterfaceUrl] = useState(project.task_interface_url || "");
  const [authMode, setAuthMode] = useState<TaskInterfaceAuthMode>(
    project.has_task_interface_auth ? "inherit" : "disabled"
  );
  const [authType, setAuthType] = useState<TaskInterfaceAuthType>(
    project.task_interface_auth_type || "local_storage"
  );
  const [authSecret, setAuthSecret] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    setTaskInterfaceUrl(project.task_interface_url || "");
    setAuthMode(project.has_task_interface_auth ? "inherit" : "disabled");
    setAuthType(project.task_interface_auth_type || "local_storage");
    setAuthSecret("");
  }, [
    project.id,
    project.task_interface_url,
    project.has_task_interface_auth,
    project.task_interface_auth_type
  ]);

  const repositories = useMemo(() => projectPayload(project).repositories, [project]);
  const canInheritAuth =
    project.has_task_interface_auth &&
    sameOrigin(taskInterfaceUrl.trim() || project.task_interface_url, project.task_interface_url);
  const blockedReason = workflowState?.blocked_reason || null;
  const displayedRunStatus = workflowStateLoading ? "Checking" : runStatus;
  const queueButtonLabel = blockedReason ? "Queue prerequisites + analysis" : "Queue analysis";

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

    const parsedMaxCommits = Number(maxCommits);
    if (!Number.isInteger(parsedMaxCommits) || parsedMaxCommits < 1 || parsedMaxCommits > 500) {
      onStatusChange("Choose commit limit");
      return;
    }

    const branches = mode === "select_branches" ? selectedBranchesByRepo : {};
    if (authMode === "override" && !authSecret.trim()) {
      onStatusChange("Enter UI authorization");
      return;
    }
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
    onStatusChange("Queueing");
    try {
      const plan = await api.enqueueAnalysisPipeline(project.id, {
        mode,
        goal,
        since: mode === "default_branch_period" ? since || null : null,
        until: mode === "default_branch_period" ? until || null : null,
        branches,
        max_commits: parsedMaxCommits,
        task_interface_url: taskInterfaceUrl.trim() || null,
        task_interface_auth_mode: authMode,
        task_interface_auth_type: authType,
        task_interface_auth_secret: authMode === "override" ? authSecret.trim() : null,
        report_locale: "en"
      });
      const summary = plan.run;
      onStatusChange(summary?.status || "queued");
      await onWorkflowStateRefresh().catch(() => undefined);
      if (summary) {
        await onRunCreated(summary);
      }
      notifications.show({
        color: "teal",
        message: `${plan.tasks.length} workflow tasks queued for this analysis.`,
        title: "Analysis queued"
      });
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
        actions={<StatusBadge status={displayedRunStatus} />}
        description="Choose what changed, then queue profile, knowledge base, and release-note analysis tasks."
        title="Run analysis"
      >
        <Stack gap="md">
          {workflowState ? (
            <Paper className="row-card" p="md" withBorder>
              <Stack gap="xs">
                <Group gap="xs">
                  <StatusBadge
                    status={workflowState.profile_ready ? "Profile ready" : "Profile pending"}
                  />
                  <StatusBadge
                    status={
                      workflowState.knowledge_base_ready
                        ? "Knowledge ready"
                        : "Knowledge pending"
                    }
                  />
                </Group>
                {blockedReason ? (
                  <Alert
                    color="yellow"
                    icon={<IconAlertCircle size={18} />}
                    title="Workflow prerequisites pending"
                    variant="light"
                  >
                    {blockedReason}
                  </Alert>
                ) : null}
              </Stack>
            </Paper>
          ) : null}

          <Textarea
            autosize
            label="Goal"
            minRows={3}
            onChange={(event) => setGoal(event.currentTarget.value)}
            value={goal}
          />

          <TextInput
            description="Overrides the project UI URL for this report. Leave unchanged to use the project default."
            label="UI URL for this report"
            onChange={(event) => {
              const value = event.currentTarget.value;
              setTaskInterfaceUrl(value);
              if (
                authMode === "inherit" &&
                !sameOrigin(value.trim() || project.task_interface_url, project.task_interface_url)
              ) {
                setAuthMode("disabled");
              }
            }}
            placeholder="http://127.0.0.1:5173/#/run"
            value={taskInterfaceUrl}
          />

          <Text c="dimmed" size="sm">
            {taskInterfaceUrl.trim()
              ? "Screenshots are optional. A separate capture step may add them when they support the report."
              : "Screenshots are skipped because no UI URL is configured."}
          </Text>

          <Radio.Group
            label="UI authorization for screenshots"
            onChange={(value) => {
              setAuthMode(value as TaskInterfaceAuthMode);
              if (value !== "override") {
                setAuthSecret("");
              }
            }}
            value={authMode}
          >
            <Group mt="xs">
              <Radio
                disabled={!canInheritAuth}
                value="inherit"
                label="Use project authorization"
              />
              <Radio value="override" label="Override for this report" />
              <Radio value="disabled" label="No authorization" />
            </Group>
          </Radio.Group>

          {authMode === "override" ? (
            <Stack gap="sm">
              <Select
                allowDeselect={false}
                data={[
                  { value: "local_storage", label: "Browser localStorage (JSON)" },
                  { value: "cookie", label: "Cookie header" }
                ]}
                label="Authorization storage"
                onChange={(value) => value && setAuthType(value as TaskInterfaceAuthType)}
                value={authType}
              />
              <PasswordInput
                description="Used only for this report's same-origin screenshot session."
                label="Authorization value"
                onChange={(event) => setAuthSecret(event.currentTarget.value)}
                placeholder={
                  authType === "cookie" ? "session=..." : '{"accessToken":"..."}'
                }
                value={authSecret}
              />
            </Stack>
          ) : null}

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

          <NumberInput
            description="Maximum commits collected from each selected repository or branch."
            label="Maximum commits per repository"
            max={500}
            min={1}
            onChange={setMaxCommits}
            value={maxCommits}
          />

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
            leftSection={<IconListCheck size={18} />}
            loading={submitting}
            onClick={submitRun}
          >
            {queueButtonLabel}
          </Button>
        </Stack>
      </SectionPanel>
    </Stack>
  );
}

function sameOrigin(first: string | null | undefined, second: string | null | undefined): boolean {
  if (!first || !second) {
    return false;
  }
  try {
    return new URL(first).origin === new URL(second).origin;
  } catch {
    return false;
  }
}

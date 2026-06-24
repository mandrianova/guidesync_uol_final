import {
  Alert,
  Button,
  Checkbox,
  Group,
  Paper,
  Select,
  Stack,
  Text
} from "@mantine/core";
import { IconGitBranch, IconRefresh } from "@tabler/icons-react";

import type { BranchSortMode } from "../../lib/branches";
import { sortBranches } from "../../lib/branches";
import { formatBranchDate } from "../../lib/dates";
import type { BranchInfo, ProjectRepository } from "../../types";

interface BranchPickerProps {
  branchSort: BranchSortMode;
  branches: BranchInfo[];
  loading: boolean;
  repository: ProjectRepository;
  selectedBranches: string[];
  warning?: string;
  onLoadBranches: () => void;
  onSelectedBranchesChange: (branches: string[]) => void;
  onSortChange: (sortMode: BranchSortMode) => void;
}

export function BranchPicker({
  branchSort,
  branches,
  loading,
  repository,
  selectedBranches,
  warning,
  onLoadBranches,
  onSelectedBranchesChange,
  onSortChange
}: BranchPickerProps) {
  const sortedBranches = sortBranches(branches, branchSort);

  return (
    <Stack gap="sm">
      <Group align="end">
        <Button
          leftSection={<IconRefresh size={17} />}
          loading={loading}
          onClick={onLoadBranches}
          variant="light"
        >
          Load branch list
        </Button>
        <Select
          allowDeselect={false}
          data={[
            { value: "updated_desc", label: "Newest first" },
            { value: "name_asc", label: "Name A-Z" },
            { value: "name_desc", label: "Name Z-A" }
          ]}
          label="Sort"
          onChange={(value) => onSortChange((value || "updated_desc") as BranchSortMode)}
          value={branchSort}
          w={220}
        />
      </Group>

      {warning ? (
        <Alert color="yellow" icon={<IconGitBranch size={18} />} title="Branch list warning">
          {warning}
        </Alert>
      ) : !sortedBranches.length ? (
        <Text c="dimmed" size="sm">
          Load branches to choose from the repository branch list.
        </Text>
      ) : (
        <Stack gap="xs">
          {sortedBranches.map((branch) => {
            const checked = selectedBranches.includes(branch.name);
            return (
              <Paper className="branch-choice" key={branch.name} p="sm" withBorder>
                <Checkbox
                  checked={checked}
                  label={
                    <span>
                      <Text fw={800} size="sm">
                        {branch.name}
                      </Text>
                      <Text c="dimmed" size="xs">
                        {formatBranchDate(branch.updated_at)}
                      </Text>
                    </span>
                  }
                  onChange={(event) => {
                    const next = event.currentTarget.checked
                      ? [...selectedBranches, branch.name]
                      : selectedBranches.filter((name) => name !== branch.name);
                    onSelectedBranchesChange(next);
                  }}
                />
              </Paper>
            );
          })}
        </Stack>
      )}

      {!selectedBranches.length && branches.length ? (
        <Text c="dimmed" size="sm">
          The default branch is {repository.default_branch || "main"}; select at least one branch before running.
        </Text>
      ) : null}
    </Stack>
  );
}

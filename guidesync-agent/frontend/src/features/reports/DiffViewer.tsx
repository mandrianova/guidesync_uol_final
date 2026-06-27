import { Badge, Group, Paper, ScrollArea, SegmentedControl, Stack, Text } from "@mantine/core";
import { useMemo, useState } from "react";
import { Decoration, Diff, Hunk, parseDiff, type FileData, type ViewType } from "react-diff-view";
import "react-diff-view/style/index.css";

interface DiffViewerProps {
  diff: string;
}

type DiffViewMode = Extract<ViewType, "split" | "unified">;

const viewOptions: Array<{ label: string; value: DiffViewMode }> = [
  { label: "Split", value: "split" },
  { label: "Unified", value: "unified" }
];

export function DiffViewer({ diff }: DiffViewerProps) {
  const [viewType, setViewType] = useState<DiffViewMode>("split");
  const parsedFiles = useMemo(() => parseUnifiedDiff(diff), [diff]);

  if (!diff.trim()) {
    return (
      <Text c="dimmed" mt="sm" size="sm">
        No diff content available.
      </Text>
    );
  }

  if (!parsedFiles.length) {
    return (
      <ScrollArea className="diff-viewer-raw-scroll" mt="sm" type="auto">
        <Text className="diff-viewer-raw" component="pre">
          {diff}
        </Text>
      </ScrollArea>
    );
  }

  return (
    <Stack className="diff-viewer" gap="sm" mt="sm">
      <Group justify="space-between">
        <Text c="dimmed" size="sm">
          {parsedFiles.length} {parsedFiles.length === 1 ? "file" : "files"} changed
        </Text>
        <SegmentedControl
          aria-label="Diff view mode"
          data={viewOptions}
          onChange={(value) => setViewType(value as DiffViewMode)}
          size="xs"
          value={viewType}
        />
      </Group>

      {parsedFiles.map((file, index) => (
        <DiffFile file={file} index={index} key={fileKey(file, index)} viewType={viewType} />
      ))}
    </Stack>
  );
}

function DiffFile({
  file,
  index,
  viewType
}: {
  file: FileData;
  index: number;
  viewType: DiffViewMode;
}) {
  const stats = diffStats(file);
  const path = displayPath(file);

  return (
    <Paper className="diff-file-card" withBorder>
      <Group className="diff-file-header" gap="xs" justify="space-between">
        <div className="diff-file-title">
          <Text fw={850} size="sm">
            {path}
          </Text>
          {file.type === "rename" && file.oldPath !== file.newPath ? (
            <Text c="dimmed" size="xs">
              renamed from {file.oldPath}
            </Text>
          ) : null}
        </div>
        <Group gap={6} wrap="nowrap">
          <Badge color={statusColor(file.type)} size="sm" variant="light">
            {file.type}
          </Badge>
          <Badge color="green" size="sm" variant="light">
            +{stats.insertions}
          </Badge>
          <Badge color="red" size="sm" variant="light">
            -{stats.deletions}
          </Badge>
        </Group>
      </Group>

      <ScrollArea className="diff-scroll" type="auto">
        <Diff
          className={`diff-viewer-table diff-viewer-table-${viewType}`}
          diffType={file.type}
          gutterType="default"
          hunks={file.hunks}
          viewType={viewType}
        >
          {(hunks) =>
            hunks.flatMap((hunk, hunkIndex) => [
              <Decoration key={`decoration-${index}-${hunkIndex}-${hunk.content}`}>
                {hunk.content}
              </Decoration>,
              <Hunk hunk={hunk} key={`hunk-${index}-${hunkIndex}-${hunk.content}`} />
            ])
          }
        </Diff>
      </ScrollArea>
    </Paper>
  );
}

function parseUnifiedDiff(diff: string): FileData[] {
  try {
    return parseDiff(diff, { nearbySequences: "zip" });
  } catch {
    return [];
  }
}

function fileKey(file: FileData, index: number): string {
  return `${index}-${file.oldRevision}-${file.newRevision}-${file.oldPath}-${file.newPath}`;
}

function displayPath(file: FileData): string {
  return file.newPath || file.oldPath || "Changed file";
}

function diffStats(file: FileData): { insertions: number; deletions: number } {
  return file.hunks.reduce(
    (stats, hunk) => {
      hunk.changes.forEach((change) => {
        if (change.type === "insert") {
          stats.insertions += 1;
        }
        if (change.type === "delete") {
          stats.deletions += 1;
        }
      });
      return stats;
    },
    { insertions: 0, deletions: 0 }
  );
}

function statusColor(type: FileData["type"]): string {
  if (type === "add" || type === "copy") {
    return "green";
  }
  if (type === "delete") {
    return "red";
  }
  if (type === "rename") {
    return "blue";
  }
  return "gray";
}

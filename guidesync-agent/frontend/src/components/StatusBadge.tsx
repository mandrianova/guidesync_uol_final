import { Badge } from "@mantine/core";

interface StatusBadgeProps {
  status: string;
}

export function StatusBadge({ status }: StatusBadgeProps) {
  const normalized = status.toLowerCase();
  const color =
    normalized === "completed" || normalized === "saved" || normalized === "adjudicated"
      ? "green"
      : normalized === "failed" ||
          normalized === "partial_failure" ||
          normalized === "error" ||
          normalized === "load error"
        ? "red"
        : normalized === "cancelled"
          ? "gray"
          : normalized === "blocked" || normalized === "retrying"
          ? "yellow"
        : normalized === "not adjudicated" ||
            normalized === "not evaluated" ||
            normalized === "undefined"
          ? "yellow"
        : normalized === "running" ||
            normalized === "processing_presentation" ||
            normalized === "indexing" ||
            normalized === "creating" ||
            normalized === "analyzing"
          ? "blue"
          : normalized === "queued" || normalized === "draft" || normalized === "unsaved"
            ? "yellow"
            : "gray";

  return (
    <Badge color={color} radius="xl" variant="light">
      {status}
    </Badge>
  );
}

import { Badge } from "@mantine/core";

interface StatusBadgeProps {
  status: string;
}

export function StatusBadge({ status }: StatusBadgeProps) {
  const normalized = status.toLowerCase();
  const color =
    normalized === "completed" || normalized === "saved"
      ? "green"
      : normalized === "failed" || normalized === "error" || normalized === "load error"
        ? "red"
        : normalized === "running" || normalized === "indexing" || normalized === "creating"
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

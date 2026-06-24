import { Paper, Text } from "@mantine/core";
import type { ReactNode } from "react";

interface EmptyStateProps {
  children: ReactNode;
}

export function EmptyState({ children }: EmptyStateProps) {
  return (
    <Paper className="empty-state" p="lg" withBorder>
      <Text c="dimmed" size="sm">
        {children}
      </Text>
    </Paper>
  );
}

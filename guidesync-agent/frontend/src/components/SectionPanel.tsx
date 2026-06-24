import { Group, Paper, Text, Title } from "@mantine/core";
import type { ReactNode } from "react";

interface SectionPanelProps {
  title: string;
  description?: string;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}

export function SectionPanel({ title, description, actions, children, className }: SectionPanelProps) {
  return (
    <Paper className={className} p="lg" shadow="sm" withBorder>
      <Group align="flex-start" justify="space-between" mb="md">
        <div>
          <Title order={2}>{title}</Title>
          {description ? (
            <Text c="dimmed" mt={4} size="sm">
              {description}
            </Text>
          ) : null}
        </div>
        {actions}
      </Group>
      {children}
    </Paper>
  );
}

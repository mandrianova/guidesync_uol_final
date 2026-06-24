import { Group, Text, Title } from "@mantine/core";
import type { ReactNode } from "react";

interface PageHeaderProps {
  label?: string;
  title: string;
  actions?: ReactNode;
}

export function PageHeader({ label = "Workspace", title, actions }: PageHeaderProps) {
  return (
    <Group align="end" className="page-header" justify="space-between" wrap="nowrap">
      <div>
        <Text className="eyebrow" size="xs">
          {label}
        </Text>
        <Title order={1}>{title}</Title>
      </div>
      {actions}
    </Group>
  );
}

import { Badge, Drawer, Group, ScrollArea, Stack, Text } from "@mantine/core";

import { MarkdownBlock } from "../../components/MarkdownBlock";
import type { KnowledgeDocumentDetail } from "../../types";

interface KnowledgeDocumentDrawerProps {
  detail: KnowledgeDocumentDetail | null;
  opened: boolean;
  onClose: () => void;
}

export function KnowledgeDocumentDrawer({
  detail,
  opened,
  onClose
}: KnowledgeDocumentDrawerProps) {
  return (
    <Drawer
      opened={opened}
      onClose={onClose}
      padding="lg"
      position="right"
      size="xl"
      title={detail?.document.path || "Knowledge document"}
    >
      {detail ? (
        <Stack gap="md">
          <Group gap={6}>
            <Badge variant="light">{detail.document.section_count} sections</Badge>
            {detail.source_commit ? (
              <Badge variant="outline">{detail.source_commit.slice(0, 8)}</Badge>
            ) : null}
            {detail.truncated ? <Badge color="yellow">truncated</Badge> : null}
          </Group>
          {detail.warnings.map((warning, index) => (
            <Text c="yellow.8" key={`${warning}:${index}`} size="sm">
              {warning}
            </Text>
          ))}
          <Group gap={6}>
            {[
              ...detail.document.categories,
              ...detail.document.keyphrases,
              ...detail.document.extracted_names,
              ...detail.document.concepts
            ]
              .slice(0, 20)
              .map((tag, index) => (
                <Badge key={`${tag}:${index}`} variant="light">
                  {tag}
                </Badge>
              ))}
          </Group>
          <Stack gap={4}>
            {detail.sections.slice(0, 12).map((section) => (
              <Text key={section.id} size="sm">
                {section.heading}{" "}
                <Text c="dimmed" component="span" size="xs">
                  {section.start_line ? `line ${section.start_line}` : ""}
                </Text>
              </Text>
            ))}
          </Stack>
          <Text fw={850}>Document content</Text>
          <ScrollArea h="55vh">
            <MarkdownBlock markdown={detail.markdown || "_No document content available._"} />
          </ScrollArea>
        </Stack>
      ) : null}
    </Drawer>
  );
}

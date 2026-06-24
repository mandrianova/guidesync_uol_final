import { Anchor, Box, Code, List, Stack, Text, Title } from "@mantine/core";
import type { ReactNode } from "react";

function parseInline(value: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  const pattern = /(`[^`]+`|\*\*[^*]+\*\*|\[[^\]]+\]\(https?:\/\/[^)\s]+\))/g;
  let cursor = 0;

  for (const match of value.matchAll(pattern)) {
    if (match.index > cursor) {
      nodes.push(value.slice(cursor, match.index));
    }
    const token = match[0];
    if (token.startsWith("`")) {
      nodes.push(<Code key={`${match.index}-code`}>{token.slice(1, -1)}</Code>);
    } else if (token.startsWith("**")) {
      nodes.push(
        <strong key={`${match.index}-strong`}>
          {token.slice(2, -2)}
        </strong>
      );
    } else {
      const link = token.match(/^\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)$/);
      if (link) {
        nodes.push(
          <Anchor key={`${match.index}-link`} href={link[2]} target="_blank">
            {link[1]}
          </Anchor>
        );
      }
    }
    cursor = match.index + token.length;
  }

  if (cursor < value.length) {
    nodes.push(value.slice(cursor));
  }

  return nodes;
}

export function MarkdownBlock({ markdown }: { markdown: string }) {
  const blocks: ReactNode[] = [];
  let paragraph: string[] = [];
  let listItems: string[] = [];

  const flushParagraph = () => {
    if (!paragraph.length) {
      return;
    }
    const text = paragraph.join(" ");
    blocks.push(
      <Text key={`p-${blocks.length}`} lh={1.6}>
        {parseInline(text)}
      </Text>
    );
    paragraph = [];
  };

  const flushList = () => {
    if (!listItems.length) {
      return;
    }
    blocks.push(
      <List key={`list-${blocks.length}`} spacing={6}>
        {listItems.map((item, index) => (
          <List.Item key={`${item}-${index}`}>{parseInline(item)}</List.Item>
        ))}
      </List>
    );
    listItems = [];
  };

  for (const rawLine of markdown.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line) {
      flushParagraph();
      flushList();
      continue;
    }
    if (line.startsWith("#")) {
      flushParagraph();
      flushList();
      const marker = line.match(/^#{1,3}/)?.[0] || "#";
      const level = marker.length;
      blocks.push(
        <Title key={`h-${blocks.length}`} order={Math.min(level + 1, 4) as 2 | 3 | 4}>
          {parseInline(line.slice(level).trim())}
        </Title>
      );
      continue;
    }
    if (line.startsWith("- ")) {
      flushParagraph();
      listItems.push(line.slice(2).trim());
      continue;
    }
    flushList();
    paragraph.push(line);
  }

  flushParagraph();
  flushList();

  return (
    <Box className="markdown-block">
      <Stack gap="sm">{blocks}</Stack>
    </Box>
  );
}

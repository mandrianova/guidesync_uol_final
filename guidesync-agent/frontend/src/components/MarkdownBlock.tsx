import { Anchor, Box } from "@mantine/core";
import ReactMarkdown, { type Components } from "react-markdown";
import rehypeHighlight from "rehype-highlight";
import remarkGfm from "remark-gfm";

const components: Components = {
  a: ({ children, href, node: _node, ...props }) => (
    <Anchor href={href} rel="noreferrer" target="_blank" {...props}>
      {children}
    </Anchor>
  ),
  table: ({ children, node: _node, ...props }) => (
    <div className="markdown-table-scroll">
      <table {...props}>{children}</table>
    </div>
  )
};

export function MarkdownBlock({ markdown }: { markdown: string }) {
  return (
    <Box className="markdown-block">
      <ReactMarkdown
        components={components}
        rehypePlugins={[rehypeHighlight]}
        remarkPlugins={[remarkGfm]}
      >
        {markdown}
      </ReactMarkdown>
    </Box>
  );
}

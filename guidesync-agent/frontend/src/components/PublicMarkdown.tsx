import { Anchor } from "@mantine/core";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

const allowedElements = [
  "a",
  "blockquote",
  "code",
  "em",
  "h2",
  "h3",
  "li",
  "ol",
  "p",
  "strong",
  "ul"
];

const components: Components = {
  a: ({ children, href, node: _node, ...props }) => {
    const safeHref = safePublicationUrl(href || "");
    return safeHref ? (
      <Anchor href={safeHref} rel="noreferrer" target="_blank" {...props}>
        {children}
      </Anchor>
    ) : (
      <span>{children}</span>
    );
  }
};

export function PublicMarkdown({ markdown }: { markdown: string }) {
  return (
    <div className="public-markdown">
      <ReactMarkdown
        allowedElements={allowedElements}
        components={components}
        remarkPlugins={[remarkGfm]}
        unwrapDisallowed
        urlTransform={(url) => safePublicationUrl(url) || ""}
      >
        {markdown}
      </ReactMarkdown>
    </div>
  );
}

export function safePublicationUrl(url: string): string | null {
  const normalized = url.trim();
  if (normalized.startsWith("/") || normalized.startsWith("#")) {
    return normalized;
  }
  try {
    return new URL(normalized).protocol === "https:" ? normalized : null;
  } catch {
    return null;
  }
}

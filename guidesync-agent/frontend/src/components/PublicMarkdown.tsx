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
  "pre",
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
  if (normalized.startsWith("#")) {
    return normalized;
  }
  try {
    if (normalized.startsWith("/")) {
      const base = "https://guidesync.invalid";
      return new URL(normalized, base).origin === base ? normalized : null;
    }
    const parsed = new URL(normalized);
    return parsed.protocol === "https:" && !parsed.username && !parsed.password
      ? normalized
      : null;
  } catch {
    return null;
  }
}

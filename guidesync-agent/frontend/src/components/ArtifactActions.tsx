import { Anchor, Group } from "@mantine/core";

import { artifactUrl } from "../api/client";

interface ArtifactActionsProps {
  runId: string;
  artifacts: Record<string, string>;
}

export function ArtifactActions({ runId, artifacts }: ArtifactActionsProps) {
  const hasHtml = Boolean(artifacts["report.html"]);
  const hasMarkdown = Boolean(artifacts["report.md"]);

  if (!hasHtml && !hasMarkdown) {
    return null;
  }

  return (
    <Group gap="xs" justify="flex-end" wrap="wrap">
      {hasHtml ? (
        <>
          <Anchor className="artifact-link" href={artifactUrl(runId, "report.html")} target="_blank">
            Open report
          </Anchor>
          <Anchor
            className="artifact-link"
            href={artifactUrl(runId, "report.html", { print: "1" })}
            target="_blank"
          >
            PDF
          </Anchor>
        </>
      ) : null}
      {hasMarkdown ? (
        <Anchor className="artifact-link" href={artifactUrl(runId, "report.md")} target="_blank">
          Markdown
        </Anchor>
      ) : null}
    </Group>
  );
}

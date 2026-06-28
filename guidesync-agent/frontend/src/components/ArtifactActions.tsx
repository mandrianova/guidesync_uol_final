import { Anchor, Group } from "@mantine/core";
import { IconDownload, IconExternalLink } from "@tabler/icons-react";

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
            <IconExternalLink size={14} />
            Open report
          </Anchor>
          <Anchor
            className="artifact-link"
            download={`guidesync-${runId}.pdf`}
            href={artifactUrl(runId, "report.pdf")}
          >
            <IconDownload size={14} />
            PDF
          </Anchor>
        </>
      ) : null}
      {hasMarkdown ? (
        <Anchor
          className="artifact-link"
          download={`guidesync-${runId}.md`}
          href={artifactUrl(runId, "report.md")}
        >
          <IconDownload size={14} />
          Markdown
        </Anchor>
      ) : null}
    </Group>
  );
}

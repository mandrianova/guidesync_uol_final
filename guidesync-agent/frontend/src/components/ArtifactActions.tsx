import { Anchor, Group } from "@mantine/core";
import { IconDownload, IconExternalLink } from "@tabler/icons-react";

import { artifactUrl, publicReportUrl } from "../api/client";

interface ArtifactActionsProps {
  runId: string;
  artifacts: Record<string, string>;
}

export function ArtifactActions({ runId, artifacts }: ArtifactActionsProps) {
  const hasPublication = Boolean(artifacts["report.json"]);
  const hasTechnicalMarkdown = Boolean(artifacts["technical-report.md"]);

  if (!hasPublication && !hasTechnicalMarkdown) {
    return null;
  }

  return (
    <Group gap="xs" justify="flex-end" wrap="wrap">
      {hasPublication ? (
        <Anchor className="artifact-link" href={publicReportUrl(runId)} target="_blank">
          <IconExternalLink size={14} />
          Open report
        </Anchor>
      ) : null}
      {hasTechnicalMarkdown ? (
        <Anchor
          className="artifact-link"
          download={`guidesync-${runId}-technical.md`}
          href={artifactUrl(runId, "technical-report.md")}
        >
          <IconDownload size={14} />
          Technical Markdown
        </Anchor>
      ) : null}
    </Group>
  );
}

import { Anchor, Group, Text } from "@mantine/core";
import { IconDownload, IconExternalLink } from "@tabler/icons-react";

import { artifactUrl, publicReportUrl } from "../api/client";

interface ArtifactActionsProps {
  runId: string;
  artifacts: Record<string, string>;
  showPublicationState?: boolean;
}

export function ArtifactActions({
  runId,
  artifacts,
  showPublicationState = false
}: ArtifactActionsProps) {
  const hasPublication = hasPublicationReport(artifacts);
  const hasTechnicalMarkdown = Boolean(artifacts["technical-report.md"]);

  if (!hasPublication && !hasTechnicalMarkdown && !showPublicationState) {
    return null;
  }

  return (
    <Group gap="xs" justify="flex-end" wrap="wrap">
      {hasPublication ? (
        <Anchor className="artifact-link" href={publicReportUrl(runId)} target="_blank">
          <IconExternalLink size={14} />
          Open report
        </Anchor>
      ) : showPublicationState ? (
        <Text c="dimmed" size="xs">
          Public report was not generated for this run.
        </Text>
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

export function hasPublicationReport(artifacts: Record<string, string>): boolean {
  return Boolean(artifacts["report.json"]);
}

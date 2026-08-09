import { Anchor, Button, Group, Text } from "@mantine/core";
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
  const publicationAction = publicationReportAction(runId, artifacts);
  const hasPublication = !publicationAction.disabled;
  const hasTechnicalMarkdown = Boolean(artifacts["technical-report.md"]);

  if (!hasPublication && !hasTechnicalMarkdown && !showPublicationState) {
    return null;
  }

  return (
    <Group gap="xs" justify="flex-end" wrap="wrap">
      {hasPublication ? (
        <Button
          component="a"
          href={publicationAction.href || undefined}
          leftSection={<IconExternalLink size={14} />}
          size="compact-sm"
          target="_blank"
          variant="light"
        >
          Open report
        </Button>
      ) : showPublicationState ? (
        <Group gap={6} wrap="wrap">
          <Button
            disabled
            leftSection={<IconExternalLink size={14} />}
            size="compact-sm"
            variant="light"
          >
            Open report
          </Button>
          <Text c="dimmed" size="xs">
            Not generated for this run.
          </Text>
        </Group>
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

export function publicationReportAction(
  runId: string,
  artifacts: Record<string, string>
): { disabled: boolean; href: string | null } {
  const available = hasPublicationReport(artifacts);
  return {
    disabled: !available,
    href: available ? publicReportUrl(runId) : null
  };
}

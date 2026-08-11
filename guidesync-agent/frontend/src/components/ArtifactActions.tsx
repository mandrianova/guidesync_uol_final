import { Anchor, Button, Group, Text } from "@mantine/core";
import { IconDownload, IconExternalLink, IconPlayerPlay } from "@tabler/icons-react";

import { artifactUrl, publicReportUrl } from "../api/client";
import type { VideoPresentationSummary } from "../types";

interface ArtifactActionsProps {
  runId: string;
  artifacts: Record<string, string>;
  publicationAvailable: boolean;
  showPublicationState?: boolean;
  videoPresentation?: VideoPresentationSummary;
}

export function ArtifactActions({
  runId,
  artifacts,
  publicationAvailable,
  showPublicationState = false,
  videoPresentation
}: ArtifactActionsProps) {
  const publicationAction = publicationReportAction(runId, publicationAvailable);
  const hasPublication = !publicationAction.disabled;
  const hasTechnicalMarkdown = Boolean(artifacts["technical-report.md"]);
  const videoArtifact =
    videoPresentation?.status === "completed"
      ? videoPresentation.video_artifact_name
      : null;

  if (!hasPublication && !hasTechnicalMarkdown && !videoArtifact && !showPublicationState) {
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
      {videoArtifact ? (
        <Button
          component="a"
          href={artifactUrl(runId, videoArtifact)}
          leftSection={<IconPlayerPlay size={14} />}
          size="compact-sm"
          target="_blank"
          variant="light"
        >
          Play video
        </Button>
      ) : null}
    </Group>
  );
}

export function publicationReportAction(
  runId: string,
  available: boolean
): { disabled: boolean; href: string | null } {
  return {
    disabled: !available,
    href: available ? publicReportUrl(runId) : null
  };
}

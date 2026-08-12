import { Anchor, Button, Group, Text } from "@mantine/core";
import {
  IconDownload,
  IconExternalLink,
  IconPlayerPlay,
  IconRefresh
} from "@tabler/icons-react";

import { artifactUrl, publicReportUrl } from "../api/client";
import {
  isVideoActiveStatus,
  isVideoRegeneration,
  videoActionLabel
} from "../lib/videoPresentation";
import type { VideoPresentationSummary } from "../types";

interface ArtifactActionsProps {
  runId: string;
  artifacts: Record<string, string>;
  publicationAvailable: boolean;
  showPublicationState?: boolean;
  videoPresentation?: VideoPresentationSummary;
  videoActionLoading?: boolean;
  onVideoAction?: (regenerate: boolean) => void;
}

export function ArtifactActions({
  runId,
  artifacts,
  publicationAvailable,
  showPublicationState = false,
  videoPresentation,
  videoActionLoading = false,
  onVideoAction
}: ArtifactActionsProps) {
  const publicationAction = publicationReportAction(runId, publicationAvailable);
  const hasPublication = !publicationAction.disabled;
  const hasTechnicalMarkdown = Boolean(artifacts["technical-report.md"]);
  const videoArtifact = videoPresentation?.video_artifact_name || null;
  const videoStatus = videoPresentation?.status || "disabled";
  const videoActive = isVideoActiveStatus(videoStatus);
  const hasVideo = Boolean(videoArtifact);

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
        <>
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
          <Anchor
            className="artifact-link"
            download={`guidesync-${runId}-video.mp4`}
            href={artifactUrl(runId, videoArtifact)}
          >
            <IconDownload size={14} />
            Download video
          </Anchor>
        </>
      ) : null}
      {hasPublication && onVideoAction ? (
        videoActive ? (
          <Button disabled loading={videoActionLoading} size="compact-sm" variant="light">
            Generating video
          </Button>
        ) : (
          <Button
            leftSection={<IconRefresh size={14} />}
            loading={videoActionLoading}
            onClick={() => onVideoAction(isVideoRegeneration(videoStatus, hasVideo))}
            size="compact-sm"
            variant="light"
          >
            {videoActionLabel(videoStatus, hasVideo, videoActionLoading)}
          </Button>
        )
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

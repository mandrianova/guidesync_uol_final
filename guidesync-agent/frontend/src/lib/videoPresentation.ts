import type { VideoPresentationSummary } from "../types";

type VideoPresentationStatus = NonNullable<VideoPresentationSummary["status"]>;

export function isVideoActiveStatus(status: VideoPresentationStatus): boolean {
  return ["queued", "running", "retrying"].includes(status);
}

export function isVideoRegeneration(
  status: VideoPresentationStatus,
  hasVideo: boolean
): boolean {
  return status === "completed" && hasVideo;
}

export function videoActionLabel(
  status: VideoPresentationStatus,
  hasVideo: boolean,
  loading = false
): string {
  if (loading || isVideoActiveStatus(status)) {
    return "Generating video";
  }
  if (isVideoRegeneration(status, hasVideo)) {
    return "Regenerate video";
  }
  if (status === "failed") {
    return "Retry video";
  }
  return "Generate video";
}

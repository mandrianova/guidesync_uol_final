import { Alert, Loader } from "@mantine/core";
import { useEffect, useState } from "react";
import { useLocation, useParams } from "react-router-dom";

import { api } from "../api/client";
import { PublicReleaseReport } from "../features/reports/PublicReleaseReport";
import { isVideoActiveStatus } from "../lib/videoPresentation";
import type { PublicationReport, VideoPresentationSummary } from "../types";

export function PublicReportRoutePage() {
  const { runId = "" } = useParams();
  const location = useLocation();
  const [report, setReport] = useState<PublicationReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [videoPresentation, setVideoPresentation] =
    useState<VideoPresentationSummary | null>(null);
  const [videoActionLoading, setVideoActionLoading] = useState(false);
  const [videoActionError, setVideoActionError] = useState<string | null>(null);
  const [videoRefreshKey, setVideoRefreshKey] = useState(0);

  useEffect(() => {
    document.body.classList.add("public-report-body");
    return () => document.body.classList.remove("public-report-body");
  }, []);

  useEffect(() => {
    let ignore = false;
    setReport(null);
    setVideoPresentation(null);
    setError(null);
    api.getPublicationReport(runId)
      .then((value) => {
        if (!ignore) {
          setReport(value);
          setError(null);
        }
      })
      .catch((reason) => {
        if (!ignore) {
          setReport(null);
          setError(reason instanceof Error ? reason.message : "Report unavailable");
        }
      });
    return () => {
      ignore = true;
    };
  }, [runId]);

  useEffect(() => {
    let ignore = false;
    let videoTimer: number | undefined;
    const loadVideoPresentation = () => {
      api.getVideoPresentation(runId)
        .then((presentation) => {
          if (ignore) {
            return;
          }
          setVideoPresentation(presentation);
          if (isVideoActiveStatus(presentation.status || "disabled")) {
            videoTimer = window.setTimeout(loadVideoPresentation, 3000);
          }
        })
        .catch(() => {
          if (!ignore) {
            setVideoPresentation(null);
          }
        });
    };
    loadVideoPresentation();
    return () => {
      ignore = true;
      if (videoTimer !== undefined) {
        window.clearTimeout(videoTimer);
      }
    };
  }, [runId, videoRefreshKey]);

  const generateVideo = async (regenerate: boolean) => {
    setVideoActionLoading(true);
    setVideoActionError(null);
    try {
      const presentation = await api.generateVideoPresentation(runId, regenerate);
      setVideoPresentation(presentation);
      setVideoRefreshKey((current) => current + 1);
    } catch (reason) {
      setVideoActionError(
        reason instanceof Error ? reason.message : "Could not queue video generation"
      );
    } finally {
      setVideoActionLoading(false);
    }
  };

  useEffect(() => {
    if (report && new URLSearchParams(location.search).get("print") === "1") {
      window.setTimeout(() => window.print(), 250);
    }
  }, [location.search, report]);

  if (error) {
    return <Alert className="public-report-status" color="red" title="Report unavailable">{error}</Alert>;
  }
  if (!report) {
    return <div className="public-report-status"><Loader color="teal" /></div>;
  }
  return (
    <PublicReleaseReport
      report={report}
      runId={runId}
      onVideoAction={(regenerate) => void generateVideo(regenerate)}
      videoActionError={videoActionError}
      videoActionLoading={videoActionLoading}
      videoPresentation={videoPresentation}
    />
  );
}

import { Alert, Loader } from "@mantine/core";
import { useEffect, useState } from "react";
import { useLocation, useParams } from "react-router-dom";

import { api } from "../api/client";
import { PublicReleaseReport } from "../features/reports/PublicReleaseReport";
import type { PublicationReport } from "../types";

export function PublicReportRoutePage() {
  const { runId = "" } = useParams();
  const location = useLocation();
  const [report, setReport] = useState<PublicationReport | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    document.body.classList.add("public-report-body");
    return () => document.body.classList.remove("public-report-body");
  }, []);

  useEffect(() => {
    let ignore = false;
    api.getPublicationReport(runId)
      .then((value) => {
        if (!ignore) setReport(value);
      })
      .catch((reason) => {
        if (!ignore) setError(reason instanceof Error ? reason.message : "Report unavailable");
      });
    return () => {
      ignore = true;
    };
  }, [runId]);

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
  return <PublicReleaseReport report={report} runId={runId} />;
}

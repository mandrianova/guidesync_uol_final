import { Anchor, Badge, Group, Paper, SimpleGrid, Stack, Text } from "@mantine/core";

import { artifactUrl } from "../../api/client";
import type { BrowserScreenshotEvidence } from "../../types";

interface ScreenshotArtifactLinks {
  derivative: string | null;
  manifest: string | null;
  prepared: string | null;
  raw: string | null;
}

export function screenshotArtifactLinks(
  runId: string,
  artifacts: Record<string, string>,
  screenshot: BrowserScreenshotEvidence
): ScreenshotArtifactLinks {
  const preparedName = screenshot.prepared_artifact_name;
  const rawName = screenshot.raw_artifact_name;
  const derivativeName = screenshot.derivative_artifact_name;
  const manifestName = screenshot.edit_manifest_artifact_name;
  return {
    derivative:
      derivativeName && artifacts[derivativeName]
        ? artifactUrl(runId, derivativeName)
        : null,
    manifest:
      manifestName && artifacts[manifestName]
        ? artifactUrl(runId, manifestName)
        : null,
    prepared:
      preparedName && artifacts[preparedName]
        ? artifactUrl(runId, preparedName)
        : null,
    raw: rawName && artifacts[rawName] ? artifactUrl(runId, rawName) : null
  };
}

export function screenshotStatusColor(
  status: BrowserScreenshotEvidence["validation_status"]
): string {
  if (status === "passed") {
    return "teal";
  }
  if (status === "failed") {
    return "red";
  }
  if (status === "skipped") {
    return "gray";
  }
  return "yellow";
}

interface ScreenshotEvidenceCardProps {
  artifacts: Record<string, string>;
  runId: string;
  screenshot: BrowserScreenshotEvidence;
}

export function ScreenshotEvidenceCard({
  artifacts,
  runId,
  screenshot
}: ScreenshotEvidenceCardProps) {
  const links = screenshotArtifactLinks(runId, artifacts, screenshot);
  const viewport = screenshot.viewport || {};
  const errors = [
    ...(screenshot.console_errors || []),
    ...(screenshot.page_errors || []),
    ...(screenshot.failed_requests || [])
  ];
  const warnings = [
    ...(screenshot.validation_reasons || []),
    ...(screenshot.semantic_mismatches || []),
    ...(screenshot.vision_warnings || [])
  ];
  const crop = screenshot.crop;
  const masks = (screenshot.masks || []).map(
    (mask) => `${mask.reason}: ${mask.locator_kind}=${mask.locator}`
  );

  return (
    <Paper className="screenshot-evidence-card" p="md" withBorder>
      <SimpleGrid cols={{ base: 1, md: links.prepared ? 2 : 1 }}>
        {links.prepared ? (
          <a
            aria-label={`Open prepared screenshot for ${screenshot.scenario}`}
            className="screenshot-evidence-preview"
            href={links.prepared}
            rel="noreferrer"
            target="_blank"
          >
            <img
              alt={screenshot.alt_text || `Prepared capture: ${screenshot.scenario}`}
              src={links.prepared}
            />
          </a>
        ) : null}
        <Stack gap="xs">
          <Group justify="space-between" wrap="wrap">
            <div>
              <Text fw={800}>{screenshot.scenario}</Text>
              <Text className="report-breakable" c="dimmed" size="sm">
                {screenshot.title || screenshot.route || screenshot.url}
              </Text>
            </div>
            <Group gap="xs">
              <Badge color="blue" variant="outline">
                attempt {screenshot.attempt}
              </Badge>
              <Badge
                color={screenshotStatusColor(screenshot.validation_status)}
                variant="light"
              >
                {screenshot.validation_status || "not validated"}
              </Badge>
              <Badge color={screenshot.publication_approved ? "teal" : "gray"} variant="outline">
                {screenshot.publication_approved ? "publication approved" : "internal only"}
              </Badge>
            </Group>
          </Group>

          <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="xs">
            <EvidenceValue label="Scenario ID" value={screenshot.scenario_id} />
            <EvidenceValue label="Plan item" value={screenshot.plan_item_id} />
            <EvidenceValue label="Change ID" value={screenshot.change_id} />
            <EvidenceValue label="Claim ID" value={screenshot.claim_id} />
            <EvidenceValue label="Retry of capture" value={screenshot.retry_of_capture_id} />
            <EvidenceValue label="Review verdict" value={screenshot.review_verdict} />
          </SimpleGrid>

          <Text size="sm">
            <strong>Requested:</strong> {screenshot.requested_state || "n/a"}
          </Text>
          <Text size="sm">
            <strong>Observed:</strong> {screenshot.observed_state || screenshot.ui_state || "n/a"}
          </Text>
          <Text c="dimmed" size="xs">
            {screenshot.route || screenshot.url} · {viewport.width || "?"}×
            {viewport.height || "?"} · {screenshot.theme} · attempt {screenshot.attempt}
          </Text>

          <Group gap="sm">
            {links.prepared ? (
              <Anchor href={links.prepared} rel="noreferrer" size="sm" target="_blank">
                Prepared image
              </Anchor>
            ) : null}
            {links.raw ? (
              <Anchor href={links.raw} rel="noreferrer" size="sm" target="_blank">
                Raw audit image
              </Anchor>
            ) : null}
            {links.derivative && links.derivative !== links.prepared ? (
              <Anchor href={links.derivative} rel="noreferrer" size="sm" target="_blank">
                Edited derivative
              </Anchor>
            ) : null}
            {links.manifest ? (
              <Anchor href={links.manifest} rel="noreferrer" size="sm" target="_blank">
                Edit manifest
              </Anchor>
            ) : null}
          </Group>
        </Stack>
      </SimpleGrid>

      <details className="screenshot-evidence-details">
        <summary>Validation, policy, and capture metadata</summary>
        <SimpleGrid cols={{ base: 1, sm: 2 }} mt="sm">
          <Stack gap={4}>
            <EvidenceList label="Matched" values={screenshot.matched_text} />
            <EvidenceList label="Missing" values={screenshot.missing_text} />
            <EvidenceList label="Rejected matches" values={screenshot.matched_rejected_text} />
            <EvidenceList label="Warnings" values={warnings} />
            <EvidenceList label="Browser errors" values={errors} />
          </Stack>
          <Stack gap={4}>
            <EvidenceValue label="Capture ID" value={screenshot.capture_id} />
            <EvidenceValue label="Image hash" value={screenshot.prepared_image_hash} />
            <EvidenceValue label="Raw hash" value={screenshot.raw_image_hash} />
            <EvidenceValue
              label="Prepared size"
              value={
                screenshot.image_width && screenshot.image_height
                  ? `${screenshot.image_width}×${screenshot.image_height}`
                  : null
              }
            />
            <EvidenceValue
              label="Crop"
              value={
                crop
                  ? `${crop.mode} · ${crop.x ?? 0},${crop.y ?? 0} · ${crop.width ?? "?"}×${crop.height ?? "?"}`
                  : null
              }
            />
            <EvidenceList label="Masks" values={masks} />
            <EvidenceValue
              label="Deterministic edits"
              value={
                screenshot.edit_operations?.length
                  ? `${screenshot.edit_operations.length} · ${screenshot.edit_finalized ? "reviewed" : "pending review"}`
                  : null
              }
            />
            <EvidenceValue label="Derivative hash" value={screenshot.derivative_image_hash} />
            <EvidenceValue label="Capture target" value={screenshot.capture_target} />
            <EvidenceValue label="DOM hash" value={screenshot.dom_hash} />
            <EvidenceValue label="ARIA hash" value={screenshot.aria_hash} />
            <EvidenceValue label="Browser" value={screenshot.browser_identity} />
            <EvidenceValue label="Build" value={screenshot.build_identity} />
            <EvidenceValue
              label="Policy"
              value={
                screenshot.policy_audit
                  ? `${screenshot.policy_audit.decision} · ${screenshot.policy_audit.permission} · ${screenshot.policy_audit.risk} · ${screenshot.policy_audit.resource_scope}`
                  : null
              }
            />
            <EvidenceValue label="Worker path" value={screenshot.path} />
          </Stack>
        </SimpleGrid>
      </details>
    </Paper>
  );
}

function EvidenceValue({ label, value }: { label: string; value?: string | null }) {
  return (
    <Text className="report-breakable" c="dimmed" size="xs">
      <strong>{label}:</strong> {value || "n/a"}
    </Text>
  );
}

function EvidenceList({ label, values }: { label: string; values?: string[] }) {
  return (
    <Text className="report-breakable" c="dimmed" size="xs">
      <strong>{label}:</strong> {values?.length ? values.join(", ") : "none"}
    </Text>
  );
}

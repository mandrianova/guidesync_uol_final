import { describe, expect, it } from "vitest";

import type { ProjectConfig } from "../types";
import {
  blankProject,
  filterProjects,
  projectPayload,
  resolveProjectSelection
} from "./projects";

function project(id: string, name: string): ProjectConfig {
  return {
    id,
    name,
    description: null,
    audience: "end_users",
    documentation_instructions: "Keep the guide evidence-based.",
    knowledge_base_repository_id: null,
    knowledge_base_ref: null,
    knowledge_base_path: "docs/",
    analysis_paths: [],
    credential_ref: null,
    task_interface_auth_type: null,
    has_task_interface_auth: false,
    repositories: [],
    documentation: []
  };
}

describe("project selector helpers", () => {
  const projects = Array.from({ length: 35 }, (_, index) =>
    project(
      `project-${index + 1}`,
      index === 31
        ? "Starlight real-project viability final causal retry with a long descriptive name"
        : `Release project ${index + 1}`
    )
  );

  it("filters a long project list by a case-insensitive name fragment", () => {
    expect(filterProjects(projects, "  CAUSAL RETRY ").map((item) => item.id)).toEqual([
      "project-32"
    ]);
    expect(filterProjects(projects, "")).toHaveLength(35);
  });

  it("falls back from a stale saved selection to the first remaining project", () => {
    expect(resolveProjectSelection(projects, "project-deleted")?.id).toBe("project-1");
    expect(resolveProjectSelection([], "project-deleted")).toBeNull();
  });
});

describe("project UI authentication payload", () => {
  it("keeps saved authorization without returning or resending its value", () => {
    const config = {
      ...blankProject(),
      task_interface_auth_type: "local_storage" as const,
      has_task_interface_auth: true,
      task_interface_auth_secret: null,
      task_interface_auth_update: "keep" as const
    };

    const payload = projectPayload(config);

    expect(payload.task_interface_auth_type).toBe("local_storage");
    expect(payload.task_interface_auth_update).toBe("keep");
    expect(payload.task_interface_auth_secret).toBeNull();
  });

  it("sends a replacement only when the user explicitly enters one", () => {
    const config = {
      ...blankProject(),
      task_interface_auth_type: "cookie" as const,
      task_interface_auth_secret: "session=replacement",
      task_interface_auth_update: "replace" as const
    };

    const payload = projectPayload(config);

    expect(payload.task_interface_auth_type).toBe("cookie");
    expect(payload.task_interface_auth_update).toBe("replace");
    expect(payload.task_interface_auth_secret).toBe("session=replacement");
  });
});

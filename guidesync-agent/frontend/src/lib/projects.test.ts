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
    has_task_interface_auth_cookie: false,
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

describe("project UI authentication cookie payload", () => {
  it("keeps a saved cookie without returning or resending its value", () => {
    const config = {
      ...blankProject(),
      has_task_interface_auth_cookie: true,
      task_interface_auth_cookie: null,
      task_interface_auth_cookie_update: "keep" as const
    };

    const payload = projectPayload(config);

    expect(payload.task_interface_auth_cookie_update).toBe("keep");
    expect(payload.task_interface_auth_cookie).toBeNull();
  });

  it("sends a replacement only when the user explicitly enters one", () => {
    const config = {
      ...blankProject(),
      task_interface_auth_cookie: "session=replacement",
      task_interface_auth_cookie_update: "replace" as const
    };

    const payload = projectPayload(config);

    expect(payload.task_interface_auth_cookie_update).toBe("replace");
    expect(payload.task_interface_auth_cookie).toBe("session=replacement");
  });
});

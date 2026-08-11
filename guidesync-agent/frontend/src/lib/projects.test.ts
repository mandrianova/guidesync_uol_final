import { describe, expect, it } from "vitest";

import type { ProjectConfig } from "../types";
import { filterProjects, resolveProjectSelection } from "./projects";

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

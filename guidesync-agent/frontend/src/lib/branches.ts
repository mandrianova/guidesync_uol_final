import type { BranchInfo } from "../types";

export type BranchSortMode = "updated_desc" | "name_asc" | "name_desc";

export function sortBranches(branches: BranchInfo[], sortMode: BranchSortMode): BranchInfo[] {
  return [...branches].sort((left, right) => {
    if (sortMode === "name_desc") {
      return right.name.localeCompare(left.name);
    }
    if (sortMode === "name_asc") {
      return left.name.localeCompare(right.name);
    }
    return String(right.updated_at || "").localeCompare(String(left.updated_at || ""));
  });
}

export function terminalStatus(status: string): boolean {
  return status === "completed" || status === "failed" || status === "cancelled";
}

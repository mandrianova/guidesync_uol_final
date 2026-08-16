import type { ReportChangeScope } from "../types";

export interface ReportScopeDescription {
  label: string;
  value: string;
}

export function describeReportChangeScope(
  scope: ReportChangeScope | null | undefined
): ReportScopeDescription | null {
  const repositories = scope?.repositories || [];
  const periods = repositories.filter((repository) => repository.since || repository.until);
  if (periods.length) {
    const values = periods.map((repository) => ({
      name: repository.name,
      value: formatPeriod(repository.since, repository.until)
    }));
    const uniquePeriods = [...new Set(values.map((item) => item.value))];
    return {
      label: uniquePeriods.length === 1 ? "Change period" : "Change periods",
      value:
        uniquePeriods.length === 1
          ? uniquePeriods[0]
          : values.map((item) => `${item.name}: ${item.value}`).join("; ")
    };
  }

  const branches = repositories
    .filter((repository) => repository.branches?.length)
    .map((repository) => `${repository.name}: ${repository.branches?.join(", ")}`);
  const branchCount = repositories.reduce(
    (count, repository) => count + (repository.branches?.length || 0),
    0
  );
  return branches.length
    ? { label: branchCount === 1 ? "Branch" : "Branches", value: branches.join("; ") }
    : null;
}

function formatPeriod(since?: string | null, until?: string | null): string {
  const start = formatScopeDate(since);
  const end = formatScopeDate(until) || "present";
  return start ? `${start} — ${end}` : `Through ${end}`;
}

function formatScopeDate(value?: string | null): string {
  if (!value) {
    return "";
  }
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) {
    return value;
  }
  return new Intl.DateTimeFormat("en-GB", {
    dateStyle: "medium",
    timeZone: "UTC"
  }).format(new Date(`${value}T00:00:00Z`));
}

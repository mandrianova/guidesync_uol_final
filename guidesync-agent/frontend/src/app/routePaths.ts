import type { PageId } from "../types";

const pagePaths: Record<PageId, string> = {
  "app-settings": "/models",
  knowledge: "/knowledge",
  projects: "/projects",
  reports: "/reports",
  run: "/run",
  settings: "/project"
};

export function pathForPage(page: PageId): string {
  return pagePaths[page];
}

export function pageForPath(pathname: string): PageId {
  if (pathname.startsWith("/models")) {
    return "app-settings";
  }
  if (pathname.startsWith("/projects")) {
    return "projects";
  }
  if (pathname.startsWith("/knowledge")) {
    return "knowledge";
  }
  if (pathname.startsWith("/reports")) {
    return "reports";
  }
  if (pathname.startsWith("/run")) {
    return "run";
  }
  return "settings";
}

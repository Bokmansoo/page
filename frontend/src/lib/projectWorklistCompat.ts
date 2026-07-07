import { apiUrl } from "@/lib/api";

export type ProjectWorklistStatus = "generating" | "needs_review" | "completed" | "failed";

export interface ProjectWorklistItem {
  project_id: string;
  project_name: string;
  status: ProjectWorklistStatus;
  thumbnail_url: string | null;
  result_url: string | null;
  review_url: string | null;
  export_history_url: string;
  last_export_status: string | null;
  updated_at: string;
}

interface ProjectWorklistResponse {
  items: ProjectWorklistItem[];
}

interface LegacyProjectItem {
  id: string;
  name: string;
  status: string;
  updated_at: string;
}

interface LegacyProjectListResponse {
  value?: LegacyProjectItem[];
  items?: LegacyProjectItem[];
}

function mockHeaders(): Record<string, string> {
  if (typeof window === "undefined") return {};
  return {
    "X-Mock-User-Id": localStorage.getItem("X-Mock-User-Id") || "00000000-0000-0000-0000-000000000001",
    "X-Mock-Workspace-Id": localStorage.getItem("X-Mock-Workspace-Id") || "00000000-0000-0000-0000-000000000002",
  };
}

function normalizeStatus(status: string): ProjectWorklistStatus {
  const value = (status || "").toLowerCase();
  if (value === "completed" || value === "needs_review" || value === "failed" || value === "generating") {
    return value;
  }
  if (value === "ready" || value === "review" || value === "reviewing" || value === "checking") {
    return "needs_review";
  }
  if (value === "draft" || value === "processing" || value === "running" || value === "pending") {
    return "generating";
  }
  return "completed";
}

function fromLegacyProject(project: LegacyProjectItem): ProjectWorklistItem {
  return {
    project_id: project.id,
    project_name: project.name,
    status: normalizeStatus(project.status),
    thumbnail_url: null,
    result_url: `/workspace/projects/${project.id}/result`,
    review_url: `/workspace/projects/${project.id}/page-editor?mode=review`,
    export_history_url: `/workspace/exports?project_id=${project.id}`,
    last_export_status: null,
    updated_at: project.updated_at,
  };
}

export async function fetchProjectWorklist(): Promise<ProjectWorklistItem[]> {
  const headers = mockHeaders();
  const response = await fetch(apiUrl("/api/v1/projects/worklist"), {
    headers,
    cache: "no-store",
  });

  if (response.status === 404) {
    const fallbackResponse = await fetch(apiUrl("/api/v1/projects"), {
      headers,
      cache: "no-store",
    });
    if (!fallbackResponse.ok) {
      throw new Error("작업 목록을 불러오지 못했습니다.");
    }
    const fallbackBody = (await fallbackResponse.json()) as LegacyProjectItem[] | LegacyProjectListResponse;
    const projects = Array.isArray(fallbackBody) ? fallbackBody : fallbackBody.value ?? fallbackBody.items ?? [];
    return projects
      .sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime())
      .map(fromLegacyProject);
  }

  if (!response.ok) {
    throw new Error("작업 목록을 불러오지 못했습니다.");
  }
  const body: ProjectWorklistResponse = await response.json();
  return body.items;
}

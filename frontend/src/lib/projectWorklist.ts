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

function mockHeaders(): Record<string, string> {
  if (typeof window === "undefined") return {};
  return {
    "X-Mock-User-Id": localStorage.getItem("X-Mock-User-Id") || "00000000-0000-0000-0000-000000000001",
    "X-Mock-Workspace-Id": localStorage.getItem("X-Mock-Workspace-Id") || "00000000-0000-0000-0000-000000000002",
  };
}

export async function fetchProjectWorklist(): Promise<ProjectWorklistItem[]> {
  const response = await fetch(apiUrl("/api/v1/projects/worklist"), {
    headers: mockHeaders(),
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error("작업 목록을 불러오지 못했습니다.");
  }
  const body: ProjectWorklistResponse = await response.json();
  return body.items;
}

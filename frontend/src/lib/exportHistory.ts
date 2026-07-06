import { apiUrl } from "@/lib/api";

export interface ExportHistoryItem {
  id: string;
  project_id: string;
  project_name: string;
  format: string;
  status: "pending" | "running" | "completed" | "failed";
  filename: string | null;
  content_type: string | null;
  download_url: string | null;
  error_message: string | null;
  created_at: string;
  completed_at: string | null;
}

export interface ExportHistoryResponse {
  items: ExportHistoryItem[];
}

function mockHeaders(): Record<string, string> {
  if (typeof window === "undefined") return {};
  return {
    "X-Mock-User-Id": localStorage.getItem("X-Mock-User-Id") || "00000000-0000-0000-0000-000000000001",
    "X-Mock-Workspace-Id": localStorage.getItem("X-Mock-Workspace-Id") || "00000000-0000-0000-0000-000000000002",
  };
}

export async function fetchExportHistory(): Promise<ExportHistoryItem[]> {
  const response = await fetch(apiUrl("/api/v1/page/exports"), {
    headers: mockHeaders(),
    cache: "no-store",
  });
  if (!response.ok) throw new Error("출력 이력을 불러오지 못했습니다.");
  const body: ExportHistoryResponse = await response.json();
  return body.items;
}

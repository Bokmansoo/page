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

interface LegacyProjectAsset {
  id: string;
  source_type: string;
  filename: string;
  mime_type: string;
}

interface LegacyProjectItem {
  id: string;
  name: string;
  updated_at: string;
  assets?: LegacyProjectAsset[];
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

function extensionFromAsset(asset: LegacyProjectAsset): "png" | "jpg" | null {
  const filename = asset.filename.toLowerCase();
  if (asset.mime_type === "image/png" || filename.endsWith(".png")) return "png";
  if (asset.mime_type === "image/jpeg" || filename.endsWith(".jpg") || filename.endsWith(".jpeg")) return "jpg";
  return null;
}

function historyFromLegacyProjects(projects: LegacyProjectItem[]): ExportHistoryItem[] {
  return projects
    .flatMap((project) =>
      (project.assets ?? [])
        .filter((asset) => asset.source_type === "exported_image")
        .map((asset) => {
          const format = extensionFromAsset(asset) ?? "png";
          return {
            id: asset.id,
            project_id: project.id,
            project_name: project.name,
            format,
            status: "completed" as const,
            filename: asset.filename,
            content_type: asset.mime_type,
            download_url: `/api/v1/projects/${project.id}/page/export/download/${asset.id}`,
            error_message: null,
            created_at: project.updated_at,
            completed_at: project.updated_at,
          };
        }),
    )
    .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());
}

async function fetchLegacyExportHistory(): Promise<ExportHistoryItem[]> {
  const response = await fetch(apiUrl("/api/v1/projects"), {
    headers: mockHeaders(),
    cache: "no-store",
  });
  if (!response.ok) throw new Error("출력 이력을 불러오지 못했습니다.");
  const body = (await response.json()) as LegacyProjectItem[] | LegacyProjectListResponse;
  const projects = Array.isArray(body) ? body : body.value ?? body.items ?? [];
  return historyFromLegacyProjects(projects);
}

export async function fetchExportHistory(): Promise<ExportHistoryItem[]> {
  const response = await fetch(apiUrl("/api/v1/page/exports"), {
    headers: mockHeaders(),
    cache: "no-store",
  });
  if (response.status === 404) {
    return fetchLegacyExportHistory();
  }
  if (!response.ok) throw new Error("출력 이력을 불러오지 못했습니다.");
  const body: ExportHistoryResponse = await response.json();
  return body.items;
}

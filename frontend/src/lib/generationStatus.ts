import { apiUrl } from "@/lib/api";

export type GenerationState =
  | "not_started"
  | "created"
  | "running"
  | "waiting_for_cost_approval"
  | "needs_review"
  | "completed"
  | "failed";

export interface GenerationCost {
  estimated: number;
  actual: number;
  token_input: number;
  token_output: number;
}

export interface GenerationActiveRun {
  id: string;
  status: string;
  current_stage: string;
  estimated_cost: number | null;
  actual_cost: number | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface GenerationStep {
  stage: string;
  status: string;
  estimated_cost: number | null;
  actual_cost: number | null;
  input_tokens: number;
  output_tokens: number;
  error_message: string | null;
}

export interface GenerationImageJobs {
  total: number;
  planned: number;
  awaiting_cost_approval: number;
  generating: number;
  needs_review: number;
  approved: number;
  failed: number;
}

export interface GenerationExportJobs {
  total: number;
  latest_status: string;
}

export interface GenerationProjectStatus {
  project_id: string;
  project_name: string;
  state: GenerationState;
  current_stage: string;
  failed_stage?: string | null;
  progress_percent: number;
  can_start_new_run: boolean;
  recommended_action: string;
  result_url?: string | null;
  review_url?: string | null;
  active_run?: GenerationActiveRun | null;
  steps?: GenerationStep[];
  image_jobs?: GenerationImageJobs;
  export_jobs?: GenerationExportJobs;
  cost: GenerationCost;
  last_error?: string | null;
  updated_at: string;
}

export interface GenerationStatusDashboard {
  summary: {
    running: number;
    waiting_for_cost_approval: number;
    needs_review: number;
    completed: number;
    failed: number;
    estimated_cost: number;
    actual_cost: number;
  };
  projects: GenerationProjectStatus[];
}

export function mockHeaders(): Record<string, string> {
  if (typeof window === "undefined") return {};
  return {
    "X-Mock-User-Id": localStorage.getItem("X-Mock-User-Id") || "00000000-0000-0000-0000-000000000001",
    "X-Mock-Workspace-Id": localStorage.getItem("X-Mock-Workspace-Id") || "00000000-0000-0000-0000-000000000002",
  };
}

export async function fetchGenerationStatusDashboard(): Promise<GenerationStatusDashboard> {
  const response = await fetch(apiUrl("/api/v1/operations/generation-status"), {
    headers: mockHeaders(),
  });
  if (!response.ok) {
    throw new Error("작업 상태를 불러오지 못했습니다.");
  }
  return response.json();
}

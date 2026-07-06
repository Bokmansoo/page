export const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8001";

export function apiUrl(path: string): string {
  return `${API_BASE_URL}${path.startsWith("/") ? path : `/${path}`}`;
}

export type StructuredIntakeDraft = {
  product_name: { value: string; source: string; confidence: string };
  description?: { value: string; source: string; confidence: string };
  product_url?: { value: string; source: string; confidence: string };
  reference_urls: string[];
  selling_points: Array<{ text: string; source: string; confidence: string }>;
  price?: { value: string; source: string; confidence: string };
  shipping?: { value: string; source: string; confidence: string };
  desired_mood: string[];
  asset_ids?: string[];
  warnings: string[];
};

export async function structureIntake(
  payload: {
    freeform_input: string;
    product_name?: string;
    description?: string;
    product_url?: string;
    reference_urls?: string[];
    desired_mood?: string;
    asset_ids?: string[];
  },
  headers: Record<string, string> = {}
): Promise<StructuredIntakeDraft> {
  const res = await fetch(apiUrl("/api/agent-runs/structure-intake"), {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...headers,
    },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    throw new Error("상품 자료를 정리하지 못했습니다.");
  }
  return res.json();
}

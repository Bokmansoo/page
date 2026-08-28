"use client";

import { useCallback, useEffect, useState } from "react";
import { apiUrl } from "@/lib/api";

type ScenePrompt = {
  id: string;
  scene_id: string;
  section_id: string;
  scene_type: string;
  version: number;
  status: string;
  objective: string;
  reference_asset_ids: string[];
  prompt_hash: string;
  reference_hash: string;
  prompt_version: string;
  provider: string;
  model: string;
  size: string;
  expected_cost: number;
  logo_policy: string;
  seller_adjustment?: string | null;
  instruction_priority?: string[];
  rights_snapshot?: Array<Record<string, unknown>>;
  stale_reason?: string | null;
  stale_impact?: Record<string, unknown>;
};

function errorMessage(payload: unknown, fallback: string) {
  if (typeof payload === "string" && payload.trim()) return payload;
  if (payload && typeof payload === "object") {
    const detail = (payload as { detail?: unknown }).detail;
    if (typeof detail === "string" && detail.trim()) return detail;
    if (detail && typeof detail === "object") {
      const item = detail as { message?: unknown; code?: unknown };
      const message = typeof item.message === "string" ? item.message : "";
      const code = typeof item.code === "string" ? item.code : "";
      if (message || code) return [code, message].filter(Boolean).join(" · ");
    }
  }
  return fallback;
}

export default function ScenePromptReviewPanel({ projectId }: { projectId: string }) {
  const [items, setItems] = useState<ScenePrompt[]>([]);
  const [adjustments, setAdjustments] = useState<Record<string, string>>({});
  const [busySceneId, setBusySceneId] = useState<string | null>(null);
  const [message, setMessage] = useState<{ kind: "success" | "error"; text: string } | null>(null);

  const load = useCallback(async () => {
    const response = await fetch(apiUrl(`/api/v1/projects/${projectId}/scene-prompts`), {
      credentials: "include",
      cache: "no-store",
    });
    const payload = await response.json().catch(() => null);
    if (!response.ok) throw new Error(errorMessage(payload, "장면 프롬프트를 불러오지 못했습니다."));
    const nextItems = (payload?.items || []) as ScenePrompt[];
    setItems(nextItems);
    setAdjustments((current) => {
      const next = { ...current };
      for (const item of nextItems) {
        if (!(item.scene_id in next)) next[item.scene_id] = item.seller_adjustment || "";
      }
      return next;
    });
  }, [projectId]);

  useEffect(() => {
    void load().catch((error) => setMessage({
      kind: "error",
      text: error instanceof Error ? error.message : "장면 프롬프트를 불러오지 못했습니다.",
    }));
  }, [load]);

  const save = async (item: ScenePrompt) => {
    setBusySceneId(item.scene_id);
    setMessage(null);
    try {
      const response = await fetch(apiUrl(`/api/v1/projects/${projectId}/scene-prompts/${item.scene_id}`), {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ seller_adjustment: adjustments[item.scene_id] || "" }),
      });
      const payload = await response.json().catch(() => null);
      if (!response.ok) throw new Error(errorMessage(payload, "프롬프트 수정 내용을 저장하지 못했습니다."));
      setItems((current) => current.map((candidate) => candidate.scene_id === item.scene_id ? payload as ScenePrompt : candidate));
      setAdjustments((current) => ({ ...current, [item.scene_id]: (payload as ScenePrompt).seller_adjustment || "" }));
      setMessage({ kind: "success", text: "이 장면만 새 프롬프트 버전으로 교체했습니다. 다른 장면은 그대로 유지됩니다." });
    } catch (error) {
      setMessage({ kind: "error", text: error instanceof Error ? error.message : "프롬프트 수정에 실패했습니다." });
    } finally {
      setBusySceneId(null);
    }
  };

  if (!items.length && !message) return <p className="rounded-xl border border-slate-200 bg-white p-4 text-sm text-slate-500">장면 프롬프트를 불러오는 중입니다.</p>;

  return (
    <section className="rounded-2xl border border-violet-200 bg-white p-5" data-testid="scene-prompt-review-panel">
      <div>
        <h3 className="font-extrabold text-slate-900">비용 승인 전 장면 프롬프트 검수</h3>
        <p className="mt-1 text-xs leading-5 text-slate-600">장면별 목적·기준 사진·버전·해시를 확인하고, 필요한 장면만 수정하세요. 이미지 안의 최종 한국어 문구와 정확한 로고는 별도 렌더러가 합성합니다.</p>
      </div>
      {message && <p role="status" className={`mt-3 rounded-lg border px-3 py-2 text-xs ${message.kind === "success" ? "border-emerald-200 bg-emerald-50 text-emerald-800" : "border-rose-200 bg-rose-50 text-rose-800"}`}>{message.text}</p>}
      <div className="mt-4 space-y-3">
        {items.map((item) => (
          <details key={item.id} data-testid={`scene-prompt-${item.scene_id}`} className="rounded-xl border border-violet-100 bg-violet-50/50 p-4 text-xs text-slate-700">
            <summary className="cursor-pointer font-bold text-violet-950">{item.scene_type} · v{item.version} · {item.status}</summary>
            <div className="mt-3 grid gap-2 md:grid-cols-2">
              <p><b>목표</b> {item.objective}</p>
              <p><b>기준 사진</b> {item.reference_asset_ids.length}장</p>
              <p><b>Prompt hash</b> <code>{item.prompt_hash.slice(0, 12)}</code></p>
              <p><b>Reference hash</b> <code>{item.reference_hash.slice(0, 12)}</code></p>
              <p><b>컴파일러</b> {item.prompt_version}</p>
              <p><b>모델</b> {item.provider}/{item.model} · {item.size}</p>
              <p><b>예상 비용</b> {item.expected_cost} credit</p>
              <p><b>텍스트·로고</b> {item.logo_policy === "renderer_only" ? "renderer-only 합성" : "사용 안 함"}</p>
              <p><b>권리 스냅샷</b> {item.rights_snapshot?.length || 0}건</p>
              <p><b>명령 우선순위</b> {(item.instruction_priority || []).join(" → ")}</p>
            </div>
            <label className="mt-3 block font-bold text-slate-800" htmlFor={`scene-adjustment-${item.scene_id}`}>이 장면만 수정</label>
            <textarea
              id={`scene-adjustment-${item.scene_id}`}
              data-testid={`scene-adjustment-${item.scene_id}`}
              value={adjustments[item.scene_id] ?? item.seller_adjustment ?? ""}
              onChange={(event) => setAdjustments((current) => ({ ...current, [item.scene_id]: event.target.value }))}
              placeholder="예: 밝은 스튜디오 배경, 제품 중앙 배치, 이미지 안 글자 없음"
              className="mt-2 min-h-20 w-full rounded-lg border border-slate-200 bg-white p-2 text-xs"
            />
            <button
              type="button"
              data-testid={`scene-adjustment-save-${item.scene_id}`}
              onClick={() => void save(item)}
              disabled={busySceneId === item.scene_id}
              className="mt-2 rounded-lg border border-violet-300 bg-white px-3 py-2 text-xs font-bold text-violet-800 disabled:opacity-50"
            >
              {busySceneId === item.scene_id ? "저장 중…" : "이 장면 새 버전 저장"}
            </button>
          </details>
        ))}
      </div>
    </section>
  );
}

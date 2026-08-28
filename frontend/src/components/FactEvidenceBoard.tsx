"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { apiUrl } from "@/lib/api";

const SESSION_HEADERS: Record<string, string> = {};

type BBox = { x?: number; y?: number; width?: number; height?: number; left?: number; top?: number; w?: number; h?: number };
type Evidence = {
  id: string;
  source_type: string;
  source_url?: string | null;
  source_asset_id?: string | null;
  original_text: string;
  translated_text?: string | null;
  bbox?: BBox | null;
  confidence?: number | null;
  extractor_version?: string | null;
  ocr_language?: string | null;
  ocr_provider?: string | null;
  ocr_model?: string | null;
};
type Impact = {
  page_section_ids: string[];
  page_version_ids: string[];
  detail_page_version_ids: string[];
  storyboard_card_ids: string[];
};
type Fact = {
  id: string;
  fact_text: string;
  verification_status: string;
  needs_review: boolean;
  risk_flags?: string[] | null;
  field_key?: string | null;
  normalized_value?: string | null;
  normalized_unit?: string | null;
  scope?: string | null;
  model_option?: string | null;
  original_text?: string | null;
  translated_text?: string | null;
  evidences: Evidence[];
  affected_section_ids: string[];
  impact: Impact;
};
type Board = {
  cards: Fact[];
  usable_for_generation: string[];
  blocked_fact_ids: string[];
  blockers: { fact_id: string; code: string; message: string }[];
};
type Asset = { id: string; filename: string; ocr_text?: string | null; usage_status?: string | null; asset_role?: string | null };

const labels: Record<string, string> = {
  extracted: "추출됨",
  source_confirmed: "출처 확인",
  seller_confirmed: "판매자 확정",
  needs_review: "검토 필요",
  conflicted: "충돌",
  rejected: "제외",
};

async function apiRequest(path: string, init?: RequestInit) {
  const response = await fetch(apiUrl(path), {
    ...init,
    headers: { ...SESSION_HEADERS, ...(init?.headers || {}) },
    credentials: "include",
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    const detail = payload?.detail;
    throw new Error(typeof detail === "string" ? detail : detail?.message || "요청을 처리하지 못했습니다.");
  }
  return response;
}

function EvidencePreview({ preview, onClose }: { preview: { src: string; text: string; bbox?: BBox | null }; onClose: () => void }) {
  const [size, setSize] = useState({ width: 0, height: 0 });
  const bbox = preview.bbox;
  const x = bbox?.x ?? bbox?.left ?? 0;
  const y = bbox?.y ?? bbox?.top ?? 0;
  const width = bbox?.width ?? bbox?.w ?? 0;
  const height = bbox?.height ?? bbox?.h ?? 0;
  const normalized = Math.max(x, y, width, height) <= 1;
  const overlay = bbox && size.width && size.height ? {
    left: `${normalized ? x * 100 : x / size.width * 100}%`,
    top: `${normalized ? y * 100 : y / size.height * 100}%`,
    width: `${normalized ? width * 100 : width / size.width * 100}%`,
    height: `${normalized ? height * 100 : height / size.height * 100}%`,
  } : null;

  return <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/70 p-6" onClick={onClose}>
    <div className="max-h-full w-full max-w-4xl overflow-auto rounded-xl bg-white p-4" onClick={(event) => event.stopPropagation()}>
      <div className="mb-3 flex justify-between gap-4"><p className="text-sm font-semibold">{preview.text}</p><button onClick={onClose} className="text-sm font-semibold">닫기</button></div>
      <div className="relative mx-auto w-fit max-w-full">
        <img src={preview.src} alt="OCR 근거 원본" className="max-h-[72vh] max-w-full object-contain" onLoad={(event) => setSize({ width: event.currentTarget.naturalWidth, height: event.currentTarget.naturalHeight })} />
        {overlay && <div className="pointer-events-none absolute border-4 border-red-500 bg-red-400/20" style={overlay} />}
      </div>
      {bbox && <p className="mt-2 text-sm text-slate-600">빨간 상자가 OCR 근거 위치입니다.</p>}
    </div>
  </div>;
}

export default function FactEvidenceBoard({ projectId }: { projectId: string }) {
  const [board, setBoard] = useState<Board | null>(null);
  const [tab, setTab] = useState<"confirmed" | "review" | "conflicted">("review");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [preview, setPreview] = useState<{ src: string; text: string; bbox?: BBox | null } | null>(null);
  const [assets, setAssets] = useState<Asset[]>([]);
  const [selectedAssetIds, setSelectedAssetIds] = useState<string[]>([]);
  const [ocrMessage, setOcrMessage] = useState<string | null>(null);

  const load = useCallback(async (refresh = false) => {
    setLoading(true); setError(null);
    try {
      const response = await apiRequest(`/api/v1/projects/${projectId}/facts/evidence-board${refresh ? "/refresh" : ""}`, { method: refresh ? "POST" : "GET" });
      setBoard(await response.json());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "사실·증거 보드를 불러오지 못했습니다.");
    } finally { setLoading(false); }
  }, [projectId]);

  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    void apiRequest(`/api/v1/projects/${projectId}`).then((response) => response.json()).then((project) => {
      const nextAssets = (project.assets || []).filter((asset: Asset) => asset.usage_status !== "blocked");
      setAssets(nextAssets);
    }).catch(() => setAssets([]));
  }, [projectId]);

  const extractOcrCandidates = async () => {
    if (!selectedAssetIds.length) { setOcrMessage("한국어 정보 후보로 추출할 참고 사진을 선택하세요."); return; }
    setLoading(true); setError(null); setOcrMessage(null);
    try {
      const response = await apiRequest(`/api/v1/projects/${projectId}/facts/ocr-candidates`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ asset_ids: selectedAssetIds }),
      });
      const payload = await response.json();
      const completed = (payload.results || []).filter((item: { status: string }) => item.status === "completed").length;
      const needsInput = (payload.results || []).filter((item: { status: string }) => item.status !== "completed").length;
      setOcrMessage(`${completed}개 사진에서 사실 후보를 추가했습니다.${needsInput ? ` ${needsInput}개 사진은 재시도 또는 직접 입력이 필요합니다.` : " 판매자 확인 전에는 생성에 사용되지 않습니다."}`);
      await load();
    } catch (reason) { setError(reason instanceof Error ? reason.message : "OCR 후보를 만들지 못했습니다."); }
    finally { setLoading(false); }
  };

  const cards = useMemo(() => (board?.cards || []).filter((fact) => {
    if (tab === "confirmed") return ["source_confirmed", "seller_confirmed"].includes(fact.verification_status) && !fact.needs_review;
    if (tab === "conflicted") return fact.verification_status === "conflicted";
    return !["source_confirmed", "seller_confirmed", "rejected", "conflicted"].includes(fact.verification_status) || fact.needs_review;
  }), [board, tab]);

  const confirmFacts = async (facts: Fact[]) => {
    const candidates = facts.filter((fact) => fact.evidences.length > 0 && fact.verification_status !== "conflicted");
    if (!candidates.length) { setError("확정 가능한 근거가 있는 사실 카드가 없습니다."); return; }
    const hasRisk = candidates.some((fact) => (fact.risk_flags || []).length > 0);
    if (hasRisk && !window.confirm("효능·인증·친환경·저소음 또는 성능 표현이 포함되어 있습니다. 근거와 표현을 직접 확인했나요?")) return;
    try {
      await apiRequest(`/api/v1/projects/${projectId}/facts/evidence-board/confirm`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ fact_ids: candidates.map((fact) => fact.id), risk_acknowledged: hasRisk, note: hasRisk ? "위험 표현 판매자 재확인" : "판매자 일괄 확인" }),
      });
      await load();
    } catch (reason) { setError(reason instanceof Error ? reason.message : "사실을 확정하지 못했습니다."); }
  };

  const resolve = async (fact: Fact) => {
    const hasRisk = (fact.risk_flags || []).length > 0;
    if (hasRisk && !window.confirm("위험 표현의 근거를 확인하고 이 후보를 선택할까요?")) return;
    try {
      await apiRequest(`/api/v1/projects/${projectId}/facts/evidence-board/conflicts/resolve`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ selected_fact_id: fact.id, note: "판매자 후보 선택", risk_acknowledged: hasRisk }),
      });
      await load();
    } catch (reason) { setError(reason instanceof Error ? reason.message : "충돌 후보를 확정하지 못했습니다."); }
  };

  const edit = async (fact: Fact) => {
    const value = window.prompt("정규화 값을 수정하세요.", fact.normalized_value || ""); if (value === null) return;
    const unit = window.prompt("단위를 수정하세요. (없으면 비워 두세요)", fact.normalized_unit || ""); if (unit === null) return;
    const model = window.prompt("적용 모델/옵션을 입력하세요. (공통이면 비워 두세요)", fact.model_option || ""); if (model === null) return;
    try {
      await apiRequest(`/api/v1/projects/${projectId}/facts/${fact.id}`, {
        method: "PATCH", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ normalized_value: value.trim() || null, normalized_unit: unit.trim() || null, model_option: model.trim() || null }),
      });
      await load();
    } catch (reason) { setError(reason instanceof Error ? reason.message : "사실 카드 수정 내용을 저장하지 못했습니다."); }
  };

  const reject = async (fact: Fact) => {
    if (!window.confirm("이 사실을 생성 입력에서 명시적으로 제외할까요?")) return;
    try {
      await apiRequest(`/api/v1/projects/${projectId}/facts/${fact.id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ verification_status: "rejected" }) });
      await load();
    } catch (reason) { setError(reason instanceof Error ? reason.message : "사실 카드를 제외하지 못했습니다."); }
  };

  const addEvidence = async (fact: Fact) => {
    const originalText = window.prompt("추가할 판매자 근거 원문을 입력하세요."); if (!originalText?.trim()) return;
    try {
      await apiRequest(`/api/v1/projects/${projectId}/facts/evidence-board/${fact.id}/evidence`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ source_type: "seller_input", original_text: originalText.trim() }) });
      await load();
    } catch (reason) { setError(reason instanceof Error ? reason.message : "근거를 추가하지 못했습니다."); }
  };

  const usableFacts = (board?.cards || []).filter((fact) => board?.usable_for_generation.includes(fact.id));
  return <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div><h2 className="text-xl font-bold text-slate-900">사실·증거 보드</h2><p className="mt-1 text-sm text-slate-500">원문·번역·수치 단위·모델·OCR 위치를 확인한 사실만 다음 생성에 사용합니다.</p></div>
      <button className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50" disabled={loading} onClick={() => void load(true)}>{loading ? "분석 중…" : "사실 카드 갱신"}</button>
    </div>
    <div className="mt-4 flex flex-wrap items-center gap-2">
      {(["confirmed", "review", "conflicted"] as const).map((key) => <button key={key} onClick={() => setTab(key)} className={`rounded-full px-3 py-1.5 text-sm ${tab === key ? "bg-slate-900 text-white" : "bg-slate-100 text-slate-700"}`}>{key === "confirmed" ? "확정됨" : key === "review" ? "검토 필요" : "충돌"}</button>)}
      {tab === "review" && <button onClick={() => void confirmFacts(cards)} className="ml-auto rounded-lg border border-emerald-300 px-3 py-1.5 text-sm font-semibold text-emerald-700">현재 검토 카드 일괄 확인</button>}
    </div>
    <section className="mt-4 rounded-xl border border-violet-200 bg-violet-50 p-3">
      <p className="text-sm font-semibold text-violet-950">참고 사진에서 한국어 정보 후보 추출</p>
      <p className="mt-1 text-xs text-violet-800">외국어·OCR 사진은 최종 이미지에 사용하지 않습니다. 원문·번역·OCR 위치가 있는 사실 후보만 추가하며, 판매자 확인 전에는 카피에 쓰지 않습니다.</p>
      <div className="mt-2 flex flex-wrap gap-2">{assets.map((asset) => { const selected = selectedAssetIds.includes(asset.id); return <button type="button" key={asset.id} disabled={loading} onClick={() => setSelectedAssetIds((current) => selected ? current.filter((id) => id !== asset.id) : [...current, asset.id])} className={`rounded-lg border px-2 py-1 text-xs font-semibold ${selected ? "border-violet-400 bg-white text-violet-800" : "border-violet-200 text-violet-700"}`}>{selected ? "선택 ✓" : "선택"}: {asset.filename}</button>; })}</div>
      <button type="button" disabled={loading || !selectedAssetIds.length} onClick={() => void extractOcrCandidates()} className="mt-3 rounded-lg bg-violet-600 px-3 py-2 text-sm font-semibold text-white disabled:opacity-50">{loading ? "추출 중…" : "한국어 정보 후보 추출"}</button>
      {ocrMessage && <p className="mt-2 text-xs font-medium text-violet-800">{ocrMessage}</p>}
    </section>
    {error && <p className="mt-3 rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</p>}
    <div className="mt-3 rounded-xl bg-emerald-50 p-3 text-sm text-emerald-900">
      <p className="font-semibold">생성 사용 가능 {usableFacts.length}개 · 확인/제외 필요 {board?.blocked_fact_ids.length ?? 0}개</p>
      {usableFacts.length > 0 && <ul className="mt-2 list-disc pl-5">{usableFacts.map((fact) => <li key={fact.id}>{fact.fact_text}{fact.model_option ? ` (${fact.model_option})` : ""}</li>)}</ul>}
    </div>
    {(board?.blockers || []).length > 0 && <div className="mt-3 rounded-xl bg-amber-50 p-3 text-sm text-amber-800"><p className="font-semibold">Sprint 4 진입 전 처리할 항목</p><ul className="mt-1 list-disc pl-5">{board?.blockers.map((item) => <li key={`${item.fact_id}-${item.code}`}>{item.message}</li>)}</ul></div>}
    <div className="mt-4 grid gap-3">
      {cards.map((fact) => <article key={fact.id} className="rounded-xl border border-slate-200 p-4">
        <div className="flex items-start justify-between gap-3"><div><p className="font-semibold text-slate-900">{fact.fact_text}</p><p className="mt-1 text-sm text-slate-600">정규화: {fact.normalized_value || "—"}{fact.normalized_unit || ""} · 범위: {fact.scope || "product"}{fact.model_option ? ` · 모델/옵션: ${fact.model_option}` : ""}</p></div><span className="rounded-full bg-amber-50 px-2 py-1 text-xs font-semibold text-amber-700">{labels[fact.verification_status] || fact.verification_status}</span></div>
        {(fact.risk_flags || []).length > 0 && <p className="mt-2 rounded-lg bg-red-50 p-2 text-xs font-semibold text-red-700">위험 표현 재확인 필요: {fact.risk_flags?.join(", ")}</p>}
        <div className="mt-3 space-y-2">{fact.evidences.map((evidence) => <div key={evidence.id} className="rounded-lg bg-slate-50 p-3 text-sm"><p><b>{evidence.source_type}</b> · {evidence.original_text}</p>{evidence.translated_text && <p className="mt-1 text-slate-600">번역: {evidence.translated_text}</p>}<p className="mt-1 text-xs text-slate-500">신뢰도: {evidence.confidence == null ? "—" : `${Math.round(evidence.confidence * 100)}%`} · 추출기: {evidence.extractor_version || "—"}{evidence.ocr_language ? ` · 언어: ${evidence.ocr_language}` : ""}{evidence.ocr_provider ? ` · 제공자: ${evidence.ocr_provider}` : ""}</p>{evidence.source_url && <a href={evidence.source_url} target="_blank" rel="noreferrer" className="mt-1 block text-xs font-semibold text-emerald-700 underline">출처 URL 열기</a>}{evidence.source_asset_id && <button className="mt-2 text-xs font-semibold text-emerald-700 underline" onClick={() => setPreview({ src: apiUrl(`/api/v1/files/assets/${evidence.source_asset_id}`), text: evidence.original_text, bbox: evidence.bbox })}>근거 이미지·OCR 위치 확대</button>}</div>)}</div>
        <div className="mt-3 flex flex-wrap gap-2"><button onClick={() => void edit(fact)} className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-700">값·단위·모델 수정</button><button onClick={() => void addEvidence(fact)} className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-700">근거 추가</button>{fact.verification_status === "conflicted" ? <button onClick={() => void resolve(fact)} className="rounded-lg bg-emerald-600 px-3 py-2 text-sm font-semibold text-white">이 후보로 충돌 해결</button> : !["seller_confirmed", "source_confirmed", "rejected"].includes(fact.verification_status) && <button onClick={() => void confirmFacts([fact])} className="rounded-lg bg-emerald-600 px-3 py-2 text-sm font-semibold text-white">판매자 확인</button>}<button onClick={() => void reject(fact)} className="rounded-lg border border-red-200 px-3 py-2 text-sm font-semibold text-red-700">명시적으로 제외</button></div>
        {(fact.impact.page_section_ids.length + fact.impact.page_version_ids.length + fact.impact.detail_page_version_ids.length + fact.impact.storyboard_card_ids.length) > 0 && <p className="mt-3 text-xs text-amber-700">수정 영향: 섹션 {fact.impact.page_section_ids.length} · 페이지 버전 {fact.impact.page_version_ids.length + fact.impact.detail_page_version_ids.length} · 스토리보드 {fact.impact.storyboard_card_ids.length}</p>}
      </article>)}
      {!loading && cards.length === 0 && <p className="rounded-lg bg-slate-50 p-4 text-sm text-slate-500">이 상태의 사실 카드가 없습니다.</p>}
    </div>
    {preview && <EvidencePreview preview={preview} onClose={() => setPreview(null)} />}
  </section>;
}

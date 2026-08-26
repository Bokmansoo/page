"use client";

import React, { useEffect, useState } from "react";
import { apiUrl } from "@/lib/api";
import PlanningDraftCard, { PlanningCard } from "./PlanningDraftCard";
import StoryboardImageGenerationPanel from "./StoryboardImageGenerationPanel";
import ApiReadyGenerationPlanPanel from "./ApiReadyGenerationPlanPanel";

export interface StoryboardRecommendation {
  key: string;
  label: string;
  reason: string;
  visual_mode: string;
  cards: PlanningCard[];
  missing_images?: Array<{ section_id: string; requirement: string; scene_request?: string | null }>;
  warnings?: string[];
  estimated_cost?: number;
  facts_stale?: boolean;
}

export interface StoryboardDraft {
  cards: PlanningCard[];
  storyboard_version?: number;
  selected_candidate_key?: string | null;
  recommendations?: StoryboardRecommendation[];
  fact_snapshot_id?: string | null;
  status?: string;
  stale_fact_ids?: string[];
  estimated_cost?: number;
  revision?: number;
  revision_history?: Array<{ revision: number; action: string; selected_candidate_key?: string | null }>;
}

interface PlanningDraftEditorProps {
  projectId: string;
  initialDraft: StoryboardDraft;
  graphRunId?: string | null;
  graphReviewStage?: string | null;
}

const defaultHeaders = () => ({ "Content-Type": "application/json" });

export default function PlanningDraftEditor({ projectId, initialDraft, graphRunId, graphReviewStage }: PlanningDraftEditorProps) {
  const [draft, setDraft] = useState<StoryboardDraft>(initialDraft);
  const [isSaving, setIsSaving] = useState(false);
  const [isApproving, setIsApproving] = useState(false);
  const [isRegenerating, setIsRegenerating] = useState(false);
  const [message, setMessage] = useState<{ type: "success" | "error"; text: string } | null>(null);
  const cards = draft.cards || [];
  const enabledCards = cards.filter((card) => card.is_enabled);
  const assetCounts = enabledCards.reduce<Record<string, number>>((counts, card) => {
    if (card.image_asset_id) counts[card.image_asset_id] = (counts[card.image_asset_id] || 0) + 1;
    return counts;
  }, {});
  const repeatedAssetCount = Object.values(assetCounts).filter((count) => count > 1).length;
  const graphPlanningReview = Boolean(graphRunId) && graphReviewStage === "planning_review";
  const graphGenerationPending = Boolean(graphRunId) && graphReviewStage === "generation_pending";
  const showApprovalAction = !graphRunId || graphPlanningReview;

  useEffect(() => {
    if (graphRunId && graphReviewStage !== "planning_review") setMessage(null);
  }, [graphRunId, graphReviewStage]);

  const replaceDraft = (next: StoryboardDraft) => setDraft({ ...next, cards: next.cards || [] });
  const updateCards = (nextCards: PlanningCard[]) => setDraft((current) => ({ ...current, cards: nextCards }));
  const handleCardChange = (index: number, card: PlanningCard) => updateCards(cards.map((item, i) => i === index ? card : item));
  const handleMoveCard = (index: number, direction: "up" | "down") => {
    const swapIndex = direction === "up" ? index - 1 : index + 1;
    if (swapIndex < 0 || swapIndex >= cards.length) return;
    const next = [...cards];
    [next[index], next[swapIndex]] = [next[swapIndex], next[index]];
    updateCards(next.map((card, sort_order) => ({ ...card, sort_order })));
  };

  const request = async (path: string, method: "POST" | "PATCH", body?: object) => {
    const res = await fetch(apiUrl(`/api/v1/projects/${projectId}${path}`), {
      method,
      headers: defaultHeaders(),
      credentials: "include",
      body: body ? JSON.stringify(body) : undefined,
    });
    if (!res.ok) {
      const detail = await res.json().catch(() => null);
      throw new Error(detail?.detail || "스토리보드를 처리하지 못했습니다.");
    }
    return res.json() as Promise<StoryboardDraft>;
  };

  const saveDraft = async () => {
    const next = await request("/planning-draft", "PATCH", { ...draft, cards });
    replaceDraft(next);
  };

  const handleSaveDraft = async () => {
    setIsSaving(true); setMessage(null);
    try { await saveDraft(); setMessage({ type: "success", text: "스토리보드 초안이 저장되었습니다." }); }
    catch (error) { setMessage({ type: "error", text: error instanceof Error ? error.message : "저장에 실패했습니다." }); }
    finally { setIsSaving(false); }
  };

  const handleRegenerate = async () => {
    setIsRegenerating(true); setMessage(null);
    try {
      const next = await request("/storyboard/recommendations", "POST");
      replaceDraft(next);
      setMessage({ type: "success", text: "확정 사실과 자산 상태를 반영한 스토리보드 후보 3개를 만들었습니다." });
    } catch (error) { setMessage({ type: "error", text: error instanceof Error ? error.message : "재생성에 실패했습니다." }); }
    finally { setIsRegenerating(false); }
  };

  const handleSelectRecommendation = async (candidateKey: string) => {
    setIsSaving(true); setMessage(null);
    try {
      const next = await request("/storyboard/select", "POST", { candidate_key: candidateKey });
      replaceDraft(next);
      setMessage({ type: "success", text: "선택한 스토리보드 흐름을 편집 중입니다." });
    } catch (error) { setMessage({ type: "error", text: error instanceof Error ? error.message : "후보 선택에 실패했습니다." }); }
    finally { setIsSaving(false); }
  };

  const handleApprove = async () => {
    if (graphRunId && !graphPlanningReview) return;
    setIsApproving(true); setMessage(null);
    try {
      if (graphRunId) {
        const stateResponse = await fetch(apiUrl(`/api/v1/graph-runs/${graphRunId}`), { credentials: "include", cache: "no-store" });
        const state = await stateResponse.json().catch(() => null);
        if (!stateResponse.ok) throw new Error(state?.detail || "승인 상태를 불러오지 못했습니다.");
        const pending = state?.values?.review?.pending;
        if (!pending || pending.review_stage !== "planning_review") {
          throw new Error("현재 실행은 스토리보드 승인 대기 상태가 아닙니다. 상단의 진행 상태를 확인해 주세요.");
        }
        const response = await fetch(apiUrl(`/api/v1/graph-runs/${graphRunId}/resume`), {
          method: "POST", headers: defaultHeaders(), credentials: "include",
          body: JSON.stringify({
            thread_id: state.thread_id,
            response: { schema_version: pending.schema_version, review_stage: "planning_review", decision: "approve" },
          }),
        });
        const next = await response.json().catch(() => null);
        if (!response.ok) throw new Error(next?.detail || "스토리보드 승인을 처리하지 못했습니다.");
        setMessage({ type: "success", text: "스토리보드를 승인했습니다. 이미지 생성 대기 상태로 보존되었습니다." });
        window.setTimeout(() => window.location.reload(), 150);
        return;
      }
      await saveDraft();
      const next = await request("/storyboard/approve", "POST");
      replaceDraft(next);
      setMessage({ type: "success", text: "스토리보드가 승인되었습니다." });
    } catch (error) { setMessage({ type: "error", text: error instanceof Error ? error.message : "승인에 실패했습니다." }); }
    finally { setIsApproving(false); }
  };

  const handleRestore = async (revision: number) => {
    setIsSaving(true); setMessage(null);
    try {
      const next = await request("/storyboard/restore", "POST", { revision });
      replaceDraft(next);
      setMessage({ type: "success", text: `${revision}번 스토리보드 상태로 복원했습니다.` });
    } catch (error) { setMessage({ type: "error", text: error instanceof Error ? error.message : "복원에 실패했습니다." }); }
    finally { setIsSaving(false); }
  };

  const busy = isSaving || isApproving || isRegenerating;
  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <div className="sticky top-0 z-10 flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 bg-slate-50/90 py-4 backdrop-blur-md">
        <div><h2 className="text-xl font-black text-slate-900">판매 스토리보드 검수</h2><p className="mt-1 text-xs text-slate-500">이미지 생성 전, 설득 흐름·근거·장면 요청을 먼저 확정합니다.</p></div>
        <div className="flex flex-wrap gap-2">
          {!graphGenerationPending && <button type="button" onClick={handleRegenerate} disabled={busy} className="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-2.5 text-xs font-bold text-emerald-800 disabled:opacity-50">{isRegenerating ? "만드는 중..." : "후보 3개 다시 만들기"}</button>}
          <button type="button" onClick={handleSaveDraft} disabled={busy} className="rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-xs font-bold text-slate-700 disabled:opacity-50">{isSaving ? "저장 중..." : "임시 저장"}</button>
          {showApprovalAction && <button type="button" onClick={handleApprove} disabled={busy} className="rounded-xl bg-emerald-600 px-5 py-2.5 text-xs font-black text-white shadow-lg shadow-emerald-100 disabled:opacity-50">{isApproving ? "승인 중..." : "스토리보드 승인"}</button>}
          {graphGenerationPending && <span className="rounded-xl border border-violet-200 bg-violet-50 px-4 py-2.5 text-xs font-black text-violet-800">스토리보드 승인 완료 · 이미지 생성 대기</span>}
        </div>
      </div>

      {message && <div role="status" className={`rounded-xl border px-4 py-3 text-sm ${message.type === "success" ? "border-emerald-100 bg-emerald-50 text-emerald-700" : "border-rose-100 bg-rose-50 text-rose-700"}`}>{message.text}</div>}
      {draft.status === "stale" && <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">연결된 사실 또는 자산이 바뀌었습니다. 후보를 다시 만든 뒤 검토해 주세요.</div>}
      {graphRunId ? (
        <>
        <section className="rounded-xl border border-violet-200 bg-violet-50 p-4 text-sm text-violet-950">
          {graphGenerationPending
            ? <>스토리보드 승인이 완료되었습니다. <b>이미지 생성 대기</b> 상태로 안전하게 보존되어 자동으로 이어집니다.</>
            : <>스토리보드는 승인 흐름으로 관리됩니다. 승인 후 <b>이미지 생성 대기</b> 상태로 보존됩니다.</>}
        </section>
        </>
      ) : <><ApiReadyGenerationPlanPanel projectId={projectId} /><StoryboardImageGenerationPanel projectId={projectId} storyboardStatus={draft.status} /></>}

      <div className="flex flex-wrap gap-2 text-xs">
        <span className={`rounded-lg px-3 py-2 font-semibold ${enabledCards.length >= 7 && enabledCards.length <= 12 ? "bg-emerald-50 text-emerald-800" : "bg-amber-50 text-amber-800"}`}>채널 길이: {enabledCards.length}개 섹션 · 권장 7~12개</span>
        <span className={`rounded-lg px-3 py-2 font-semibold ${repeatedAssetCount ? "bg-rose-50 text-rose-700" : "bg-slate-100 text-slate-600"}`}>{repeatedAssetCount ? `반복 자산 경고 ${repeatedAssetCount}건` : "최종 자산 자동 반복 없음"}</span>
        <span className="rounded-lg bg-slate-100 px-3 py-2 font-semibold text-slate-600">예상 이미지 생성 비용: {draft.estimated_cost || 0} 크레딧 (정보용)</span>
      </div>

      <section className="rounded-2xl border border-slate-200 bg-white p-5">
        <div className="mb-4"><h3 className="font-extrabold text-slate-900">추천 스토리보드</h3><p className="mt-1 text-xs text-slate-500">선택해도 실제 이미지는 아직 생성되지 않으며, 필요한 장면만 예약됩니다.</p></div>
        <div className="grid gap-3 md:grid-cols-3">
          {(draft.recommendations || []).map((candidate) => {
            const selected = candidate.key === draft.selected_candidate_key;
            return <button key={candidate.key} type="button" onClick={() => handleSelectRecommendation(candidate.key)} disabled={busy} className={`rounded-xl border p-4 text-left ${selected ? "border-emerald-500 bg-emerald-50" : "border-slate-200 hover:border-emerald-200"}`}>
              <div className="flex items-center justify-between gap-2"><strong className="text-sm text-slate-900">{candidate.label}</strong>{selected && <span className="text-[10px] font-bold text-emerald-700">선택됨</span>}</div>
              <p className="mt-2 text-xs leading-5 text-slate-600">{candidate.reason}</p>
              <p className="mt-2 text-[11px] font-semibold text-amber-700">필요 장면 {candidate.missing_images?.length || 0}개 · 예상 비용 {candidate.estimated_cost || 0} 크레딧</p>
            </button>;
          })}
        </div>
      </section>

      <section className="rounded-2xl border border-slate-200 bg-white p-5">
        <div className="flex items-center justify-between"><h3 className="font-extrabold text-slate-900">스토리보드 버전</h3><span className="text-xs font-bold text-emerald-700">현재 v{draft.revision || 1}</span></div>
        <div className="mt-3 flex flex-wrap gap-2">
          {(draft.revision_history || []).slice(-5).reverse().map((item) => <button key={`${item.revision}-${item.action}`} type="button" onClick={() => handleRestore(item.revision)} disabled={busy || item.revision === draft.revision} className="rounded-lg border border-slate-200 px-3 py-2 text-xs text-slate-600 disabled:opacity-40">v{item.revision} · {item.action === "generated" ? "생성" : item.action === "edited" ? "수정" : item.action === "approved" ? "승인" : "복원"}</button>)}
        </div>
      </section>

      <div className="space-y-4">{cards.map((card, index) => <PlanningDraftCard key={card.id} card={card} index={index} totalCards={cards.length} onChange={(next) => handleCardChange(index, next)} onMoveUp={() => handleMoveCard(index, "up")} onMoveDown={() => handleMoveCard(index, "down")} />)}</div>
      <div className="flex justify-end gap-3 border-t border-slate-100 pt-6"><button type="button" onClick={handleSaveDraft} disabled={busy} className="rounded-2xl border border-slate-200 bg-white px-5 py-3.5 text-sm font-bold text-slate-700 disabled:opacity-50">임시 저장</button>{showApprovalAction && <button type="button" onClick={handleApprove} disabled={busy} className="rounded-2xl bg-emerald-600 px-6 py-3.5 text-sm font-black text-white disabled:opacity-50">스토리보드 승인</button>}</div>
    </div>
  );
}

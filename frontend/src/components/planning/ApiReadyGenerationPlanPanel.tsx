"use client";

import { useCallback, useEffect, useState } from "react";
import { apiUrl } from "@/lib/api";

type Asset = { id: string; filename: string; asset_role: string; is_representative: boolean };
type Fact = { id: string; text: string; field_key: string; value?: string | null; unit?: string | null };
type ExpectedCopy = { headline: string; body: string };
type Scene = {
  id: string; label: string; scene_type: string; objective: string; source_fact_ids: string[];
  reference_asset_ids: string[]; requested_output: string; mock_status: string; generation_reason: string;
  expected_copy: ExpectedCopy; seller_note: string; seller_approved: boolean;
  regeneration_history: Array<{ event: string; reason: string; at: string }>;
  copy_draft?: { status: string; headline: string; body: string; source_fact_ids: string[]; forbidden_check: { passed: boolean; matches: string[] }; estimated_cost: number };
};
type ProductBrief = {
  product_name?: string; category?: string | null; model_option?: string | null; options?: string[];
  color?: string | null; sales_channel?: string | null; seller_input?: string; forbidden_claims?: string[];
  identity_criteria?: { must_preserve?: string[]; seller_notes?: string };
  confirmed_facts: Fact[]; safe_reference_assets: Asset[];
  needs_seller_confirmation: Array<{ id: string; text: string; status?: string; reason: string }>;
  source_states?: Array<{ kind: string; value: string; status: string }>;
};
type Plan = {
  version: number; provider_mode: string; product_brief: ProductBrief; scenes: Scene[];
  summary: { safe_reference_asset_count: number; generation_pending_count: number; seller_confirmation_needed_count: number };
  rendering_policy?: { export_label?: string };
};

const statusLabel: Record<string, string> = {
  ready_with_existing_asset: "안전한 원본 사진 사용",
  information_fallback: "정보형 미리보기",
  generation_pending: "AI 이미지 생성 대기",
  needs_seller_input: "판매자 입력 필요",
};

export default function ApiReadyGenerationPlanPanel({ projectId }: { projectId: string }) {
  const [plan, setPlan] = useState<Plan | null>(null);
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const load = useCallback(async (create = false) => {
    setLoading(true); setMessage(null);
    try {
      const response = await fetch(apiUrl(`/api/v1/projects/${projectId}/generation-plan`), {
        method: create ? "POST" : "GET", headers: create ? { "Content-Type": "application/json" } : undefined,
        credentials: "include",
      });
      if (response.status === 404 && !create) { setPlan(null); return; }
      if (!response.ok) throw new Error("AI 생성 준비 계획을 불러오지 못했습니다.");
      setPlan(await response.json());
    } catch (error) { setMessage(error instanceof Error ? error.message : "AI 생성 준비 계획을 불러오지 못했습니다."); }
    finally { setLoading(false); }
  }, [projectId]);

  useEffect(() => { void load(); }, [load]);

  const patch = async (payload: Record<string, unknown>) => {
    setWorking(true); setMessage(null);
    try {
      const response = await fetch(apiUrl(`/api/v1/projects/${projectId}/generation-plan`), {
        method: "PATCH", headers: { "Content-Type": "application/json" }, credentials: "include", body: JSON.stringify(payload),
      });
      if (!response.ok) {
        const body = await response.json().catch(() => null);
        throw new Error(body?.detail || "장면 계획을 저장하지 못했습니다.");
      }
      setPlan(await response.json()); setMessage("AI 생성 준비 계획을 저장했습니다.");
    } catch (error) { setMessage(error instanceof Error ? error.message : "장면 계획을 저장하지 못했습니다."); }
    finally { setWorking(false); }
  };

  const updateScene = (scene: Scene, update: Record<string, unknown>) => void patch({ scenes: [{ id: scene.id, ...update }] });
  const updateBrief = (brief: Record<string, unknown>) => void patch({ product_brief: brief, scenes: [] });
  const updateLocalScene = (sceneId: string, update: Partial<Scene>) => setPlan((current) => current ? {
    ...current, scenes: current.scenes.map((scene) => scene.id === sceneId ? { ...scene, ...update } : scene),
  } : current);
  const createCopyDrafts = async () => {
    setWorking(true); setMessage(null);
    try {
      const response = await fetch(apiUrl(`/api/v1/projects/${projectId}/generation-plan/copy-drafts`), { method: "POST", headers: { "Content-Type": "application/json" }, credentials: "include", body: JSON.stringify({ seller_cost_approved: true }) });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload?.detail || "카피 초안을 만들지 못했습니다.");
      setPlan(payload.plan); setMessage(`카피 초안 ${payload.results.filter((item: { status: string }) => item.status === "needs_seller_review").length}개를 만들었습니다. 판매자 확인 전에는 다음 단계에 전달되지 않습니다.`);
    } catch (error) { setMessage(error instanceof Error ? error.message : "카피 초안을 만들지 못했습니다."); }
    finally { setWorking(false); }
  };
  const decideCopyDraft = async (scene: Scene, sellerApproved: boolean) => {
    setWorking(true); setMessage(null);
    try {
      const response = await fetch(apiUrl(`/api/v1/projects/${projectId}/generation-plan/copy-drafts/${scene.id}`), { method: "PATCH", headers: { "Content-Type": "application/json" }, credentials: "include", body: JSON.stringify({ seller_approved: sellerApproved }) });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload?.detail || "카피 검토 상태를 저장하지 못했습니다.");
      updateLocalScene(scene.id, { copy_draft: payload.copy_draft });
      setMessage(payload.copy_draft?.status === "stale" ? "근거 또는 브리프가 변경되어 승인할 수 없습니다. 카피를 다시 생성하세요." : sellerApproved ? "카피 초안을 승인했습니다. 후속 이미지·렌더 단계에서만 사용할 수 있습니다." : "카피 초안을 반려했습니다. 장면 근거를 수정한 뒤 다시 생성하세요.");
    } catch (error) { setMessage(error instanceof Error ? error.message : "카피 검토 상태를 저장하지 못했습니다."); }
    finally { setWorking(false); }
  };

  if (loading) return <section className="rounded-2xl border border-slate-200 bg-white p-5 text-sm text-slate-500">AI 생성 준비 계획을 확인하는 중...</section>;
  if (!plan) return <section className="rounded-2xl border border-violet-200 bg-violet-50 p-5"><h3 className="font-black text-slate-900">AI 생성 연결 준비</h3><p className="mt-1 text-sm text-slate-600">API 비용 없이 상품 브리프와 장면 계획을 먼저 만듭니다. 사람 사용 장면과 한국어 사양 그래픽은 API 연결 전까지 생성 대기로 표시됩니다.</p><button type="button" onClick={() => void load(true)} disabled={working} className="mt-4 rounded-xl bg-violet-600 px-4 py-2.5 text-sm font-bold text-white disabled:opacity-50">{working ? "만드는 중..." : "상품 브리프·장면 계획 만들기"}</button>{message && <p className="mt-3 text-sm text-rose-700">{message}</p>}</section>;

  const brief = plan.product_brief;
  const assets = brief.safe_reference_assets || [];
  const facts = brief.confirmed_facts || [];
  return <section className="rounded-2xl border border-violet-200 bg-white p-5 shadow-sm">
    <div className="flex flex-wrap items-start justify-between gap-3"><div><div className="flex items-center gap-2"><h3 className="font-black text-slate-900">AI 생성 연결 준비</h3><span className="rounded-full bg-violet-100 px-2 py-1 text-[11px] font-bold text-violet-800">API 미연결</span></div><p className="mt-1 text-sm text-slate-600">현재는 안전한 원본 사진과 확정 사실 기반 정보형 미리보기만 출력합니다. 생성 대기 장면은 실제 API 연결 후에만 실행됩니다.</p></div><button type="button" onClick={() => void load(true)} disabled={working} className="rounded-xl border border-violet-200 px-3 py-2 text-xs font-bold text-violet-800 disabled:opacity-50">계획 새로 만들기</button></div>
    {message && <p className="mt-3 text-sm text-violet-700">{message}</p>}
    <div className="mt-4 grid gap-2 sm:grid-cols-3"><span className="rounded-lg bg-slate-50 p-3 text-xs text-slate-600">안전 기준 사진 <b className="text-slate-900">{plan.summary.safe_reference_asset_count || 0}개</b></span><span className="rounded-lg bg-amber-50 p-3 text-xs text-amber-800">AI 생성 대기 <b>{plan.summary.generation_pending_count || 0}개</b></span><span className="rounded-lg bg-rose-50 p-3 text-xs text-rose-800">판매자 확인 필요 <b>{plan.summary.seller_confirmation_needed_count || 0}개</b></span></div>

    <section className="mt-5 rounded-xl border border-slate-200 bg-slate-50 p-4"><h4 className="font-black text-slate-900">상품 브리프</h4><p className="mt-1 text-xs text-slate-500">AI가 나중에 사용할 상품 기준입니다. 확정 사실 외의 정보는 판매자가 직접 확인·수정합니다.</p><div className="mt-3 grid gap-3 sm:grid-cols-2"><label className="text-xs font-bold text-slate-700">제품명<input value={brief.product_name || ""} onChange={(e) => setPlan({ ...plan, product_brief: { ...brief, product_name: e.target.value } })} onBlur={(e) => updateBrief({ product_name: e.target.value })} className="mt-1 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm" /></label><label className="text-xs font-bold text-slate-700">카테고리<input value={brief.category || ""} onChange={(e) => setPlan({ ...plan, product_brief: { ...brief, category: e.target.value } })} onBlur={(e) => updateBrief({ category: e.target.value })} className="mt-1 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm" /></label><label className="text-xs font-bold text-slate-700">모델·옵션<input value={brief.model_option || ""} onChange={(e) => setPlan({ ...plan, product_brief: { ...brief, model_option: e.target.value } })} onBlur={(e) => updateBrief({ model_option: e.target.value })} className="mt-1 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm" /></label><label className="text-xs font-bold text-slate-700">색상<input value={brief.color || ""} onChange={(e) => setPlan({ ...plan, product_brief: { ...brief, color: e.target.value } })} onBlur={(e) => updateBrief({ color: e.target.value })} className="mt-1 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm" /></label><label className="text-xs font-bold text-slate-700">판매 채널<input value={brief.sales_channel || ""} onChange={(e) => setPlan({ ...plan, product_brief: { ...brief, sales_channel: e.target.value } })} onBlur={(e) => updateBrief({ sales_channel: e.target.value })} className="mt-1 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm" /></label><label className="text-xs font-bold text-slate-700">옵션 (쉼표로 구분)<input value={(brief.options || []).join(", ")} onChange={(e) => setPlan({ ...plan, product_brief: { ...brief, options: e.target.value.split(",").map((v) => v.trim()).filter(Boolean) } })} onBlur={(e) => updateBrief({ options: e.target.value.split(",").map((v) => v.trim()).filter(Boolean) })} className="mt-1 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm" /></label></div><label className="mt-3 block text-xs font-bold text-slate-700">금지 표현 (쉼표로 구분)<input value={(brief.forbidden_claims || []).join(", ")} onChange={(e) => setPlan({ ...plan, product_brief: { ...brief, forbidden_claims: e.target.value.split(",").map((v) => v.trim()).filter(Boolean) } })} onBlur={(e) => updateBrief({ forbidden_claims: e.target.value.split(",").map((v) => v.trim()).filter(Boolean) })} className="mt-1 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm" /></label><label className="mt-3 block text-xs font-bold text-slate-700">제품 정체성 유지 메모<textarea value={brief.identity_criteria?.seller_notes || ""} onChange={(e) => setPlan({ ...plan, product_brief: { ...brief, identity_criteria: { ...brief.identity_criteria, seller_notes: e.target.value } } })} onBlur={(e) => updateBrief({ identity_criteria: { ...brief.identity_criteria, seller_notes: e.target.value } })} className="mt-1 min-h-16 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm" placeholder="형태·색상·버튼·포트·구성품 중 반드시 유지할 특징" /></label><div className="mt-3 rounded-lg bg-white p-3 text-xs text-slate-600"><b className="text-slate-800">정체성 유지:</b> {(brief.identity_criteria?.must_preserve || []).join(" · ") || "판매자 확인 필요"}</div><div className="mt-2 rounded-lg bg-white p-3 text-xs text-slate-600"><b className="text-slate-800">출처:</b> {(brief.source_states || []).map((item) => `${item.kind}: ${item.status}`).join(" / ") || "직접 입력 확인 필요"}</div></section>

    <section className="mt-4 rounded-xl border border-emerald-200 bg-emerald-50 p-4"><h4 className="font-black text-emerald-950">확정 사실 카드</h4><div className="mt-2 flex flex-wrap gap-2">{facts.length ? facts.map((fact) => <span key={fact.id} className="rounded-full bg-white px-2 py-1 text-xs text-emerald-900">{fact.text}</span>) : <span className="text-xs text-amber-800">확정된 상품 사실이 없어 생성 요청을 할 수 없습니다.</span>}</div></section>
    {brief.needs_seller_confirmation.length > 0 && <section className="mt-4 rounded-xl border border-amber-200 bg-amber-50 p-4"><h4 className="font-black text-amber-950">누락·충돌 확인</h4>{brief.needs_seller_confirmation.map((item) => <p key={item.id} className="mt-2 text-xs text-amber-900"><b>{item.status === "conflicted" ? "충돌" : "확인 필요"}</b> · {item.text} — {item.reason}</p>)}</section>}

    <div className="mt-5 flex flex-wrap items-center justify-between gap-3"><div><h4 className="font-black text-slate-900">근거 기반 한국어 카피 초안</h4><p className="mt-1 text-xs text-slate-500">실행 대상 {plan.scenes.length}개 장면 · 예상 비용 0원 · 확정 사실과 판매자 승인 브리프만 사용</p></div><button type="button" onClick={() => void createCopyDrafts()} disabled={working || facts.length === 0} className="rounded-xl bg-violet-600 px-4 py-2 text-sm font-bold text-white disabled:opacity-50">작업 수·예상 비용 확인 후 카피 초안 만들기</button></div>
    {plan.scenes.some((scene) => scene.copy_draft?.status === "stale") && <p className="mt-3 rounded-lg bg-amber-50 p-3 text-xs font-semibold text-amber-800">연결된 사실 또는 브리프가 변경된 카피가 있습니다. 해당 장면은 다시 생성하기 전까지 후속 단계에 전달되지 않습니다.</p>}
    <div className="mt-3 space-y-3">{plan.scenes.map((scene) => <article key={scene.id} className="rounded-xl border border-slate-200 p-4"><div className="flex flex-wrap items-center justify-between gap-2"><div><strong className="text-sm text-slate-900">{scene.label}</strong><span className="ml-2 text-xs font-semibold text-violet-700">{statusLabel[scene.mock_status] || scene.mock_status}</span></div><span className="text-[11px] text-slate-500">{scene.requested_output} · 이력 {scene.regeneration_history?.length || 0}회</span></div><p className="mt-2 text-xs text-slate-500">{scene.generation_reason}</p>{scene.copy_draft && <div className="mt-3 rounded-lg bg-violet-50 p-3 text-sm text-violet-950"><p className="font-bold">카피 상태: {scene.copy_draft.status === "seller_approved" ? "판매자 승인" : scene.copy_draft.status === "seller_rejected" ? "판매자 반려" : scene.copy_draft.status === "stale" ? "근거 변경으로 재생성 필요" : "판매자 검토 대기"}</p><p className="mt-1 font-semibold">{scene.copy_draft.headline}</p><p className="mt-1">{scene.copy_draft.body}</p><p className="mt-2 text-xs">근거 {scene.copy_draft.source_fact_ids.length}개 · 금지 표현 검사 통과</p>{scene.copy_draft.status === "needs_seller_review" && <div className="mt-2 flex gap-2"><button type="button" disabled={working} onClick={() => void decideCopyDraft(scene, true)} className="rounded-md bg-emerald-600 px-2 py-1 text-xs font-bold text-white">카피 승인</button><button type="button" disabled={working} onClick={() => void decideCopyDraft(scene, false)} className="rounded-md border border-rose-300 px-2 py-1 text-xs font-bold text-rose-700">반려</button></div>}</div>}<label className="mt-3 block text-xs font-bold text-slate-700">장면 목적<input value={scene.objective} onChange={(e) => updateLocalScene(scene.id, { objective: e.target.value })} onBlur={(e) => updateScene(scene, { objective: e.target.value, regeneration_reason: "판매자 장면 목적 수정" })} className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm" /></label><div className="mt-3"><p className="text-xs font-bold text-slate-700">이 장면에서 사용할 확정 사실</p><div className="mt-2 flex flex-wrap gap-2">{facts.map((fact) => { const selected = scene.source_fact_ids.includes(fact.id); return <button key={fact.id} type="button" disabled={working} onClick={() => updateScene(scene, { source_fact_ids: selected ? scene.source_fact_ids.filter((id) => id !== fact.id) : [...scene.source_fact_ids, fact.id], regeneration_reason: "판매자 장면 근거 사실 변경" })} className={`rounded-lg border px-2 py-1 text-[11px] font-semibold ${selected ? "border-emerald-300 bg-emerald-50 text-emerald-800" : "border-slate-200 text-slate-600"}`}>{selected ? "근거 ✓" : "근거 추가"}: {fact.text}</button>; })}</div></div><div className="mt-3"><p className="text-xs font-bold text-slate-700">안전 기준 사진</p><div className="mt-2 flex flex-wrap gap-2">{assets.map((asset) => { const selected = scene.reference_asset_ids.includes(asset.id); return <button key={asset.id} type="button" disabled={working} onClick={() => updateScene(scene, { reference_asset_ids: selected ? scene.reference_asset_ids.filter((id) => id !== asset.id) : [...scene.reference_asset_ids, asset.id], regeneration_reason: "판매자 기준 사진 변경" })} className={`rounded-lg border px-2 py-1 text-[11px] font-semibold ${selected ? "border-emerald-300 bg-emerald-50 text-emerald-800" : "border-slate-200 text-slate-600"}`}>{selected ? "기준 사진 ✓" : "기준 사진"}: {asset.filename}</button>; })}</div></div><div className="mt-3 grid gap-2 sm:grid-cols-2"><label className="text-xs font-bold text-slate-700">예상 헤드라인<input value={scene.expected_copy?.headline || ""} onChange={(e) => updateLocalScene(scene.id, { expected_copy: { ...scene.expected_copy, headline: e.target.value } })} onBlur={(e) => updateScene(scene, { expected_copy: { ...scene.expected_copy, headline: e.target.value }, regeneration_reason: "판매자 예상 헤드라인 수정" })} className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm" /></label><label className="text-xs font-bold text-slate-700">예상 본문<input value={scene.expected_copy?.body || ""} onChange={(e) => updateLocalScene(scene.id, { expected_copy: { ...scene.expected_copy, body: e.target.value } })} onBlur={(e) => updateScene(scene, { expected_copy: { ...scene.expected_copy, body: e.target.value }, regeneration_reason: "판매자 예상 본문 수정" })} className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm" /></label></div><label className="mt-3 block text-xs font-bold text-slate-700">판매자 메모<textarea value={scene.seller_note || ""} onChange={(e) => updateLocalScene(scene.id, { seller_note: e.target.value })} onBlur={(e) => updateScene(scene, { seller_note: e.target.value })} className="mt-1 min-h-14 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm" placeholder="API 연결 후 생성할 때 참고할 요구사항" /></label><label className="mt-3 flex items-center gap-2 text-xs font-semibold text-slate-700"><input type="checkbox" checked={scene.seller_approved} onChange={(e) => updateScene(scene, { seller_approved: e.target.checked, regeneration_reason: "판매자 장면 계획 승인 변경" })} disabled={working} />이 장면 계획을 확인했습니다</label>{scene.regeneration_history?.length ? <p className="mt-2 text-[11px] text-slate-500">최근 변경: {scene.regeneration_history[scene.regeneration_history.length - 1]?.reason}</p> : null}</article>)}</div>
    <p className="mt-4 rounded-lg bg-slate-100 p-3 text-xs text-slate-600">{plan.rendering_policy?.export_label || "API 미연결 상태의 다운로드에는 가짜 생성 이미지가 포함되지 않습니다."}</p>
  </section>;
}

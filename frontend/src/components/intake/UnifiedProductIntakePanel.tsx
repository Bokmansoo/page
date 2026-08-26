"use client";

import { ChangeEvent, FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { apiUrl, sessionFetch } from "@/lib/api";

type InputMode = "owned_product_url" | "photo_only" | "manual";
type GenerationMode = "quick" | "expert";
type Channel = "smartstore" | "coupang";
type Brand = { id: string; name: string };
type Asset = { id: string; filename: string; source_type: string; usage_status: string; mime_type: string; content_hash?: string | null };
type GraphRun = { run_id: string; thread_id: string; status: string; current_stage: string; values: Record<string, unknown>; next_nodes: string[] };
type Clarification = { clarification_id: string; field_id?: string; label?: string; question?: string; options?: Array<{ id?: string; value?: string; label?: string }>; observations?: Array<{ id?: string; value?: string; label?: string }> };
type AnswerDraft = { decision: "confirm" | "reject" | "unknown" | "skip"; value: string; unit: string; selected: string };

const MODE_COPY: Record<InputMode, { title: string; body: string }> = {
  owned_product_url: { title: "내 상품 URL", body: "판매·사용 권한을 확인한 상품 URL을 캡처 요청으로 고정합니다." },
  photo_only: { title: "상품 사진", body: "권리 상태가 확인된 내 상품 사진 1~2장만 관찰 자료로 사용합니다." },
  manual: { title: "직접 입력", body: "판매자 사실 후보와 창작 방향을 분리해 안전하게 확인합니다." },
};
const STAGE_COPY: Record<string, string> = {
  unified_intake_router: "입력 방식을 확인하고 있습니다",
  manual_input_adapter: "직접 입력 자료를 고정하고 있습니다",
  owned_product_url_capture_adapter: "상품 URL을 안전하게 캡처하고 있습니다",
  photo_only_observation_adapter: "상품 사진을 관찰하고 있습니다",
  product_truth_normalization: "상품 정보를 근거와 함께 정리하고 있습니다",
  seller_confirmation_required: "판매자 확인이 필요합니다",
  confirmation_still_required: "남은 확인 항목이 있습니다",
  product_creative_brief: "상품 콘텐츠 기준을 만들고 있습니다",
  commerce_creative_master: "콘텐츠 기준을 고정하고 있습니다",
  master_ready: "Commerce Creative Master가 준비되었습니다",
  owned_url_capture_recovery: "URL 캡처를 완료하지 못했습니다",
  photo_observation_recovery: "사진 관찰을 완료하지 못했습니다",
  truth_blocked_source_integrity: "입력 자료 무결성 확인이 필요합니다",
};

function messageFrom(value: unknown): string {
  if (typeof value === "string") return value;
  if (value && typeof value === "object") {
    const data = value as Record<string, unknown>;
    return String(data.message || data.detail || data.code || "요청을 처리하지 못했습니다.");
  }
  return "요청을 처리하지 못했습니다.";
}
async function requestJson<T>(path: string, init: RequestInit): Promise<T> {
  const response = await sessionFetch(apiUrl(path), init);
  if (!response.ok) {
    let body: unknown;
    try { body = await response.json(); } catch { body = null; }
    throw new Error(messageFrom(body && typeof body === "object" && "detail" in body ? (body as { detail: unknown }).detail : body));
  }
  return response.json() as Promise<T>;
}
function selectedChannels(channels: Record<Channel, boolean>): Channel[] {
  return (["smartstore", "coupang"] as const).filter((channel) => channels[channel]);
}
function isRecovery(stage: string) {
  return stage.includes("recovery") || stage.includes("blocked_source_integrity") || stage.includes("capture_failed");
}
function confirmationFrom(run: GraphRun | null): { plan: Record<string, unknown>; questions: Clarification[] } | null {
  if (!run) return null;
  const values = run.values || {};
  const review = (values.review || {}) as Record<string, unknown>;
  const pending = (review.pending || {}) as Record<string, unknown>;
  const context = (pending.context || {}) as Record<string, unknown>;
  const intake = (values.intake || {}) as Record<string, unknown>;
  const plan = (context.seller_confirmation || intake.seller_confirmation || {}) as Record<string, unknown>;
  const questions = Array.isArray(plan.clarifications) ? plan.clarifications as Clarification[] : [];
  return questions.length ? { plan, questions: questions.slice(0, 3) } : null;
}

export function UnifiedProductIntakePanel() {
  const router = useRouter();
  const search = useSearchParams();
  const errorRef = useRef<HTMLDivElement>(null);
  const [mode, setMode] = useState<InputMode>("manual");
  const [generationMode, setGenerationMode] = useState<GenerationMode>("quick");
  const [channels, setChannels] = useState<Record<Channel, boolean>>({ smartstore: true, coupang: false });
  const [brands, setBrands] = useState<Brand[]>([]);
  const [brandId, setBrandId] = useState("");
  const [projectName, setProjectName] = useState("");
  const [category, setCategory] = useState("");
  const [url, setUrl] = useState("");
  const [urlRights, setUrlRights] = useState<"seller_owned" | "rights_confirmed" | "unconfirmed">("seller_owned");
  const [manualFacts, setManualFacts] = useState("");
  const [creativeDirection, setCreativeDirection] = useState("");
  const [manualRights, setManualRights] = useState<"confirmed" | "unconfirmed">("unconfirmed");
  const [photoRights, setPhotoRights] = useState<"seller_owned" | "rights_confirmed" | "unconfirmed">("seller_owned");
  const [photos, setPhotos] = useState<File[]>([]);
  const [projectId, setProjectId] = useState(search.get("projectId") || "");
  const [runId, setRunId] = useState(search.get("runId") || "");
  const [run, setRun] = useState<GraphRun | null>(null);
  const [answers, setAnswers] = useState<Record<string, AnswerDraft>>({});
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

  const refreshRun = useCallback(async (requestedRunId = runId) => {
    if (!requestedRunId) return;
    try {
      const next = await requestJson<GraphRun>("/api/v1/graph-runs/" + requestedRunId, { method: "GET" });
      setRun(next);
      const intake = (next.values.intake || {}) as Record<string, unknown>;
      const envelope = (intake.envelope || {}) as Record<string, unknown>;
      if (envelope.input_mode === "owned_product_url" || envelope.input_mode === "photo_only" || envelope.input_mode === "manual") setMode(envelope.input_mode);
      if (envelope.requested_generation_mode === "quick" || envelope.requested_generation_mode === "expert") setGenerationMode(envelope.requested_generation_mode);
      if (Array.isArray(envelope.target_channels)) setChannels({ smartstore: envelope.target_channels.includes("smartstore"), coupang: envelope.target_channels.includes("coupang") });
    } catch (cause) { setError(cause instanceof Error ? cause.message : "현재 실행 상태를 불러오지 못했습니다."); }
  }, [runId]);

  useEffect(() => {
    requestJson<Brand[]>("/api/v1/brands", { method: "GET" })
      .then((items) => { setBrands(items); if (items[0]) setBrandId((current) => current || items[0].id); })
      .catch(() => setError("브랜드 목록을 불러오지 못했습니다. 새로고침 후 다시 시도해 주세요."));
  }, []);
  useEffect(() => { void refreshRun(search.get("runId") || ""); }, [refreshRun, search]);
  useEffect(() => {
    if (!run || run.status === "awaiting_review" || run.status === "completed" || isRecovery(run.current_stage)) return;
    const timer = window.setInterval(() => void refreshRun(), 1500);
    return () => window.clearInterval(timer);
  }, [refreshRun, run]);
  useEffect(() => { if (error) errorRef.current?.focus(); }, [error]);

  const confirmation = useMemo(() => confirmationFrom(run), [run]);
  const stageText = run ? (STAGE_COPY[run.current_stage] || "상품 입력을 처리하고 있습니다") : "입력 방식을 선택해 주세요";
  const updateAnswer = (id: string, update: Partial<AnswerDraft>) => setAnswers((current) => {
    const previous = current[id];
    return {
      ...current,
      [id]: {
        decision: update.decision ?? previous?.decision ?? "unknown",
        value: update.value ?? previous?.value ?? "",
        unit: update.unit ?? previous?.unit ?? "",
        selected: update.selected ?? previous?.selected ?? "",
      },
    };
  });
  function onPhotos(event: ChangeEvent<HTMLInputElement>) {
    const next = Array.from(event.target.files || []);
    if (next.length > 2) { setPhotos([]); setError("상품 사진은 1~2장만 선택할 수 있습니다."); return; }
    setError(""); setPhotos(next);
  }
  async function createProject(): Promise<string> {
    if (!projectName.trim() || !brandId) throw new Error("프로젝트 이름과 브랜드를 선택해 주세요.");
    const project = await requestJson<{ id: string }>("/api/v1/projects", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: projectName.trim(), brand_id: brandId }),
    });
    return project.id;
  }
  async function sourceReferences(id: string): Promise<Array<Record<string, unknown>>> {
    if (mode === "manual") {
      const sellerEnteredFields = [
        { field_id: "product_name", classification: "fact_candidate", label: "상품명", value: projectName.trim() },
        category.trim() ? { field_id: "category", classification: "fact_candidate", label: "카테고리", value: category.trim() } : null,
        manualFacts.trim() ? { field_id: "seller_facts", classification: "fact_candidate", label: "판매자 입력", value: manualFacts.trim() } : null,
        creativeDirection.trim() ? { field_id: "creative_direction", classification: "creative_direction", label: "창작 방향", value: creativeDirection.trim() } : null,
      ].filter(Boolean);
      const ref = await requestJson<{ id: string; version: number; content_hash: string }>("/api/v1/projects/" + id + "/reference-inputs", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ input_kind: "text", text: "manual intake artifact", rights_status: "seller_owned", source_metadata: {
          manual_payload_schema_version: "lg12i-manual-input-artifact-v1", seller_entered_fields: sellerEnteredFields,
          unknown_fact_field_ids: [], conflict_fact_candidates: [], rights_confirmation_state: manualRights,
        }}),
      });
      return [{ id: ref.id, kind: "manual_payload_artifact", version: ref.version, hash: ref.content_hash }];
    }
    if (mode === "owned_product_url") {
      if (!url.trim()) throw new Error("내 상품 URL을 입력해 주세요.");
      const ref = await requestJson<{ id: string; version: number; content_hash: string }>("/api/v1/projects/" + id + "/reference-inputs", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ input_kind: "url", source_url: url.trim(), rights_status: urlRights === "rights_confirmed" ? "verified" : urlRights === "seller_owned" ? "seller_owned" : "unverified", source_metadata: {
          owned_product_url_capture_request_schema_version: "lg12i-owned-product-url-capture-request-v1",
          normalized_url: url.trim(), rights_state: urlRights, provenance: "seller_submitted_owned_product_url",
        }}),
      });
      return [{ id: ref.id, kind: "owned_product_url_capture_request", version: ref.version, hash: ref.content_hash, schema_version: "lg12i-owned-product-url-capture-request-v1" }];
    }
    if (photos.length < 1 || photos.length > 2) throw new Error("상품 사진은 1~2장만 선택해 주세요.");
    const refs: Array<Record<string, unknown>> = [];
    for (const photo of photos) {
      const form = new FormData();
      form.set("project_id", id); form.set("source_type", "uploaded"); form.set("file", photo);
      const uploaded = await requestJson<Asset>("/api/v1/files/upload", { method: "POST", body: form });
      if (!uploaded.content_hash) throw new Error("업로드한 사진의 무결성 정보를 확인하지 못했습니다.");
      refs.push({ id: uploaded.id, kind: "asset_ref", version: 1, hash: uploaded.content_hash, rights_status: photoRights });
    }
    return refs;
  }
  async function start(event: FormEvent) {
    event.preventDefault(); setError(""); setNotice("");
    const targetChannels = selectedChannels(channels);
    if (!targetChannels.length) { setError("판매 채널을 하나 이상 선택해 주세요."); return; }
    if (mode === "photo_only" && (photos.length < 1 || photos.length > 2)) { setError("상품 사진은 1~2장만 선택할 수 있습니다."); return; }
    setBusy(true);
    try {
      const id = projectId || await createProject();
      const refs = await sourceReferences(id);
      const next = await requestJson<GraphRun>("/api/v1/graph-runs/projects/" + id + "/unified-intake", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ input_mode: mode, source_payload_refs: refs, requested_generation_mode: generationMode, target_channels: targetChannels }),
      });
      setProjectId(id); setRunId(next.run_id); setRun(next);
      const restoredUrl = "/workspace/projects/new?projectId=" + encodeURIComponent(id) + "&runId=" + encodeURIComponent(next.run_id);
      // Persist the durable identifiers synchronously. A seller can reload
      // immediately after an interrupt/resume response, before Next has
      // finished a client navigation.
      window.history.replaceState(null, "", restoredUrl);
      router.replace(restoredUrl);
      setNotice("입력 자료를 고정했습니다. 현재 생성 상태를 표시합니다.");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "상품 입력을 시작하지 못했습니다."); }
    finally { setBusy(false); }
  }
  async function retry() {
    if (!run) return;
    setBusy(true); setError("");
    try { setRun(await requestJson<GraphRun>("/api/v1/graph-runs/" + run.run_id + "/resume", { method: "POST" })); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "복구를 다시 시작하지 못했습니다."); }
    finally { setBusy(false); }
  }
  async function submitConfirmation(event: FormEvent) {
    event.preventDefault();
    if (!run || !confirmation) return;
    setBusy(true); setError("");
    try {
      const confirmationAnswers = confirmation.questions.map((question) => {
        const answer = answers[question.clarification_id] || { decision: "unknown" as const, value: "", unit: "", selected: "" };
        // The confirmation contract treats an omitted optional field differently
        // from an empty identifier.  In particular, rights questions have no
        // selectable observation, so sending an empty ID would be rejected by
        // the immutable seller-confirmation validator.
        return {
          clarification_id: question.clarification_id,
          decision: answer.decision,
          ...(answer.value.trim() ? { answer_value: answer.value } : {}),
          ...(answer.unit.trim() ? { unit: answer.unit } : {}),
          ...(answer.selected ? { selected_observation_id: answer.selected } : {}),
        };
      });
      const next = await requestJson<GraphRun>("/api/v1/graph-runs/" + run.run_id + "/resume", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ thread_id: run.thread_id, response: {
          schema_version: "lg12i-v1", review_stage: "seller_confirmation", decision: "submit",
          confirmation_request_hash: String(confirmation.plan.resume_request_hash || ""), confirmation_answers: confirmationAnswers,
        }}),
      });
      setRun(next); setNotice("판매자 확인을 저장했습니다. 다음 상태를 불러오고 있습니다.");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "확인 응답을 저장하지 못했습니다."); }
    finally { setBusy(false); }
  }

  return <main className="mx-auto max-w-4xl space-y-6 px-4 py-8 sm:px-6" aria-labelledby="intake-title">
    <header className="space-y-2"><p className="text-sm font-semibold text-emerald-700">상품 입력</p><h1 id="intake-title" className="text-2xl font-bold text-slate-900">상품 입력 방식</h1><p className="text-sm text-slate-600">선택한 방식은 같은 생성 흐름에서 근거·확인·콘텐츠 기준으로 이어집니다.</p></header>
    <div aria-live="polite" className="sr-only">{notice}</div>
    {error && <div ref={errorRef} tabIndex={-1} role="alert" className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800">{error}</div>}
    {notice && <div role="status" className="rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-800">{notice}</div>}
    <form onSubmit={start} className="space-y-6">
      <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"><div className="grid gap-3 md:grid-cols-3">{(Object.keys(MODE_COPY) as InputMode[]).map((value) => <label key={value} className={"cursor-pointer rounded-xl border p-4 " + (mode === value ? "border-emerald-500 bg-emerald-50" : "border-slate-200")}><input aria-label={"입력 방식 " + value} className="mr-2" type="radio" name="input-mode" value={value} checked={mode === value} onChange={() => setMode(value)} /><span className="font-semibold text-slate-900">{MODE_COPY[value].title}</span><span className="mt-1 block text-xs leading-5 text-slate-600">{MODE_COPY[value].body}</span></label>)}</div></section>
      <section className="grid gap-4 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm md:grid-cols-2"><label className="text-sm font-medium text-slate-800">프로젝트 이름<input required value={projectName} onChange={(event) => setProjectName(event.target.value)} className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2" placeholder="예: 휴대용 선풍기" /></label><label className="text-sm font-medium text-slate-800">브랜드<select required value={brandId} onChange={(event) => setBrandId(event.target.value)} className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2"><option value="">브랜드 선택</option>{brands.map((brand) => <option key={brand.id} value={brand.id}>{brand.name}</option>)}</select></label></section>
      {mode === "owned_product_url" && <section className="space-y-4 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"><label className="block text-sm font-medium">내 상품 URL<input type="url" value={url} onChange={(event) => setUrl(event.target.value)} className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2" placeholder="https://store.example.com/products/…" /></label><RightsControl name="url-rights" value={urlRights} onChange={setUrlRights} /><p className="text-xs text-slate-500">브라우저는 URL 본문을 수집하지 않습니다. 서버에는 불변 캡처 요청 reference만 전달됩니다.</p></section>}
      {mode === "photo_only" && <section className="space-y-4 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"><label className="block text-sm font-medium">상품 사진 1~2장<input aria-label="상품 사진 1~2장" type="file" accept="image/png,image/jpeg,image/webp" multiple onChange={onPhotos} className="mt-2 block w-full text-sm" /></label><p className="text-sm text-slate-600">선택됨: {photos.length}장. 공급처·레퍼런스·차단 자료는 이 입력 방식에서 사용할 수 없습니다.</p><RightsControl name="photo-rights" value={photoRights} onChange={setPhotoRights} /></section>}
      {mode === "manual" && <section className="grid gap-4 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm md:grid-cols-2"><label className="text-sm font-medium">카테고리<input value={category} onChange={(event) => setCategory(event.target.value)} className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2" placeholder="예: 생활용품" /></label><label className="text-sm font-medium">권리 상태<select value={manualRights} onChange={(event) => setManualRights(event.target.value as "confirmed" | "unconfirmed")} className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2"><option value="unconfirmed">미확인</option><option value="confirmed">확인됨</option></select></label><label className="md:col-span-2 text-sm font-medium">판매자 입력 사실 후보<textarea value={manualFacts} onChange={(event) => setManualFacts(event.target.value)} className="mt-1 block min-h-28 w-full rounded-lg border border-slate-300 px-3 py-2" placeholder="확인 가능한 사양, 구성, 수치만 입력해 주세요." /></label><label className="md:col-span-2 text-sm font-medium">창작 방향 (선택)<textarea value={creativeDirection} onChange={(event) => setCreativeDirection(event.target.value)} className="mt-1 block min-h-24 w-full rounded-lg border border-slate-300 px-3 py-2" placeholder="예: 깔끔하고 프리미엄한 분위기" /></label><p className="md:col-span-2 text-xs text-slate-500">빈 선택 항목은 미확인 정보로 남습니다. 창작 방향은 상품 사실로 승인되지 않습니다.</p></section>}
      <section className="grid gap-4 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm md:grid-cols-2"><fieldset><legend className="text-sm font-semibold">생성 방식</legend><div className="mt-2 flex gap-4"><label><input type="radio" name="generation" checked={generationMode === "quick"} onChange={() => setGenerationMode("quick")} /> Quick</label><label><input type="radio" name="generation" checked={generationMode === "expert"} onChange={() => setGenerationMode("expert")} /> Expert</label></div><p className="mt-2 text-xs text-slate-500">Quick도 권리·충돌·미확인 핵심 사실은 확인을 건너뛰지 않습니다. Expert는 단계별 검토를 제공합니다.</p></fieldset><fieldset><legend className="text-sm font-semibold">판매 채널</legend><div className="mt-2 flex gap-4"><label><input type="checkbox" checked={channels.smartstore} onChange={() => setChannels((current) => ({ ...current, smartstore: !current.smartstore }))} /> SmartStore</label><label><input type="checkbox" checked={channels.coupang} onChange={() => setChannels((current) => ({ ...current, coupang: !current.coupang }))} /> Coupang</label></div></fieldset></section>
      <button disabled={busy} className="rounded-xl bg-emerald-700 px-5 py-3 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:bg-emerald-300">{busy ? "처리 중…" : "상품 입력 시작"}</button>
    </form>
    {run && <section className="space-y-3 rounded-2xl border border-indigo-200 bg-indigo-50 p-5" aria-label="생성 진행 상태"><p className="text-xs font-semibold text-indigo-700">생성 진행 상태</p><h2 className="text-lg font-bold text-slate-900">{stageText}</h2><p className="text-sm text-slate-700">선택 방식: {mode} · {generationMode} · {selectedChannels(channels).join(", ")}</p>{isRecovery(run.current_stage) && <div className="rounded-lg bg-white p-3 text-sm text-slate-700"><p>현재 입력 자료를 완료하지 못했습니다. 같은 실행을 재시도하거나 위에서 사진·직접 입력 방식으로 바꿔 새 입력을 시작할 수 있습니다.</p><button type="button" disabled={busy} onClick={retry} className="mt-3 rounded-lg border border-indigo-300 px-3 py-2 text-sm font-semibold text-indigo-700">같은 실행 다시 시도</button></div>}{run.current_stage === "master_ready" && <a className="inline-flex rounded-lg bg-emerald-700 px-3 py-2 text-sm font-semibold text-white" href={"/workspace/projects/" + projectId + "/planning?runId=" + run.run_id}>기존 상세페이지 흐름으로 계속</a>}</section>}
    {confirmation && run && <form onSubmit={submitConfirmation} className="space-y-4 rounded-2xl border border-amber-300 bg-amber-50 p-5" aria-labelledby="confirmation-title"><h2 id="confirmation-title" className="text-lg font-bold">상품 정보 확인</h2><p className="text-sm text-slate-700">이번 확인 주기에는 최대 3개 항목만 표시됩니다. 저장된 질문 순서와 기준으로 응답합니다.</p>{confirmation.questions.map((question) => <ConfirmationQuestion key={question.clarification_id} question={question} answer={answers[question.clarification_id] || { decision: "unknown", value: "", unit: "", selected: "" }} update={updateAnswer} />)}<button disabled={busy} className="rounded-xl bg-amber-600 px-4 py-2 text-sm font-semibold text-white disabled:bg-amber-300">{busy ? "저장 중…" : "확인 응답 제출"}</button></form>}
  </main>;
}

function RightsControl({ name, value, onChange }: { name: string; value: "seller_owned" | "rights_confirmed" | "unconfirmed"; onChange: (value: "seller_owned" | "rights_confirmed" | "unconfirmed") => void }) {
  return <fieldset><legend className="text-sm font-medium">권리 상태</legend><div className="mt-2 flex flex-wrap gap-3">{(["seller_owned", "rights_confirmed", "unconfirmed"] as const).map((rights) => <label key={rights} className="text-sm"><input type="radio" name={name} checked={value === rights} onChange={() => onChange(rights)} /> {rights === "seller_owned" ? "판매자 소유" : rights === "rights_confirmed" ? "사용 권리 확인" : "권리 미확인"}</label>)}</div></fieldset>;
}
function ConfirmationQuestion({ question, answer, update }: { question: Clarification; answer: AnswerDraft; update: (id: string, update: Partial<AnswerDraft>) => void }) {
  const options = question.options || question.observations || [];
  return <fieldset className="rounded-xl border border-amber-200 bg-white p-4"><legend className="font-semibold text-slate-900">{question.label || question.question || question.field_id || "확인 항목"}</legend><div className="mt-2 flex flex-wrap gap-3">{(["confirm", "reject", "unknown", "skip"] as const).map((decision) => <label key={decision} className="text-sm"><input type="radio" name={"decision-" + question.clarification_id} checked={answer.decision === decision} onChange={() => update(question.clarification_id, { decision })} /> {decision === "confirm" ? "확인" : decision === "reject" ? "거절" : decision === "unknown" ? "모름" : "건너뛰기"}</label>)}</div>{options.length > 0 && <label className="mt-3 block text-sm">기존 관찰 선택<select value={answer.selected} onChange={(event) => update(question.clarification_id, { selected: event.target.value })} className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2"><option value="">직접 수정하거나 선택하지 않음</option>{options.map((option, index) => <option key={option.id || index} value={option.id || ""}>{option.label || option.value || "관찰 " + (index + 1)}</option>)}</select></label>}<div className="mt-3 grid gap-2 sm:grid-cols-2"><label className="text-sm">수정 값<input value={answer.value} onChange={(event) => update(question.clarification_id, { value: event.target.value })} className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2" /></label><label className="text-sm">단위<input value={answer.unit} onChange={(event) => update(question.clarification_id, { unit: event.target.value })} className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2" /></label></div></fieldset>;
}

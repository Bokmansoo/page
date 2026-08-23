"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { apiUrl, sessionFetch } from "@/lib/api";

type InteractionMode = "quick" | "expert";
type ReferenceKind = "url" | "text" | "image" | "pdf";

type Intelligence = {
  interaction_mode: InteractionMode;
  reviews: Array<{
    id: string;
    version: number;
    format: string;
    source_label?: string;
    consent_status: string;
    rights_status: string;
    fact_promotion_status: "blocked";
  }>;
  references: Array<{
    id: string;
    version: number;
    kind: ReferenceKind;
    rights_status: string;
    usage_scope: "analysis_only" | "final_output_eligible";
  }>;
  creative_direction: null | {
    version: number;
    target_audience: string;
    desired_mood: string[];
    emphasis: string[];
    forbidden_scenes: string[];
  };
  briefs: Array<{ id: string; version: number; input_hash: string; output_hash: string }>;
  review_asset_options?: Array<{ id: string; filename: string; mime_type: string; has_text: boolean }>;
  trace?: {
    run_id?: string | null;
    generation_mode?: string | null;
    interaction_mode?: string | null;
    prompt_packs?: Array<null | { kind: string; id: string; version: number; hash: string }>;
    brand_kit?: null | { id: string; version: number; hash: string };
    creative_brief?: null | { id: string; version: number; hash: string };
    approved_facts?: Array<{ id?: string; text?: string; fact_text?: string }>;
    fact_candidates?: Array<{ id: string; text: string; status: string }>;
    creative_direction?: null | { id: string; version: number; hash: string };
    review_usage?: { used: boolean; ids: string[] };
    reference_usage?: { used: boolean; ids: string[] };
    sections?: Array<{ section: string; target: string; objective: string; fact_ids: string[]; copy_classification: string }>;
    auto_approval_history?: Array<{ stage: string; decision: string; rationale: string; checkpoint_id?: string }>;
    stale_artifacts?: Array<{ artifact: string; impact: unknown; reason: string }>;
  };
};

type ProjectAsset = {
  id: string;
  filename: string;
  mime_type: string;
  usage_status: string;
};

async function responseMessage(response: Response, fallback: string) {
  if (response.ok) return "";
  try {
    const body = await response.json();
    if (typeof body?.detail === "string") return body.detail;
    if (body?.detail && typeof body.detail === "object") {
      const code = typeof body.detail.code === "string" ? `[${body.detail.code}] ` : "";
      const message = typeof body.detail.message === "string" ? body.detail.message : fallback;
      const remedy = typeof body.detail.remedy === "string" ? ` 해결 방법: ${body.detail.remedy}` : "";
      return `${code}${message}${remedy}`;
    }
    return fallback;
  } catch {
    return fallback;
  }
}

const splitList = (value: string) => value.split(",").map((item) => item.trim()).filter(Boolean);

export default function CreativeBriefInputPanel({ projectId, runId }: { projectId: string; runId?: string | null }) {
  const [data, setData] = useState<Intelligence | null>(null);
  const [assets, setAssets] = useState<ProjectAsset[]>([]);
  const [reviewText, setReviewText] = useState("");
  const [reviewConsent, setReviewConsent] = useState(false);
  const [reviewRights, setReviewRights] = useState("unverified");
  const [reviewAssetId, setReviewAssetId] = useState("");
  const [referenceKind, setReferenceKind] = useState<ReferenceKind>("url");
  const [referenceValue, setReferenceValue] = useState("");
  const [referenceAssetId, setReferenceAssetId] = useState("");
  const [referenceRights, setReferenceRights] = useState("unverified");
  const [referenceSignals, setReferenceSignals] = useState<string[]>(["palette", "layout", "section_flow"]);
  const [target, setTarget] = useState("");
  const [mood, setMood] = useState("");
  const [emphasis, setEmphasis] = useState("");
  const [forbiddenScenes, setForbiddenScenes] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    const [intelligenceResponse, assetsResponse] = await Promise.all([
      sessionFetch(apiUrl(`/api/v1/projects/${projectId}/creative-intelligence${runId ? `?run_id=${encodeURIComponent(runId)}` : ""}`), { cache: "no-store" }),
      sessionFetch(apiUrl(`/api/v1/projects/${projectId}/assets`), { cache: "no-store" }),
    ]);
    if (intelligenceResponse.ok) setData(await intelligenceResponse.json());
    if (assetsResponse.ok) {
      const body = await assetsResponse.json();
      setAssets(Array.isArray(body) ? body : []);
    }
  }, [projectId, runId]);

  useEffect(() => { void refresh(); }, [refresh]);

  const selectableAssets = useMemo(() => assets.filter((asset) => (
    referenceKind === "image"
      ? asset.mime_type?.startsWith("image/")
      : referenceKind === "pdf" && asset.mime_type === "application/pdf"
  )), [assets, referenceKind]);

  const submitReview = async (body: FormData, success: string) => {
    body.append("consent_status", reviewConsent ? "confirmed" : "unconfirmed");
    body.append("rights_status", reviewRights);
    setBusy(true);
    const response = await sessionFetch(apiUrl(`/api/v1/projects/${projectId}/review-inputs`), { method: "POST", body });
    const error = await responseMessage(response, "리뷰를 저장하지 못했습니다.");
    setMessage(error || success);
    if (response.ok) { setReviewText(""); await refresh(); }
    setBusy(false);
  };

  const addReview = async () => {
    const body = new FormData();
    body.append("text", reviewText);
    body.append("source_label", "판매자 직접 입력");
    await submitReview(body, "리뷰 인사이트를 저장했습니다. 리뷰 문장은 확정 사실로 승격되지 않습니다.");
  };

  const addReviewFile = async (file?: File) => {
    if (!file) return;
    const body = new FormData();
    body.append("file", file);
    body.append("source_label", file.name);
    await submitReview(body, `${file.name} 리뷰를 분석했습니다.`);
  };

  const addReviewAsset = async () => {
    if (!reviewAssetId) return;
    const body = new FormData();
    body.append("source_asset_id", reviewAssetId);
    await submitReview(body, "기존 수집 자료를 리뷰 분석에 연결했습니다.");
    setReviewAssetId("");
  };

  const addReference = async () => {
    const payload = {
      input_kind: referenceKind,
      text: referenceKind === "text" ? referenceValue : "",
      source_url: referenceKind === "url" ? referenceValue : "",
      asset_id: ["image", "pdf"].includes(referenceKind) ? referenceAssetId || null : null,
      rights_status: referenceRights,
      source_metadata: { selected_signals: referenceSignals },
    };
    setBusy(true);
    const response = await sessionFetch(apiUrl(`/api/v1/projects/${projectId}/reference-inputs`), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const error = await responseMessage(response, "레퍼런스를 저장하지 못했습니다.");
    setMessage(error || "레퍼런스의 색감·레이아웃·섹션 흐름만 추상 신호로 저장했습니다. 원문·로고·고유 표현은 복제하지 않습니다.");
    if (response.ok) { setReferenceValue(""); setReferenceAssetId(""); await refresh(); }
    setBusy(false);
  };

  const saveDirection = async () => {
    setBusy(true);
    const response = await sessionFetch(apiUrl(`/api/v1/projects/${projectId}/creative-direction`), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        desired_mood: splitList(mood),
        target_audience: target,
        emphasis: splitList(emphasis),
        forbidden_scenes: splitList(forbiddenScenes),
      }),
    });
    const error = await responseMessage(response, "창작 방향을 저장하지 못했습니다.");
    setMessage(error || "판매자 창작 방향을 새 불변 버전으로 저장했습니다.");
    if (response.ok) await refresh();
    setBusy(false);
  };

  const setMode = async (mode: InteractionMode) => {
    if (!runId) return;
    setBusy(true);
    const response = await sessionFetch(apiUrl(`/api/v1/agent-runs/${runId}/interaction-mode`), {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ interaction_mode: mode }),
    });
    const error = await responseMessage(response, "진행 방식을 변경하지 못했습니다.");
    setMessage(error || `${mode === "quick" ? "빠른 생성" : "전문가 검수"} 모드로 변경했습니다. 기존 산출물은 보존됩니다.`);
    if (response.ok) await refresh();
    setBusy(false);
  };

  return (
    <section className="mx-auto mb-5 max-w-4xl rounded-xl border border-violet-200 bg-white p-5 text-sm">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="font-bold text-slate-900">리뷰·레퍼런스·창작 방향</h2>
          <p className="mt-1 text-xs text-slate-500">LG-7 입력은 상품 사실과 분리되며, 불변 Product Creative Brief로 컴파일됩니다.</p>
        </div>
        <div className="flex gap-2" aria-label="진행 방식">
          <button type="button" onClick={() => void setMode("quick")} disabled={!runId || busy} className={`rounded-lg border px-3 py-2 ${data?.interaction_mode === "quick" ? "bg-emerald-600 text-white" : "bg-white"}`}>빠른 생성</button>
          <button type="button" onClick={() => void setMode("expert")} disabled={!runId || busy} className={`rounded-lg border px-3 py-2 ${data?.interaction_mode === "expert" ? "bg-violet-600 text-white" : "bg-white"}`}>전문가 검수</button>
        </div>
      </div>
      {!runId && <p className="mt-2 text-xs text-amber-700">진행 방식은 LangGraph 실행이 연결된 프로젝트에서 변경할 수 있습니다.</p>}

      <div className="mt-4 grid gap-4 md:grid-cols-3">
        <div className="rounded-lg border p-3">
          <strong>리뷰 전용 입력</strong>
          <textarea aria-label="리뷰 붙여넣기" value={reviewText} onChange={(event) => setReviewText(event.target.value)} className="mt-2 w-full rounded border p-2" rows={4} placeholder="구매 이유, 반복 불만, 자주 쓰는 표현" />
          <label className="mt-2 flex items-center gap-2 text-xs"><input type="checkbox" checked={reviewConsent} onChange={(event) => setReviewConsent(event.target.checked)} />분석 활용 동의를 확인했습니다</label>
          <select aria-label="리뷰 권리 상태" value={reviewRights} onChange={(event) => setReviewRights(event.target.value)} className="mt-2 w-full rounded border p-2">
            <option value="unverified">권리 미확인</option><option value="seller_owned">판매자 보유</option><option value="licensed">사용 허가</option>
          </select>
          <div className="mt-2 flex gap-2">
            <button type="button" disabled={busy || !reviewText.trim()} onClick={() => void addReview()} className="rounded bg-slate-900 px-3 py-2 text-white disabled:opacity-40">분석 저장</button>
            <label className="cursor-pointer rounded border px-3 py-2">CSV/XLSX/TXT<input className="hidden" type="file" accept=".csv,.xlsx,.txt" onChange={(event) => void addReviewFile(event.target.files?.[0])} /></label>
          </div>
          <div className="mt-2 flex gap-2">
            <select aria-label="기존 수집 리뷰 자료" value={reviewAssetId} onChange={(event) => setReviewAssetId(event.target.value)} className="min-w-0 flex-1 rounded border p-2">
              <option value="">기존 수집 자료 선택</option>
              {(data?.review_asset_options ?? []).map((asset) => (
                <option key={asset.id} value={asset.id} disabled={!asset.has_text}>
                  {asset.filename}{asset.has_text ? "" : " · 텍스트 없음"}
                </option>
              ))}
            </select>
            <button type="button" disabled={busy || !reviewAssetId} onClick={() => void addReviewAsset()} className="rounded border px-3 py-2 disabled:opacity-40">자료 연결</button>
          </div>
          <p className="mt-2 text-xs text-rose-700">리뷰는 구매 동기·불만·언어 신호 전용이며 제품 사실로 승격되지 않습니다.</p>
        </div>

        <div className="rounded-lg border p-3">
          <strong>레퍼런스 전용 입력</strong>
          <select aria-label="레퍼런스 종류" value={referenceKind} onChange={(event) => { setReferenceKind(event.target.value as ReferenceKind); setReferenceValue(""); setReferenceAssetId(""); }} className="mt-2 w-full rounded border p-2">
            <option value="url">URL</option><option value="image">프로젝트 이미지</option><option value="pdf">프로젝트 PDF</option><option value="text">텍스트 메모</option>
          </select>
          {(referenceKind === "url" || referenceKind === "text") ? (
            <textarea aria-label="레퍼런스 내용" value={referenceValue} onChange={(event) => setReferenceValue(event.target.value)} className="mt-2 w-full rounded border p-2" rows={3} placeholder={referenceKind === "url" ? "https://..." : "참고할 분위기·섹션 흐름·촬영 무드"} />
          ) : (
            <select aria-label="레퍼런스 파일" value={referenceAssetId} onChange={(event) => setReferenceAssetId(event.target.value)} className="mt-2 w-full rounded border p-2">
              <option value="">파일 선택</option>
              {selectableAssets.map((asset) => <option key={asset.id} value={asset.id}>{asset.filename}</option>)}
            </select>
          )}
          <select aria-label="레퍼런스 권리 상태" value={referenceRights} onChange={(event) => setReferenceRights(event.target.value)} className="mt-2 w-full rounded border p-2">
            <option value="unverified">권리 미확인 · 분석 전용</option><option value="seller_owned">판매자 보유</option><option value="licensed">사용 허가</option><option value="verified">권리 확인</option>
          </select>
          <fieldset className="mt-2"><legend className="text-xs font-semibold">참고할 항목</legend><div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-xs">
            {[["palette", "색감"], ["layout", "레이아웃"], ["section_flow", "섹션 흐름"], ["shoot_mood", "촬영 분위기"], ["copy_tone", "카피 톤"]].map(([value, label]) => (
              <label key={value} className="flex items-center gap-1"><input type="checkbox" checked={referenceSignals.includes(value)} onChange={(event) => setReferenceSignals((current) => event.target.checked ? [...current, value] : current.filter((item) => item !== value))} />{label}</label>
            ))}
          </div></fieldset>
          <button type="button" disabled={busy || ((referenceKind === "url" || referenceKind === "text") ? !referenceValue.trim() : !referenceAssetId)} onClick={() => void addReference()} className="mt-3 rounded bg-slate-900 px-3 py-2 text-white disabled:opacity-40">추상 신호 저장</button>
          <p className="mt-2 text-xs text-amber-700">권리 미확인 자료는 분석 전용입니다. 원문·로고·워터마크·고유 디자인은 복제하지 않습니다.</p>
        </div>

        <div className="rounded-lg border p-3">
          <strong>판매자 창작 방향</strong>
          <input aria-label="타깃 고객" value={target} onChange={(event) => setTarget(event.target.value)} className="mt-2 w-full rounded border p-2" placeholder="예: 출퇴근하는 20~30대" />
          <input aria-label="원하는 분위기" value={mood} onChange={(event) => setMood(event.target.value)} className="mt-2 w-full rounded border p-2" placeholder="깔끔함, 프리미엄" />
          <input aria-label="강조 요소" value={emphasis} onChange={(event) => setEmphasis(event.target.value)} className="mt-2 w-full rounded border p-2" placeholder="휴대성, 저소음" />
          <input aria-label="금지 장면" value={forbiddenScenes} onChange={(event) => setForbiddenScenes(event.target.value)} className="mt-2 w-full rounded border p-2" placeholder="과장 비교, 의료 효능 암시" />
          <button type="button" disabled={busy} onClick={() => void saveDirection()} className="mt-3 rounded bg-violet-600 px-3 py-2 text-white disabled:opacity-40">방향 저장</button>
        </div>
      </div>

      <div className="mt-4 grid gap-2 text-xs sm:grid-cols-4">
        <span>리뷰 {data?.reviews.length ?? 0}개</span><span>레퍼런스 {data?.references.length ?? 0}개</span><span>방향 v{data?.creative_direction?.version ?? 0}</span><span>Brief v{data?.briefs[0]?.version ?? 0}</span>
      </div>
      {(data?.reviews.length || data?.references.length) ? <div className="mt-3 rounded-lg bg-slate-50 p-3 text-xs text-slate-700">
        <strong>Creative Brief 근거 사용 상태</strong>
        <ul className="mt-2 space-y-1">
          {data.reviews.slice(0, 3).map((review) => <li key={review.id}>리뷰 v{review.version} · 창작 인사이트 사용 · 사실 승격 {review.fact_promotion_status === "blocked" ? "차단" : review.fact_promotion_status}</li>)}
          {data.references.slice(0, 3).map((reference) => <li key={reference.id}>레퍼런스 v{reference.version} · {reference.kind} · {reference.usage_scope === "analysis_only" ? "분석 전용" : "권리 확인 자산"}</li>)}
        </ul>
      </div> : null}
      {data?.trace && <details className="mt-3 rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs" open>
        <summary className="cursor-pointer font-bold text-slate-900">생성 추적 정보</summary>
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          <div><strong>현재 모드</strong><p>생성: {data.trace.generation_mode ?? "없음"} · 진행: {data.trace.interaction_mode ?? data.interaction_mode}</p></div>
          <div><strong>Prompt Pack</strong>{(data.trace.prompt_packs ?? []).filter(Boolean).map((pack) => pack && <p key={pack.id}>{pack.kind} · {pack.id} · v{pack.version} · {pack.hash}</p>)}</div>
          <div><strong>Brand Kit</strong><p>{data.trace.brand_kit ? `${data.trace.brand_kit.id} · v${data.trace.brand_kit.version} · ${data.trace.brand_kit.hash}` : "미적용"}</p></div>
          <div><strong>Creative Brief</strong><p>{data.trace.creative_brief ? `${data.trace.creative_brief.id} · v${data.trace.creative_brief.version} · ${data.trace.creative_brief.hash}` : "미생성"}</p></div>
          <div><strong>Creative Direction</strong><p>{data.trace.creative_direction ? `${data.trace.creative_direction.id} · v${data.trace.creative_direction.version} · ${data.trace.creative_direction.hash}` : "미입력"}</p></div>
          <div><strong>입력 사용 여부</strong><p>리뷰 {data.trace.review_usage?.used ? "사용" : "미사용"} · 레퍼런스 {data.trace.reference_usage?.used ? "사용" : "미사용"}</p></div>
          <div><strong>승인 사실</strong><ul>{(data.trace.approved_facts ?? []).map((fact, index) => <li key={fact.id ?? index}>{fact.fact_text ?? fact.text ?? fact.id}</li>)}</ul></div>
          <div><strong>사실 후보</strong><ul>{(data.trace.fact_candidates ?? []).map((fact) => <li key={fact.id}>{fact.text} · {fact.status}</li>)}</ul></div>
        </div>
        <div className="mt-3"><strong>섹션 계약</strong><div className="mt-1 space-y-1">{(data.trace.sections ?? []).map((section, index) => <p key={`${section.section}-${index}`}>{section.section} · target: {section.target} · objective: {section.objective} · facts: {section.fact_ids.join(", ") || "없음"} · copy: {section.copy_classification}</p>)}</div></div>
        <div className="mt-3"><strong>자동 승인 이력</strong><div>{(data.trace.auto_approval_history ?? []).length ? data.trace.auto_approval_history?.map((event, index) => <p key={`${event.stage}-${index}`}>{event.stage} · {event.decision} · {event.rationale}</p>) : <p>없음</p>}</div></div>
        <div className="mt-3"><strong>이전 자료 및 영향 범위</strong><div>{(data.trace.stale_artifacts ?? []).length ? data.trace.stale_artifacts?.map((item, index) => <p key={`${item.artifact}-${index}`}>{item.artifact} · {JSON.stringify(item.impact)} · {item.reason}</p>) : <p>없음</p>}</div></div>
      </details>}
      {message && <p role="status" className={`mt-3 rounded p-2 ${message.startsWith("[") ? "bg-rose-50 text-rose-800" : "bg-emerald-50 text-emerald-800"}`}>{message}</p>}
    </section>
  );
}

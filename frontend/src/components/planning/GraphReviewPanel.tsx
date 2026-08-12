"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { apiUrl } from "@/lib/api";

export type GraphView = {
  run_id: string;
  thread_id: string;
  status: string;
  current_stage: string;
  checkpoint_id?: string | null;
  values: {
    review?: { pending?: ReviewRequest | null };
    generation?: {
      jobs?: Array<{
        job_id: string;
        scene_id?: string;
        section_id?: string;
        role?: string;
        status: string;
        output_asset_id?: string | null;
        error_code?: string | null;
        warnings?: string[];
        source_asset_ids?: string[];
        validation?: {
          schema_version?: string;
          status?: string;
          checks?: Record<string, string>;
          warnings?: string[];
          risk_codes?: string[];
          ocr_text?: string;
        };
        estimated_cost?: number | null;
        actual_cost?: number | null;
        generation_attempt?: number;
        outbox_status?: string | null;
        required_for_completion?: boolean;
      }>;
      estimated_cost?: number;
      actual_cost?: number;
      pending_count?: number;
      review_count?: number;
      failed_job_ids?: string[];
      required_scene_count?: number;
      approved_count?: number;
      remaining_required_scene_ids?: string[];
      all_required_scenes_approved?: boolean;
      cost_plan?: {
        cost_plan_hash: string;
        provider: string;
        model: string;
        scene_count: number;
        scenes: Array<{ scene_id: string; title: string; role: string; model: string; output_size: string; estimated_cost: number }>;
        total_estimated_cost: number;
        currency: string;
        status: string;
      };
    };
    rendering?: {
      detail_page_version?: { id?: string };
    };
    execution?: {
      recoverable?: boolean;
      last_error?: GraphExecutionError | null;
      errors?: GraphExecutionError[];
    };
  };
  next_nodes: string[];
};

type GraphExecutionError = {
  stage?: string;
  code?: string;
  message?: string;
  user_message?: string;
  recovery_action?: string;
  recoverable?: boolean;
};

type ReviewRequest = {
  schema_version: "lg4-v1" | "lg5-v1";
  review_stage: "input_review" | "evidence_review" | "planning_review" | "generation_pending" | "provider_wait" | "image_review";
  title: string;
  description: string;
  allowed_decisions: string[];
  rejection_reason?: string;
};

type UploadAsset = {
  id: string;
  filename: string;
  source_type: string;
  usage_status: string;
  mime_type?: string;
};

type StandaloneExport = {
  html_download_url: string;
  zip_download_url: string;
};

type Props = {
  projectId: string;
  runId?: string | null;
  hidePlanningAction?: boolean;
  onStateChange?: (view: GraphView | null) => void;
};

const validationStatusLabel: Record<string, string> = {
  passed: "통과",
  needs_review: "판매자 확인 필요",
  blocked: "차단",
};

const validationCheckLabel: Record<string, string> = {
  identity: "상품 정체성",
  ocr: "문구/OCR",
  crop: "잘림 안전성",
  resolution: "해상도",
  safety: "안전성",
  rights: "사용 권리",
};

const validationCheckStatusLabel: Record<string, string> = {
  passed: "통과",
  needs_review: "확인 필요",
  blocked: "차단",
  not_run: "실행 전 중단",
};

export default function GraphReviewPanel({ projectId, runId, hidePlanningAction = false, onStateChange }: Props) {
  const [view, setView] = useState<GraphView | null>(null);
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [loadIssue, setLoadIssue] = useState<string | null>(null);
  const [recoveryNotice, setRecoveryNotice] = useState<string | null>(null);
  const [uploadAssets, setUploadAssets] = useState<UploadAsset[]>([]);
  const [uploadByJob, setUploadByJob] = useState<Record<string, string>>({});
  const [standaloneExport, setStandaloneExport] = useState<StandaloneExport | null>(null);
  const [standaloneExporting, setStandaloneExporting] = useState(false);
  const inFlightRef = useRef(false);
  const resolvedRunIdRef = useRef<string | null>(runId ?? null);

  const recoveryStorageKey = useCallback(
    (resolvedRunId: string) => `sellform:graph-review-recovered:${projectId}:${resolvedRunId}`,
    [projectId],
  );

  useEffect(() => {
    resolvedRunIdRef.current = runId ?? null;
  }, [runId]);

  const load = useCallback(async (showLoading = true) => {
    if (showLoading) setLoading(true);
    try {
      setLoadIssue(null);
      const requestedRunId = resolvedRunIdRef.current;
      const requestOptions = { credentials: "include" as const, cache: "no-store" as const };
      const assetPromise = fetch(apiUrl(`/api/v1/projects/${projectId}/assets`), requestOptions);
      let response = await fetch(apiUrl(requestedRunId
        ? `/api/v1/graph-runs/${requestedRunId}`
        : `/api/v1/graph-runs/projects/${projectId}/review`), requestOptions);
      let recoveredFromStaleRun = false;

      if (requestedRunId && response.status === 404) {
        response = await fetch(apiUrl(`/api/v1/graph-runs/projects/${projectId}/review`), requestOptions);
        recoveredFromStaleRun = response.ok;
      }

      const assetResponse = await assetPromise;
    if (response.status === 404) {
      setView(null);
      onStateChange?.(null);
      setRecoveryNotice(null);
        if (requestedRunId) {
          setLoadIssue("이 주소의 LangGraph 실행을 찾을 수 없습니다. 실행이 만료되었거나 새 실행으로 교체되었습니다. 작업 목록에서 현재 실행을 다시 열거나 새 프로젝트 실행을 시작해 주세요.");
        }
        return;
      }
      if (!response.ok) throw new Error("승인 대기 상태를 불러오지 못했습니다.");
      const next = await response.json() as GraphView;
      resolvedRunIdRef.current = next.run_id;
      setView(next);
      onStateChange?.(next);
      if (recoveredFromStaleRun && next.run_id !== requestedRunId) {
        const notice = "만료된 실행 주소를 이 프로젝트의 현재 승인 대기 실행으로 복구했습니다.";
        window.sessionStorage.setItem(recoveryStorageKey(next.run_id), notice);
        const url = new URL(window.location.href);
        url.searchParams.set("runId", next.run_id);
        window.history.replaceState({}, "", `${url.pathname}${url.search}${url.hash}`);
        setRecoveryNotice(notice);
      } else {
        setRecoveryNotice(window.sessionStorage.getItem(recoveryStorageKey(next.run_id)));
      }
      if (assetResponse.ok) {
        const assets = await assetResponse.json() as UploadAsset[];
        setUploadAssets(assets.filter((asset) =>
          ["uploaded", "self_shot"].includes(asset.source_type)
          && asset.usage_status === "seller_owned"
          && (!asset.mime_type || asset.mime_type.startsWith("image/")),
        ));
      }
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "승인 대기 상태를 불러오지 못했습니다.");
    } finally {
      if (showLoading) setLoading(false);
    }
  }, [projectId, onStateChange, recoveryStorageKey]);

  useEffect(() => { void load(); }, [load]);

  useEffect(() => {
    if (view?.current_stage !== "provider_wait") return;
    // Keep the current review card mounted during background polling.  A
    // provider wait may last several seconds; replacing the whole panel with
    // a loading placeholder on every poll makes images appear to vanish.
    const timer = window.setInterval(() => { void load(false); }, 1500);
    return () => window.clearInterval(timer);
  }, [view?.current_stage, load]);

  const resume = async (
    decision: "approve" | "reject" | "defer" | "refresh" | "regenerate" | "upload",
    options: { jobId?: string; assetId?: string } = {},
  ) => {
    if (!view || inFlightRef.current) return;
    const pending = view.values.review?.pending;
    if (!pending) return;
    inFlightRef.current = true;
    setWorking(true); setMessage(null);
    try {
      const response = await fetch(apiUrl(`/api/v1/graph-runs/${view.run_id}/resume`), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({
          thread_id: view.thread_id,
          response: {
            schema_version: pending.schema_version,
            review_stage: pending.review_stage,
            decision,
            ...(view.values.generation?.cost_plan?.cost_plan_hash
              ? { cost_plan_hash: view.values.generation.cost_plan.cost_plan_hash }
              : {}),
            ...(options.jobId ? { job_id: options.jobId } : {}),
            ...(decision === "upload" ? { asset_id: options.assetId, seller_attested: true } : {}),
          },
        }),
      });
      const payload = await response.json().catch(() => null);
      if (!response.ok) {
        const errorMessage = typeof payload?.detail === "string" ? payload.detail : "승인 요청을 처리하지 못했습니다.";
        await load();
        setMessage(errorMessage);
        return;
      }
      setView(payload);
      onStateChange?.(payload);
      // A seller can add or reclassify a rights-owned image while the graph is
      // paused at a review gate. Refresh both the graph and project assets
      // after every successful resume so the per-scene upload selector does
      // not keep the asset list captured when this panel first mounted.
      await load();
      setMessage(decision === "approve" ? "승인을 저장하고 다음 그래프 단계로 진행했습니다." : "현재 실행 상태를 갱신했습니다.");
      // Planning artifacts are persisted while the graph advances from
      // evidence_review to planning_review. Reload once so the editor reads
      // that durable draft instead of manufacturing a legacy fallback.
      if (payload.current_stage === "planning_review") window.setTimeout(() => window.location.reload(), 150);
      if (["completed", "cancelled"].includes(payload.status)) window.setTimeout(() => window.location.reload(), 150);
    } catch (error) {
      await load();
      setMessage(error instanceof Error ? error.message : "승인 요청을 처리하지 못했습니다.");
    } finally {
      inFlightRef.current = false;
      setWorking(false);
    }
  };

  const retryFailedRun = async () => {
    if (!view || inFlightRef.current) return;
    inFlightRef.current = true;
    setWorking(true); setMessage(null);
    try {
      const response = await fetch(apiUrl(`/api/v1/graph-runs/${view.run_id}/resume`), {
        method: "POST",
        credentials: "include",
      });
      const payload = await response.json().catch(() => null);
      if (!response.ok) {
        const errorMessage = payload?.detail || "같은 실행을 재개하지 못했습니다.";
        await load();
        setMessage(errorMessage);
        return;
      }
      setView(payload);
      onStateChange?.(payload);
      setMessage("같은 LangGraph 실행을 재개했습니다.");
      if (payload.current_stage === "planning_review") window.setTimeout(() => window.location.reload(), 150);
    } catch (error) {
      await load();
      setMessage(error instanceof Error ? error.message : "같은 실행을 재개하지 못했습니다.");
    } finally {
      inFlightRef.current = false;
      setWorking(false);
    }
  };

  const createStandaloneExport = async (detailPageVersionId: string) => {
    setStandaloneExporting(true);
    setMessage(null);
    try {
      const response = await fetch(apiUrl(`/api/v1/projects/${projectId}/page/export/standalone`), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ final_version_id: detailPageVersionId }),
      });
      const payload = await response.json().catch(() => null);
      if (!response.ok) {
        throw new Error(typeof payload?.detail === "string" ? payload.detail : "HTML/ZIP 내보내기를 준비하지 못했습니다.");
      }
      setStandaloneExport(payload as StandaloneExport);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "HTML/ZIP 내보내기를 준비하지 못했습니다.");
    } finally {
      setStandaloneExporting(false);
    }
  };

  if (loading) return <section className="mx-auto mb-5 max-w-4xl rounded-xl border border-slate-200 bg-white p-4 text-sm text-slate-500">LangGraph 승인 상태를 확인하는 중...</section>;
  if (view?.status === "failed") {
    const failure = view.values.execution?.last_error;
    return <section role="alert" className="mx-auto mb-5 max-w-4xl rounded-xl border border-rose-300 bg-rose-50 p-5 text-sm text-rose-950">
      <p className="text-xs font-bold text-rose-700">LangGraph 실행 복구 필요 · {failure?.stage || view.current_stage}</p>
      <h2 className="mt-1 font-black">다음 단계로 진행하지 못했습니다</h2>
      <p className="mt-2 leading-6">{failure?.user_message || "실행 중 오류가 발생했습니다. 원인을 해결한 뒤 같은 실행을 다시 시도해 주세요."}</p>
      {failure?.code ? <p className="mt-2 text-xs text-rose-700">오류 코드: {failure.code}</p> : null}
      <div className="mt-4 flex flex-wrap gap-2">
        <button type="button" onClick={() => void load()} disabled={working} className="rounded-lg border border-rose-300 bg-white px-3 py-2 text-xs font-bold text-rose-800 disabled:opacity-50">상태 새로고침</button>
        <button type="button" onClick={() => void retryFailedRun()} disabled={working || failure?.recoverable === false} className="rounded-lg bg-rose-700 px-3 py-2 text-xs font-bold text-white disabled:opacity-50">{working ? "재개 중..." : "원인 해결 후 같은 실행 재시도"}</button>
      </div>
      {message ? <p role="status" className="mt-3 text-xs font-semibold text-rose-800">{message}</p> : null}
    </section>;
  }
  if (!view && loadIssue) {
    return <section role="alert" className="mx-auto mb-5 max-w-4xl rounded-xl border border-amber-300 bg-amber-50 p-5 text-sm text-amber-950">
      <p className="text-xs font-bold text-amber-700">LangGraph 실행 주소 확인 필요</p>
      <h2 className="mt-1 font-black">승인할 실행을 찾지 못했습니다</h2>
      <p className="mt-2 leading-6">{loadIssue}</p>
      <button type="button" onClick={() => void load()} className="mt-4 rounded-lg border border-amber-300 bg-white px-3 py-2 text-xs font-bold text-amber-900">현재 실행 다시 찾기</button>
    </section>;
  }
  const pending = view?.values.review?.pending;
  if (!view) return null;
  if (!pending) {
    const completedJobs = (view.values.generation?.jobs || []).filter((job) => job.output_asset_id);
    const detailPageVersionId = view.values.rendering?.detail_page_version?.id;
    if (view.status === "completed" && (completedJobs.length > 0 || detailPageVersionId)) {
      return <section className="mx-auto mb-5 max-w-4xl rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-950" data-testid="lg5r-completed-gallery">
        <p className="text-xs font-bold text-emerald-700">LangGraph 상세페이지 생성 완료</p>
        <h2 className="mt-1 font-black">{completedJobs.length > 0 ? "승인된 장면 결과" : "정보형 상세페이지 결과"}</h2>
        <p className="mt-1 text-xs leading-5 text-slate-600">{completedJobs.length > 0 ? "이 실행에서 승인한 이미지를 다시 확인할 수 있습니다." : "추가 이미지 생성 없이 정보와 권리 보유 원본으로 상세페이지를 완성했습니다."}</p>
        {completedJobs.length > 0 ? <div className="mt-4 grid gap-3 sm:grid-cols-2">
          {completedJobs.map((job) => <figure key={job.job_id} className="overflow-hidden rounded-lg border border-emerald-100 bg-white">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={apiUrl(`/api/v1/files/assets/${job.output_asset_id}`)} alt={`${job.role || job.section_id || "장면"} 승인 이미지`} className="aspect-square w-full object-contain" loading="lazy" />
            <figcaption className="border-t border-emerald-100 px-3 py-2 text-xs"><b>{job.role || job.section_id || job.job_id}</b> · {job.status}</figcaption>
          </figure>)}
        </div> : null}
        {detailPageVersionId ? <div className="mt-4 flex flex-wrap gap-2">
          <a href={`/workspace/projects/${projectId}/render?version_id=${encodeURIComponent(detailPageVersionId)}`} className="inline-flex rounded-lg bg-emerald-700 px-3 py-2 text-xs font-bold text-white">완성 상세페이지 미리보기</a>
          <button type="button" data-testid="lg10-standalone-export" onClick={() => void createStandaloneExport(detailPageVersionId)} disabled={standaloneExporting} className="rounded-lg border border-emerald-300 bg-white px-3 py-2 text-xs font-bold text-emerald-800 disabled:opacity-50">{standaloneExporting ? "HTML/ZIP 준비 중..." : "HTML/ZIP 내보내기"}</button>
          {standaloneExport ? <><a data-testid="lg10-copyable-html-download" href={apiUrl(standaloneExport.html_download_url)} className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-xs font-bold text-slate-800">HTML 다운로드</a><a data-testid="lg10-standalone-zip-download" href={apiUrl(standaloneExport.zip_download_url)} className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-xs font-bold text-slate-800">ZIP 다운로드</a></> : null}
        </div> : null}
      </section>;
    }
    return null;
  }
  if (hidePlanningAction && pending.review_stage === "planning_review") {
    return <section className="mx-auto mb-5 max-w-4xl rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-900">스토리보드가 승인 대기 중입니다. 아래의 <b>스토리보드 승인</b> 버튼은 동일한 LangGraph 실행을 재개합니다.</section>;
  }
  const generationWaiting = pending.review_stage === "generation_pending";
  const providerWaiting = pending.review_stage === "provider_wait";
  const imageReview = pending.review_stage === "image_review";
  const jobs = view.values.generation?.jobs || [];
  const costPlan = view.values.generation?.cost_plan;
  const errorLabel = (code?: string | null) => ({
    API_KEY_MISSING: "API 키가 없습니다. 키를 설정한 뒤 같은 실행을 재개하세요.",
    BALANCE_OR_LIMIT: "API 잔액 또는 사용 한도를 확인하세요.",
    PROVIDER_TIMEOUT: "제공자 응답 시간이 초과됐습니다. 이 장면만 다시 시도할 수 있습니다.",
    PROVIDER_SAFETY: "제공자 안전 정책에 의해 차단됐습니다. 장면 요청을 수정하세요.",
    IDENTITY_MISMATCH: "상품 외형이 기준 사진과 일치하지 않습니다.",
    OCR_CONTAMINATION: "글자·로고·워터마크 오염이 감지됐습니다.",
    RIGHTS_BLOCKED: "이미지 사용 권리를 확인해야 합니다.",
  }[code || ""] || code || "");
  return <section
    className="mx-auto mb-5 max-w-4xl rounded-xl border border-violet-200 bg-violet-50 p-4 text-sm text-violet-950"
    data-testid={`graph-review-${pending.review_stage}`}
  >
    {recoveryNotice ? <p role="status" className="mb-3 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs font-semibold text-emerald-900">{recoveryNotice}</p> : null}
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div><p className="text-xs font-bold text-violet-700">LangGraph 승인 대기 · {pending.review_stage}</p><h2 className="mt-1 font-black">{pending.title}</h2><p className="mt-1 leading-5 text-slate-700">{pending.description}</p>{pending.rejection_reason ? <p className="mt-2 text-xs text-rose-700">최근 반려 사유: {pending.rejection_reason}</p> : null}</div>
      {generationWaiting ? <div className="flex gap-2"><button type="button" onClick={() => void resume("defer")} disabled={working} className="rounded-lg border border-violet-300 bg-white px-3 py-2 text-xs font-bold text-violet-800 disabled:opacity-50">대기 상태 저장</button><button type="button" onClick={() => void resume("approve")} disabled={working} className="rounded-lg bg-emerald-600 px-3 py-2 text-xs font-bold text-white disabled:opacity-50">{working ? "확인 중..." : "비용 승인 후 이미지 생성"}</button></div> : providerWaiting ? <button type="button" onClick={() => void resume("refresh")} disabled={working} className="rounded-lg border border-violet-300 bg-white px-3 py-2 text-xs font-bold text-violet-800 disabled:opacity-50">{working ? "확인 중..." : "작업 상태 새로고침"}</button> : imageReview ? <p className="rounded-lg bg-white px-3 py-2 text-xs font-bold text-violet-800">아래 장면별로 승인·거절·재생성·직접 업로드를 선택하세요.</p> : <div className="flex gap-2"><button type="button" onClick={() => void resume("reject")} disabled={working} className="rounded-lg border border-rose-300 bg-white px-3 py-2 text-xs font-bold text-rose-700 disabled:opacity-50">수정 후 재검토</button><button type="button" onClick={() => void resume("approve")} disabled={working} className="rounded-lg bg-emerald-600 px-3 py-2 text-xs font-bold text-white disabled:opacity-50">{working ? "승인 중..." : "확인·다음 단계"}</button></div>}
    </div>
    {generationWaiting && costPlan ? <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-950" data-testid="lg5r-cost-plan">
      <p className="font-black">생성 전 비용 확인</p>
      <p className="mt-1">{costPlan.scene_count}개 장면 · {costPlan.provider} / {costPlan.model}</p>
      <ul className="mt-2 space-y-1">
        {costPlan.scenes.map((scene) => <li key={scene.scene_id} className="flex justify-between gap-3"><span>{scene.title} · {scene.output_size}</span><b>{scene.estimated_cost} {costPlan.currency}</b></li>)}
      </ul>
      <p className="mt-2 border-t border-amber-200 pt-2 text-right font-black">총 예상 비용 {costPlan.total_estimated_cost} {costPlan.currency}</p>
    </div> : null}
    {(providerWaiting || imageReview) && jobs.length > 0 ? <div className="mt-4 space-y-2 rounded-lg border border-violet-100 bg-white/70 p-3 text-xs">
      <div className="flex flex-wrap items-center justify-between gap-2"><p className="font-bold text-slate-800">장면별 이미지 작업</p>{imageReview ? <p>{view.values.generation?.approved_count || 0}/{view.values.generation?.required_scene_count || jobs.length}개 필수 장면 승인</p> : null}</div>
      {jobs.map((job) => <article key={job.job_id} className="rounded-md border border-slate-100 p-3" data-testid={`lg5r-scene-${job.scene_id || job.job_id}`}>
        <div className="flex flex-wrap items-start justify-between gap-2"><span><b>{job.role || job.section_id || job.job_id}</b> · {job.status} · 시도 {job.generation_attempt || 1}{job.outbox_status ? ` · worker ${job.outbox_status}` : ""}</span><span>{job.estimated_cost ?? 0} credit</span></div>
        {job.output_asset_id ? <figure className="mt-3 overflow-hidden rounded-lg border border-slate-200 bg-slate-100">
          {/* The authenticated asset endpoint serves both fake-provider previews
              and real provider results, so reviewers always approve a visible image. */}
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={apiUrl(`/api/v1/files/assets/${job.output_asset_id}`)}
            alt={`${job.role || job.section_id || "장면"} 생성 이미지 미리보기`}
            className="aspect-square w-full bg-slate-100 object-contain"
            loading="lazy"
            data-testid={`lg5r-scene-preview-${job.scene_id || job.job_id}`}
          />
          <figcaption className="border-t border-slate-200 bg-white px-3 py-2 text-[11px] text-slate-500">생성 결과 미리보기 · 이미지를 확인한 뒤 승인해 주세요.</figcaption>
        </figure> : imageReview && job.status === "needs_review" ? <p className="mt-3 rounded bg-rose-50 px-3 py-2 text-rose-700">검수할 이미지 파일을 불러오지 못했습니다. 이 장면을 승인하지 말고 상태를 새로고침해 주세요.</p> : null}
        {job.output_asset_id && job.source_asset_ids?.length ? <section className="mt-3 rounded-lg border border-violet-100 bg-violet-50/50 p-3" data-testid={`lg9-scene-comparison-${job.scene_id || job.job_id}`}>
          <p className="text-[11px] font-bold text-violet-900">생성 결과와 기준 사진 비교</p>
          <p className="mt-1 text-[10px] leading-4 text-slate-600">기준 사진은 생성 참고용이며, 최종 사용 여부는 생성 결과와 검사 보고서를 함께 확인해 결정합니다.</p>
          <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-3">
            {job.source_asset_ids.map((assetId, index) => <figure key={assetId} className="overflow-hidden rounded border border-violet-100 bg-white">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={apiUrl(`/api/v1/files/assets/${assetId}`)} alt={`${job.role || job.section_id || "장면"} 기준 사진 ${index + 1}`} className="aspect-square w-full object-contain" loading="lazy" data-testid={`lg9-reference-${job.scene_id || job.job_id}-${assetId}`} />
              <figcaption className="px-2 py-1 text-[10px] text-slate-600">기준 사진 {index + 1}</figcaption>
            </figure>)}
          </div>
        </section> : null}
        {job.validation?.status && job.validation.status !== "pending" ? <section className={`mt-3 rounded-lg border p-3 text-[11px] ${job.validation.status === "blocked" ? "border-rose-200 bg-rose-50 text-rose-900" : job.validation.status === "needs_review" ? "border-amber-200 bg-amber-50 text-amber-950" : "border-emerald-200 bg-emerald-50 text-emerald-950"}`} data-testid={`lg9-validation-${job.scene_id || job.job_id}`}>
          <p className="font-bold">자동 검사 보고서 · {validationStatusLabel[job.validation.status] || job.validation.status}</p>
          {job.validation.checks ? <div className="mt-2 grid gap-1 sm:grid-cols-2">
            {Object.entries(validationCheckLabel).map(([key, label]) => {
              const status = job.validation?.checks?.[key];
              return <p key={key}><b>{label}</b> · {status ? (validationCheckStatusLabel[status] || status) : "미확인"}</p>;
            })}
          </div> : null}
          {job.validation.risk_codes?.length ? <p className="mt-2">감지 항목: {job.validation.risk_codes.join(", ")}</p> : null}
          {job.validation.ocr_text ? <p className="mt-2">감지 문구: {job.validation.ocr_text}</p> : null}
          {job.validation.warnings?.length ? <p className="mt-2">검사 메모: {job.validation.warnings.join(" · ")}</p> : null}
        </section> : null}
        {job.error_code ? <p className="mt-2 text-rose-700">{errorLabel(job.error_code)}</p> : null}
        {imageReview ? <div className="mt-3 flex flex-wrap gap-2">
          {job.status === "needs_review" ? <><button type="button" onClick={() => void resume("approve", { jobId: job.job_id })} disabled={working} className="rounded bg-emerald-600 px-2 py-1 font-bold text-white disabled:opacity-50">이 장면 승인</button><button type="button" onClick={() => void resume("reject", { jobId: job.job_id })} disabled={working} className="rounded border border-rose-300 px-2 py-1 font-bold text-rose-700 disabled:opacity-50">거절</button></> : null}
          {["failed", "blocked", "rejected", "cancelled", "dead_letter", "needs_review"].includes(job.status) ? <button type="button" onClick={() => void resume("regenerate", { jobId: job.job_id })} disabled={working} className="rounded border border-amber-300 px-2 py-1 font-bold text-amber-800 disabled:opacity-50">이 장면 재생성</button> : null}
          {job.status !== "approved" ? <><select aria-label={`${job.job_id} 직접 업로드 사진`} value={uploadByJob[job.job_id] || ""} onChange={(event) => setUploadByJob((current) => ({ ...current, [job.job_id]: event.target.value }))} className="rounded border border-slate-200 bg-white px-2 py-1"><option value="">권리 보유 사진 선택</option>{uploadAssets.map((asset) => <option key={asset.id} value={asset.id}>{asset.filename}</option>)}</select><button type="button" onClick={() => void resume("upload", { jobId: job.job_id, assetId: uploadByJob[job.job_id] })} disabled={working || !uploadByJob[job.job_id]} className="rounded border border-violet-300 px-2 py-1 font-bold text-violet-800 disabled:opacity-50">선택 사진 연결</button></> : null}
        </div> : null}
      </article>)}
      {imageReview && (view.values.generation?.failed_job_ids?.length || 0) > 0 ? <button type="button" onClick={() => void resume("regenerate")} disabled={working} className="rounded border border-amber-300 bg-white px-2 py-1 font-bold text-amber-800 disabled:opacity-50">실패 장면만 재생성</button> : null}
    </div> : null}
    {message ? <p role="status" className="mt-3 text-xs font-semibold text-violet-800">{message}</p> : null}
  </section>;
}

"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { apiUrl } from "@/lib/api";

type StoryboardImageJob = {
  job_id: string;
  section_id: string;
  section_type?: string | null;
  section_title?: string | null;
  role: string;
  source_asset_ids: string[];
  prompt: string;
  negative_prompt: string;
  status: string;
  provider?: string | null;
  model?: string | null;
  attempt_count: number;
  output_asset_id?: string | null;
  error_code?: string | null;
  warnings: string[];
  requires_cost_approval: boolean;
  reference_assets?: Array<{ id: string; filename: string; role: string; usage_status: string; identity_status?: string }>;
  fixed_elements?: string[];
  validation_result?: { status?: string; warnings?: string[]; checks?: Record<string, string>; ocr_text?: string };
  estimated_cost?: number | null;
  actual_cost?: number | null;
  usage_metadata?: Record<string, unknown>;
  seed?: string | null;
  scene_prompt_version_id?: string | null;
  scene_prompt?: {
    id: string;
    scene_id: string;
    scene_type: string;
    version: number;
    objective: string;
    reference_asset_ids: string[];
    prompt_version: string;
    prompt_hash: string;
    reference_hash: string;
    identity_constraints?: Record<string, unknown>;
    composition?: Record<string, unknown>;
    camera?: Record<string, unknown>;
    lighting?: Record<string, unknown>;
    background?: Record<string, unknown>;
    palette?: Record<string, unknown>;
    negative_constraints?: string[];
    text_policy?: Record<string, unknown>;
    rights_snapshot?: Array<Record<string, unknown>>;
    instruction_priority?: string[];
    logo_policy?: string;
    provider?: string;
    model?: string;
    size?: string;
    quality?: string;
    expected_cost?: number;
    seller_adjustment?: string;
    stale_reason?: string | null;
    stale_impact?: Record<string, unknown>;
  } | null;
};

const headers = () => ({ "Content-Type": "application/json" });

const statusLabel: Record<string, string> = {
  planned: "준비됨",
  awaiting_approval: "생성 승인 대기",
  queued: "대기열",
  running: "생성 중",
  generating: "생성 중",
  needs_review: "결과 검토 필요",
  succeeded: "생성 완료",
  failed: "생성 실패",
  blocked: "차단됨",
  approved: "최종 사용 승인",
  rejected: "사용 안 함",
  cancelled: "판매자 취소",
  stale: "이전 버전",
};

const statusClass = (status: string) => {
  if (status === "approved") return "bg-emerald-100 text-emerald-800";
  if (status === "needs_review") return "bg-sky-100 text-sky-800";
  if (status === "blocked" || status === "failed" || status === "cancelled") return "bg-amber-100 text-amber-800";
  if (status === "rejected") return "bg-slate-100 text-slate-600";
  return "bg-violet-100 text-violet-800";
};

export default function StoryboardImageGenerationPanel({ projectId, storyboardStatus }: { projectId: string; storyboardStatus?: string }) {
  const [jobs, setJobs] = useState<StoryboardImageJob[]>([]);
  const [loading, setLoading] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [adjustments, setAdjustments] = useState<Record<string, string>>({});
  const [selectedReferenceIds, setSelectedReferenceIds] = useState<Record<string, string[]>>({});
  const [uploadingJobId, setUploadingJobId] = useState<string | null>(null);
  const [assembling, setAssembling] = useState(false);
  const [imageGenerationAvailable, setImageGenerationAvailable] = useState(false);

  const load = useCallback(async () => {
    const response = await fetch(apiUrl(`/api/v1/projects/${projectId}/storyboard/image-jobs`), { headers: headers(), credentials: "include", cache: "no-store" });
    if (!response.ok) throw new Error("이미지 생성 작업을 불러오지 못했습니다.");
    const payload = await response.json();
    setJobs(payload.jobs || []);
    setImageGenerationAvailable(Boolean(payload.image_generation_available));
  }, [projectId]);

  useEffect(() => {
    if (storyboardStatus === "approved") void load().catch(() => undefined);
  }, [load, storyboardStatus]);

  useEffect(() => {
    if (!jobs.some((job) => ["queued", "running", "generating"].includes(job.status))) return;
    const timer = window.setInterval(() => void load().catch(() => undefined), 2000);
    return () => window.clearInterval(timer);
  }, [jobs, load]);

  const byScene = useMemo(() => {
    const grouped = new Map<string, StoryboardImageJob[]>();
    jobs.forEach((job) => grouped.set(job.section_id, [...(grouped.get(job.section_id) || []), job]));
    // Older projects may still retain a second (-v2) record for audit. Show
    // sellers one deliberate redesign direction per scene instead.
    return Array.from(grouped.values()).map((scene) => [
      [...scene].reverse().find((job) => job.status !== "stale") || scene[scene.length - 1] || scene[0],
    ]);
  }, [jobs]);
  const allRequiredScenesReady = byScene.length > 0 && byScene.every((scene) => scene.some((job) => job.status === "approved"));
  const approvedSceneCount = byScene.filter((scene) => scene.some((job) => job.status === "approved")).length;
  const totalEstimatedCost = byScene.reduce((sum, scene) => sum + Number(scene[0]?.estimated_cost || 0), 0);

  const prepare = async () => {
    setLoading(true); setMessage(null);
    try {
      const response = await fetch(apiUrl(`/api/v1/projects/${projectId}/storyboard/image-jobs`), { method: "POST", headers: headers(), credentials: "include" });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || "장면 작업을 준비하지 못했습니다.");
      setJobs(payload.jobs || []);
      const generationAvailable = Boolean(payload.image_generation_available);
      setImageGenerationAvailable(generationAvailable);
      const nextJobs: StoryboardImageJob[] = payload.jobs || [];
      const sceneCount = new Set(nextJobs.map((job) => job.section_id)).size;
      setMessage(
        sceneCount
          ? generationAvailable
            ? `${sceneCount}개 장면의 리디자인 작업을 준비했습니다. 기준 사진을 확인하고, 생성 전 문장을 수정하거나 생성 승인을 눌러 주세요.`
            : `${sceneCount}개 장면의 최종 이미지 업로드 작업을 준비했습니다. 장면별 완성 이미지를 올린 뒤 외형을 확인해 승인해 주세요.`
          : "리디자인할 이미지 장면을 찾지 못했습니다. 스토리보드에서 이미지 장면을 추가한 뒤 다시 시도해 주세요.",
      );
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "장면 작업 준비에 실패했습니다.");
    } finally { setLoading(false); }
  };

  const action = async (job: StoryboardImageJob, path: string, body?: object) => {
    setBusyId(job.job_id); setMessage(null);
    try {
      const response = await fetch(apiUrl(`/api/v1/projects/${projectId}/storyboard/image-jobs/${job.job_id}${path}`), {
        method: path ? "POST" : "PATCH",
        headers: headers(),
        credentials: "include",
        body: body ? JSON.stringify(body) : undefined,
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || "이미지 작업을 처리하지 못했습니다.");
      setJobs((current) => current.map((item) => item.job_id === job.job_id ? payload : item));
      if (payload.status === "queued") {
        setMessage("생성 작업을 대기열에 넣었습니다. 결과 상태를 자동으로 확인합니다.");
      } else if (payload.status === "blocked" && payload.error_code === "IMAGE_PROVIDER_NOT_CONFIGURED") {
        setMessage("현재 이미지 API가 설정되지 않아 생성은 차단되었습니다. 가짜 이미지로 완료 처리하지 않았습니다.");
      } else if (path === "") {
        setMessage("대표 기준 사진과 장면 요청을 저장했습니다. 다른 사진은 제품 구조 검증용으로만 함께 참고합니다.");
      }
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "이미지 작업 처리에 실패했습니다.");
    } finally { setBusyId(null); }
  };

  const saveAdjustment = (job: StoryboardImageJob) => action(job, "", { instruction: adjustments[job.job_id] || "" });

  const toggleReference = (job: StoryboardImageJob, assetId: string) => {
    setSelectedReferenceIds((current) => {
      const selected = current[job.job_id] || job.source_asset_ids.slice(0, 3);
      const next = selected.includes(assetId)
        ? selected.filter((id) => id !== assetId)
        : [...selected, assetId];
      return { ...current, [job.job_id]: next };
    });
  };

  const saveReferenceSelection = (job: StoryboardImageJob) => {
    const selected = selectedReferenceIds[job.job_id] || job.source_asset_ids.slice(0, 3);
    if (selected.length < 2) {
      setMessage("제품 형태 보존을 위해 대표 상품 사진과 조작부·측면 또는 사용 장면 등 기준 사진을 2장 이상 선택해 주세요.");
      return;
    }
    if (!selected.length) {
      setMessage("AI 리디자인 기준 사진을 한 장 이상 선택해 주세요.");
      return;
    }
    void action(job, "", { instruction: adjustments[job.job_id] || "", source_asset_ids: selected });
  };

  const primaryReference = (job: StoryboardImageJob) => {
    const selectedId = (selectedReferenceIds[job.job_id] || job.source_asset_ids.slice(0, 3))[0];
    return job.reference_assets?.find((asset) => asset.id === selectedId) || job.reference_assets?.[0];
  };

  const uploadManualFinal = async (job: StoryboardImageJob, file?: File) => {
    if (!file) return;
    setUploadingJobId(job.job_id); setMessage(null);
    try {
      const form = new FormData();
      form.append("project_id", projectId);
      form.append("source_type", "uploaded");
      form.append("file", file);
      const uploadedResponse = await fetch(apiUrl("/api/v1/files/upload"), {
        method: "POST",
        credentials: "include",
        body: form,
      });
      const uploaded = await uploadedResponse.json();
      if (!uploadedResponse.ok) throw new Error(uploaded.detail || "완성 이미지 업로드에 실패했습니다.");

      const assignResponse = await fetch(apiUrl(`/api/v1/projects/${projectId}/storyboard/image-jobs/${job.job_id}/manual-output`), {
        method: "POST",
        headers: headers(),
        credentials: "include",
        body: JSON.stringify({ asset_id: uploaded.id, seller_attested: true }),
      });
      const payload = await assignResponse.json();
      if (!assignResponse.ok) throw new Error(payload.detail || "업로드 이미지를 장면에 연결하지 못했습니다.");
      setJobs((current) => current.map((item) => item.job_id === job.job_id ? payload : item));
      setMessage("직접 업로드한 최종 후보를 연결했습니다. 외형·구성품을 확인한 뒤 ‘외형 확인 후 사용’을 눌러 주세요.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "완성 이미지 업로드에 실패했습니다.");
    } finally { setUploadingJobId(null); }
  };

  const assembleDetailPage = async (allowPendingImages = false) => {
    setAssembling(true); setMessage(null);
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 30000);
    try {
      const response = await fetch(apiUrl(`/api/v1/projects/${projectId}/planning-draft/approve`), {
        method: "POST",
        headers: headers(),
        credentials: "include",
        body: JSON.stringify({ allow_pending_images: allowPendingImages }),
        signal: controller.signal,
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || "상세페이지 반영에 실패했습니다.");
      setMessage(
        allowPendingImages
          ? "AI 이미지 없이 상세페이지 초안을 만들었습니다. 결과 화면을 새로 불러옵니다."
          : "승인한 장면 이미지를 상세페이지에 반영했습니다. 결과 화면을 새로 불러옵니다.",
      );
      // A hard navigation prevents the previous result-page cache from making
      // a newly assembled text-first draft look as though the button did nothing.
      window.location.assign(`/workspace/projects/${projectId}/result`);
    } catch (error) {
      setMessage(
        error instanceof DOMException && error.name === "AbortError"
          ? "상세페이지 반영 요청이 30초 안에 끝나지 않았습니다. 백엔드 상태를 확인한 뒤 다시 시도해 주세요."
          : error instanceof Error ? error.message : "상세페이지 반영에 실패했습니다.",
      );
    } finally { window.clearTimeout(timeout); setAssembling(false); }
  };

  if (storyboardStatus !== "approved") return null;
  return (
    <section className="rounded-2xl border border-violet-200 bg-violet-50/50 p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="font-extrabold text-slate-900">{imageGenerationAvailable ? "AI 리디자인 이미지" : "장면별 완성 이미지 업로드"}</h3>
          <p className="mt-1 text-xs leading-5 text-slate-600">{imageGenerationAvailable ? "공급처 사진은 생성 참고 입력으로만 사용합니다. 원본 레이아웃·중국어 문구·로고를 그대로 출력하지 않습니다." : "현재 이미지 API가 연결되지 않아, 장면별로 직접 준비한 최종 리디자인 이미지를 업로드해 상세페이지를 완성합니다."}</p>
        </div>
        <button type="button" onClick={prepare} disabled={loading} className="rounded-xl bg-violet-700 px-4 py-2.5 text-xs font-bold text-white disabled:opacity-50">
          {loading ? "준비 중…" : jobs.length ? "장면 작업 다시 확인" : imageGenerationAvailable ? "AI 리디자인 장면 준비" : "업로드할 장면 준비"}
        </button>
      </div>
      {message && <p role="status" className="mt-3 rounded-lg border border-violet-100 bg-white px-3 py-2 text-xs text-slate-700">{message}</p>}
      {imageGenerationAvailable && jobs.length > 0 && <p className="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-950"><b>생성 전 비용 확인:</b> {byScene.length}개 장면 · 장면당 1024×1024 · 예상 합계 {totalEstimatedCost} 크레딧. 다시 만들기는 해당 장면의 예상 비용이 다시 발생할 수 있습니다.</p>}
      {jobs.length > 0 && <div className={`mt-4 flex flex-wrap items-center justify-between gap-3 rounded-xl border p-3 ${allRequiredScenesReady ? "border-emerald-200 bg-emerald-50" : "border-amber-200 bg-amber-50"}`}>
        <div>
          <p className="text-xs font-extrabold text-slate-900">상세페이지 생성</p>
          {allRequiredScenesReady ? <p className="mt-1 text-xs leading-5 text-emerald-900">모든 장면의 최종 이미지가 승인되었습니다. 이 이미지들로 상세페이지를 만들 수 있습니다.</p> : <p className="mt-1 text-xs leading-5 text-amber-900">이미지 준비 {approvedSceneCount}/{byScene.length}장면 완료. 각 장면에서 AI 생성 승인 또는 완성 이미지 직접 업로드 후 ‘외형 확인 후 사용’을 눌러 주세요.</p>}
        </div>
        <button type="button" onClick={() => void assembleDetailPage()} disabled={!allRequiredScenesReady || assembling} title={allRequiredScenesReady ? "승인된 장면 이미지로 상세페이지 만들기" : "모든 장면에 최종 이미지 1개씩을 승인한 뒤 사용할 수 있습니다."} className="rounded-lg bg-emerald-600 px-3 py-2 text-xs font-bold text-white disabled:cursor-not-allowed disabled:opacity-45">{assembling ? "상세페이지 반영 중…" : "승인 이미지로 상세페이지 만들기"}</button>
      </div>}
      {jobs.length > 0 && !allRequiredScenesReady && <div className="mt-3 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-sky-200 bg-sky-50 p-3 text-xs text-sky-950"><p><b>AI 이미지 생성 대기:</b> 지금은 텍스트·구조만 상세페이지에 반영하고, 나중에 이 화면에서 생성한 이미지를 장면별로 승인해 교체할 수 있습니다.</p><button type="button" onClick={() => void assembleDetailPage(true)} disabled={assembling} className="rounded-lg bg-sky-700 px-3 py-2 font-bold text-white disabled:opacity-50">생성 대기 상태로 상세페이지 만들기</button></div>}
      {jobs.length > 0 && !allRequiredScenesReady && <ol className="mt-3 grid gap-2 rounded-xl border border-violet-100 bg-white p-3 text-[11px] leading-5 text-slate-700 md:grid-cols-4">
        {imageGenerationAvailable ? <><li><strong>1. 기준 사진 2장 저장</strong><br />전체 제품과 조작부·측면 또는 사용 장면을 함께 고릅니다.</li><li><strong>2. AI 생성 승인</strong><br />리디자인 결과를 생성합니다.</li></> : <><li><strong>1. 장면 이미지 업로드</strong><br />직접 만든 최종 리디자인 이미지를 올립니다.</li><li><strong>2. 외형 확인</strong><br />장면과 제품 외형이 맞는지 확인합니다.</li></>}
        <li><strong>3. 외형 확인 후 사용</strong><br />올린 최종 이미지를 승인합니다.</li>
        <li><strong>4. 상세페이지 만들기</strong><br />모든 장면 승인 뒤 버튼이 활성화됩니다.</li>
      </ol>}
      {!jobs.length ? <p className="mt-4 text-sm text-slate-500">승인된 스토리보드에서 이미지가 필요한 장면을 먼저 준비해 주세요. 생성 비용은 실행 직전에만 승인합니다.</p> : (
        <div className="mt-5 space-y-4">
          {byScene.map((scene) => {
            const title = scene[0]?.section_title || scene[0]?.section_type || "이미지 장면";
            return <article key={scene[0].section_id} className="rounded-xl border border-white bg-white p-4 shadow-sm">
              <div className="flex flex-wrap items-center justify-between gap-2"><div><h4 className="font-bold text-slate-900">{title}</h4><p className="mt-1 text-[11px] text-slate-500">리디자인 장면 1개 · 상품 구조 보존 필수 · 공급처 원본은 최종 출력 불가</p></div></div>
              <div className="mt-3 w-full">
                {scene.map((job) => <div key={job.job_id} className="rounded-lg border border-slate-200 p-3">
                  <div className="flex items-center justify-between gap-2"><strong className="text-xs text-slate-800">리디자인 장면</strong><span className={`rounded-full px-2 py-1 text-[10px] font-bold ${statusClass(job.status)}`}>{statusLabel[job.status] || job.status}</span></div>
                  {job.output_asset_id ? <div className="mt-3 grid gap-2 sm:grid-cols-2"><figure className="relative"><img src={apiUrl(`/api/v1/files/assets/${job.output_asset_id}`)} alt={`${title} AI 리디자인 결과`} className="aspect-square w-full rounded-md border border-slate-100 object-cover" />{job.status !== "approved" && <figcaption className="absolute left-2 top-2 rounded-full bg-amber-500 px-2 py-1 text-[10px] font-extrabold text-white">판매자 검수 전</figcaption>}<p className="mt-1 text-center text-[10px] font-bold text-slate-600">생성 결과</p></figure>{primaryReference(job) && <figure><img src={apiUrl(`/api/v1/files/assets/${primaryReference(job)?.id}`)} alt={`${primaryReference(job)?.filename} 제품 기준 사진`} className="aspect-square w-full rounded-md border border-slate-100 object-cover" /><figcaption className="mt-1 text-center text-[10px] font-bold text-slate-600">제품 기준 사진</figcaption></figure>}</div> : imageGenerationAvailable && primaryReference(job) ? <div className="relative mt-3 aspect-square overflow-hidden rounded-md border border-violet-100 bg-slate-50"><img src={apiUrl(`/api/v1/files/assets/${primaryReference(job)?.id}`)} alt={`${primaryReference(job)?.filename} AI 리디자인 참고 사진`} className="h-full w-full object-cover opacity-45 grayscale" /><div className="absolute inset-0 flex items-center justify-center bg-slate-950/15 p-4 text-center text-[11px] font-bold leading-5 text-slate-800"><span className="rounded-md bg-white/90 px-3 py-2">AI 생성 전 참고용<br />최종 출력에는 사용되지 않음</span></div></div> : <div className="mt-3 flex aspect-[4/3] items-center justify-center rounded-md border border-dashed border-emerald-200 bg-emerald-50/60 p-4 text-center text-[11px] font-semibold leading-5 text-emerald-800">{imageGenerationAvailable && (job.status === "queued" || job.status === "running" || job.status === "generating") ? "AI가 새 장면을 만드는 중입니다" : "업로드한 최종 리디자인 이미지가 이곳에 표시됩니다"}</div>}
                  {!imageGenerationAvailable && !job.output_asset_id && job.status !== "approved" && <div className="mt-3 rounded-lg border border-emerald-200 bg-emerald-50 p-3"><p className="text-xs font-bold text-emerald-950">이 장면에 사용할 완성 이미지를 업로드하세요.</p><p className="mt-1 text-[11px] leading-4 text-emerald-900">공급처 원본이 아닌, 직접 제작하거나 리디자인한 최종 이미지만 올릴 수 있습니다.</p><label className="mt-3 inline-flex cursor-pointer rounded-md bg-emerald-600 px-3 py-2 text-[11px] font-bold text-white disabled:opacity-50">{uploadingJobId === job.job_id ? "업로드 중…" : "이 장면 이미지 업로드"}<input type="file" accept="image/png,image/jpeg,image/webp" className="sr-only" disabled={uploadingJobId === job.job_id} onChange={(event) => { void uploadManualFinal(job, event.target.files?.[0]); event.currentTarget.value = ""; }} /></label></div>}
                  {job.scene_prompt && <details data-testid={`scene-prompt-${job.section_id}`} className="mt-3 rounded-lg border border-violet-100 bg-violet-50/60 p-3 text-[11px] text-slate-700">
                    <summary className="cursor-pointer font-bold text-violet-900">장면 프롬프트 v{job.scene_prompt.version} · {job.scene_prompt.scene_type}</summary>
                    <div className="mt-2 grid gap-1.5 sm:grid-cols-2">
                      <p><b>목표</b> {job.scene_prompt.objective}</p>
                      <p><b>기준 사진</b> {job.scene_prompt.reference_asset_ids.length}장</p>
                      <p><b>Prompt hash</b> <code>{job.scene_prompt.prompt_hash.slice(0, 12)}</code></p>
                      <p><b>Reference hash</b> <code>{job.scene_prompt.reference_hash.slice(0, 12)}</code></p>
                      <p><b>모델</b> {job.scene_prompt.provider}/{job.scene_prompt.model} · {job.scene_prompt.size}</p>
                      <p><b>예상 비용</b> {job.scene_prompt.expected_cost ?? 0} credit</p>
                      <p><b>로고 정책</b> {job.scene_prompt.logo_policy === "renderer_only" ? "정확한 로고는 별도 렌더러가 합성" : "로고 사용 안 함"}</p>
                      <p><b>권리 스냅샷</b> {job.scene_prompt.rights_snapshot?.length ?? 0}개 기준 사진</p>
                    </div>
                    <p className="mt-2"><b>명령 우선순위</b> {(job.scene_prompt.instruction_priority || []).join(" → ")}</p>
                    <p className="mt-2 rounded bg-white px-2 py-1.5 font-semibold text-slate-800">이미지 안에 최종 한글 문구를 넣지 않습니다. 정확한 한국어는 별도 텍스트 렌더러가 합성합니다.</p>
                    {job.scene_prompt.seller_adjustment && <p className="mt-2"><b>판매자 조정</b> {job.scene_prompt.seller_adjustment}</p>}
                  </details>}
                  {imageGenerationAvailable && <><p className="mt-2 line-clamp-3 text-[11px] leading-5 text-slate-600">{job.prompt}</p><p className="mt-2 text-[10px] text-slate-500">예상 비용 {job.estimated_cost ?? 0} 크레딧{job.actual_cost != null ? ` · 제공자 보고 비용 ${job.actual_cost}` : ""} · 모델 {job.model || "설정 대기"} · 시드 {job.seed || "제공자 미지원"}</p></>}
                  {imageGenerationAvailable && job.reference_assets?.length ? <div className="mt-2"><p className="text-[10px] font-bold text-slate-600">AI 리디자인 기준 사진</p><p className="mt-0.5 text-[10px] leading-4 text-slate-500">{job.status === "approved" ? "최종 승인된 결과의 기준 사진이 고정됩니다." : "전체 제품 사진과 조작부·측면 또는 사용 장면을 포함해 2~3장을 선택하세요. 이 사진은 AI 생성 참고용이며, 공급처 원본 자체를 최종 승인하지는 않습니다."}</p><div className="mt-2 flex flex-wrap gap-2">{job.reference_assets.map((asset) => { const selected = (selectedReferenceIds[job.job_id] || job.source_asset_ids.slice(0, 3)).includes(asset.id); return <button key={asset.id} type="button" disabled={job.status === "approved"} onClick={() => toggleReference(job, asset.id)} className={`block w-16 rounded-md p-0.5 text-left disabled:cursor-not-allowed disabled:opacity-70 ${selected ? "ring-2 ring-violet-600" : "ring-1 ring-slate-200"}`} title={`${asset.filename} · ${asset.role}`}><img src={apiUrl(`/api/v1/files/assets/${asset.id}`)} alt={`${asset.filename} 기준 사진`} className="aspect-square w-full rounded object-cover" /><span className="mt-1 block truncate px-0.5 text-[9px] text-slate-600">{selected ? "선택됨" : asset.filename}</span></button>; })}</div>{job.status !== "approved" && <button type="button" onClick={() => saveReferenceSelection(job)} disabled={busyId === job.job_id} className="mt-2 rounded-md border border-violet-300 bg-violet-50 px-2.5 py-1.5 text-[11px] font-bold text-violet-800 disabled:opacity-50">기준 사진 저장</button>}<p className="mt-1 text-[10px] leading-4 text-slate-500">{(job.fixed_elements || []).join(" · ")}</p></div> : null}
                  {job.validation_result?.status && <p className={`mt-2 rounded px-2 py-1 text-[10px] font-semibold ${job.validation_result.status === "blocked" ? "bg-rose-50 text-rose-700" : job.validation_result.status === "needs_review" ? "bg-amber-50 text-amber-700" : "bg-emerald-50 text-emerald-700"}`}>검사: {job.validation_result.status === "passed" ? "통과" : job.validation_result.status === "needs_review" ? "외형·문구 확인 필요" : job.validation_result.status}</p>}
                  {imageGenerationAvailable && <textarea data-testid={`scene-adjustment-${job.section_id}`} value={adjustments[job.job_id] ?? job.scene_prompt?.seller_adjustment ?? ""} onChange={(event) => setAdjustments((current) => ({ ...current, [job.job_id]: event.target.value }))} placeholder="예: 밝은 거실, 손이 보이지 않는 제품 중심 구도" className="mt-3 min-h-16 w-full rounded-md border border-slate-200 p-2 text-xs" />}
                  {job.warnings?.length > 0 && <p className="mt-2 text-[11px] leading-4 text-amber-700">{job.warnings[0]}</p>}
                  <div className="mt-3 flex flex-wrap gap-2">
                    {imageGenerationAvailable && <button data-testid={`scene-adjustment-save-${job.section_id}`} type="button" onClick={() => saveAdjustment(job)} disabled={busyId === job.job_id} className="rounded-md border border-slate-300 px-2.5 py-1.5 text-[11px] font-semibold text-slate-700 disabled:opacity-50">수정 저장</button>}
                    {imageGenerationAvailable && job.status !== "approved" && <label className="cursor-pointer rounded-md border border-emerald-300 bg-emerald-50 px-2.5 py-1.5 text-[11px] font-bold text-emerald-800 disabled:opacity-50">
                      {uploadingJobId === job.job_id ? "업로드 중…" : "완성된 리디자인 이미지 업로드"}
                      <input
                        type="file"
                        accept="image/png,image/jpeg,image/webp"
                        className="sr-only"
                        disabled={uploadingJobId === job.job_id}
                        onChange={(event) => { void uploadManualFinal(job, event.target.files?.[0]); event.currentTarget.value = ""; }}
                      />
                    </label>}
                    {imageGenerationAvailable && (job.status === "awaiting_approval" || job.status === "blocked" || job.status === "failed") && <button type="button" onClick={() => action(job, "/start", { cost_approved: true })} disabled={busyId === job.job_id} className="rounded-md bg-violet-700 px-2.5 py-1.5 text-[11px] font-bold text-white disabled:opacity-50">생성 승인·실행</button>}
                    {imageGenerationAvailable && (job.status === "awaiting_approval" || job.status === "queued") && <button type="button" onClick={() => action(job, "/cancel")} disabled={busyId === job.job_id} className="rounded-md border border-amber-300 px-2.5 py-1.5 text-[11px] font-semibold text-amber-800">생성 취소</button>}
                    {imageGenerationAvailable && (job.status === "needs_review" || job.status === "rejected" || job.status === "failed" || job.status === "blocked" || job.status === "cancelled") && <button type="button" onClick={() => action(job, "/regenerate")} disabled={busyId === job.job_id} className="rounded-md border border-violet-300 px-2.5 py-1.5 text-[11px] font-semibold text-violet-800">다시 만들기</button>}
                    {job.status === "needs_review" && <><button type="button" onClick={() => action(job, "/approve", { identity_confirmed: true })} disabled={busyId === job.job_id} className="rounded-md bg-emerald-600 px-2.5 py-1.5 text-[11px] font-bold text-white">외형 확인 후 사용</button><button type="button" onClick={() => action(job, "/reject")} disabled={busyId === job.job_id} className="rounded-md border border-slate-300 px-2.5 py-1.5 text-[11px] font-semibold text-slate-700">사용 안 함</button></>}
                  </div>
                </div>)}
              </div>
            </article>;
          })}
        </div>
      )}
    </section>
  );
}

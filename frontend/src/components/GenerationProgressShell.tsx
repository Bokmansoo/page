"use client";

import React, { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { apiUrl } from "@/lib/api";
import {
  BACKEND_STAGE_GROUPS,
  monotonicProgressStage,
  progressStepIndex,
} from "@/lib/generationProgress";

interface GenerationProgressShellProps {
  runId: string;
}

interface SalesStrategy {
  hook_headline?: string;
  tone_and_manner?: string;
}

interface VisualPlan {
  color_palette?: string[];
}

interface GeneratedAsset {
  id: string;
  url: string;
  source_type: string;
}

interface PageSection {
  id: string;
  title: string;
  body: string;
  visual_role: string;
  image_id: string;
}

interface AgentOutputs {
  sales_strategy?: SalesStrategy;
  visual_plan?: VisualPlan;
  generated_assets?: {
    images: GeneratedAsset[];
  };
  page_assembly?: {
    sections: PageSection[];
  };
  image_generation?: {
    jobs?: Array<{
      slot_id?: string;
      status?: string;
      error_code?: string | null;
    }>;
  };
}

interface RunResponse {
  project_id: string;
  outputs: AgentOutputs;
}

interface RunProgressResponse {
  status: string;
  current_stage: string;
  completed_stages: string[];
  failed_stage?: string | null;
  error_message?: string | null;
}

interface CachedGenerationResult {
  projectId: string;
  outputs: AgentOutputs;
}

const GENERATION_STEPS = [
  "상품 이해",
  "판매 방향 추천",
  "상세페이지 구조 설계",
  "문구 생성",
  "이미지 연출 기획",
  "이미지 생성",
  "상세페이지 조립",
  "검수",
] as const;

function sourceLabel(sourceType: string): string {
  switch (sourceType) {
    case "uploaded":
      return "직접 업로드";
    case "url-extracted":
    case "url-imported":
      return "URL 추출";
    case "mock-generated":
      return "AI 모의 생성";
    case "real-generated":
      return "AI 생성 이미지";
    case "ai-generated":
      return "AI 생성";
    case "generation-skipped":
      return "생성 생략";
    case "blocked_cost_approval":
      return "이미지 생성 비용 승인 필요";
    case "needs_review":
      return "상품 정체성 검수 필요";
    default:
      return sourceType || "출처 없음";
  }
}

export default function GenerationProgressShell({ runId }: GenerationProgressShellProps) {
  const router = useRouter();
  const [currentStage, setCurrentStage] = useState("input_router");
  const [completedStages, setCompletedStages] = useState<string[]>([]);
  const [runStatus, setRunStatus] = useState("created");
  const [projectId, setProjectId] = useState<string | null>(null);
  const [isApiCompleted, setIsApiCompleted] = useState(false);
  const [outputs, setOutputs] = useState<AgentOutputs | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const cacheKey = `sellform:generation:${runId}`;
    const cached = typeof window !== "undefined" ? sessionStorage.getItem(cacheKey) : null;
    if (cached) {
      try {
        const parsed = JSON.parse(cached) as CachedGenerationResult;
        if (parsed.projectId && parsed.outputs) {
          setProjectId(parsed.projectId);
          setOutputs(parsed.outputs);
          setIsApiCompleted(true);
          setCompletedStages(BACKEND_STAGE_GROUPS.flat());
          setCurrentStage("qa_review");
          setRunStatus("completed");
          return;
        }
      } catch {
        sessionStorage.removeItem(cacheKey);
      }
    }

    let cancelled = false;
    const uid = localStorage.getItem("X-Mock-User-Id") || "00000000-0000-0000-0000-000000000001";
    const wid = localStorage.getItem("X-Mock-Workspace-Id") || "00000000-0000-0000-0000-000000000002";
    const headers = {
      "Content-Type": "application/json",
      "X-Mock-User-Id": uid,
      "X-Mock-Workspace-Id": wid,
    };

    const pollProgress = async () => {
      try {
        const res = await fetch(apiUrl(`/api/agent-runs/${runId}/status`), {
          headers,
          cache: "no-store",
        });
        if (!res.ok || cancelled) return;
        const progress = (await res.json()) as RunProgressResponse;
        setCurrentStage((previous) =>
          monotonicProgressStage(previous, progress.current_stage)
        );
        setCompletedStages((previous) =>
          Array.from(new Set([...previous, ...(progress.completed_stages || [])]))
        );
        setRunStatus((previous) =>
          previous === "completed" || previous === "failed"
            ? previous
            : progress.status
        );
        if (progress.status === "failed") {
          setError(
            progress.error_message ||
              `${progress.failed_stage || "에이전트"} 단계에서 생성에 실패했습니다.`
          );
        }
      } catch {
        // The generation request remains authoritative; retry on the next poll.
      }
    };

    const runGeneration = async () => {
      try {
        const res = await fetch(apiUrl(`/api/agent-runs/${runId}/run`), {
          method: "POST",
          headers,
        });

        if (!res.ok) throw new Error("상세페이지 생성 요청에 실패했습니다.");
        const data = (await res.json()) as RunResponse;
        if (cancelled) return;
        setProjectId(data.project_id);
        setOutputs(data.outputs);
        setIsApiCompleted(true);
        setCompletedStages(BACKEND_STAGE_GROUPS.flat());
        setCurrentStage("qa_review");
        setRunStatus("completed");
        if (typeof window !== "undefined") {
          sessionStorage.setItem(
            cacheKey,
            JSON.stringify({
              projectId: data.project_id,
              outputs: data.outputs,
            })
          );
        }
      } catch (err) {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "상세페이지 생성 중 오류가 발생했습니다.");
      } finally {
        window.clearInterval(pollTimer);
        void pollProgress();
      }
    };

    void pollProgress();
    const pollTimer = window.setInterval(pollProgress, 500);
    void runGeneration();

    return () => {
      cancelled = true;
      window.clearInterval(pollTimer);
    };
  }, [runId]);

  const pageAssembly = outputs?.page_assembly;
  const generatedAssets = outputs?.generated_assets;
  const visualPlan = outputs?.visual_plan;
  const currentStepIdx = progressStepIndex(currentStage);
  const isFinished = isApiCompleted;
  const failedImageJobs =
    outputs?.image_generation?.jobs?.filter((job) =>
      ["provider_error", "missing_reference_asset", "asset_persist_failed"].includes(job.status || "")
    ) || [];

  const handleNavigate = () => {
    if (projectId) router.push(`/workspace/projects/${projectId}/result`);
  };

  if (isFinished && failedImageJobs.length > 0) {
    const firstError = failedImageJobs[0]?.error_code || failedImageJobs[0]?.status || "이미지 생성 실패";
    return (
      <div className="min-h-[620px] flex items-center justify-center p-6">
        <div className="w-full max-w-xl rounded-2xl border border-rose-200 bg-white p-8 text-center shadow-sm">
          <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-rose-50 text-xl font-bold text-rose-600">
            !
          </div>
          <h2 className="text-xl font-extrabold text-slate-950">이미지 생성이 완료되지 않았습니다</h2>
          <p className="mt-3 text-sm leading-relaxed text-slate-600">
            상품과 무관한 원본 이미지를 반복 배치하지 않도록 생성을 중단했습니다.
            이미지 모델 설정과 API 권한을 확인한 뒤 다시 생성해 주세요.
          </p>
          <p className="mt-4 rounded-lg bg-slate-50 px-4 py-3 font-mono text-xs text-slate-600">
            {firstError}
          </p>
          <button
            type="button"
            onClick={() => router.push("/workspace")}
            className="mt-6 rounded-lg bg-emerald-600 px-5 py-3 text-sm font-bold text-white hover:bg-emerald-700"
          >
            입력 화면으로 돌아가기
          </button>
        </div>
      </div>
    );
  }

  if (isFinished && pageAssembly) {
    return (
      <div className="min-h-screen bg-slate-50 text-slate-800 flex flex-col items-center p-6 w-full max-w-4xl mx-auto space-y-6">
        <div className="w-full bg-white rounded-2xl border border-slate-200 p-5 flex items-center justify-between shadow-sm">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-full bg-emerald-500 text-white flex items-center justify-center font-bold text-lg">✓</div>
            <div>
              <h2 className="font-extrabold text-slate-900">상세페이지 생성 완료</h2>
              <p className="text-xs text-slate-500">상품별 이미지 후보와 판매 문구를 조립했습니다.</p>
            </div>
          </div>
          <button
            type="button"
            onClick={handleNavigate}
            className="px-4 py-2 bg-emerald-600 hover:bg-emerald-700 text-white rounded-xl text-xs font-bold transition-all shadow-md shadow-emerald-600/10"
          >
            생성된 상세페이지 보기
          </button>
        </div>

        <div className="grid md:grid-cols-[300px_1fr] gap-6 w-full items-start">
          <aside className="space-y-4">
            {visualPlan?.color_palette?.length ? (
              <div className="bg-white border border-slate-200 rounded-2xl p-5 shadow-sm">
                <h3 className="font-bold text-slate-900 mb-4">AI 추천 컬러 팔레트</h3>
                <div className="flex gap-3">
                  {visualPlan.color_palette.slice(0, 4).map((color) => (
                    <div key={color} className="space-y-2 text-center">
                      <div className="w-10 h-10 rounded-full border border-slate-200" style={{ backgroundColor: color }} />
                      <span className="text-[10px] font-bold text-slate-400">{color}</span>
                    </div>
                  ))}
                </div>
              </div>
            ) : null}

            {outputs?.sales_strategy ? (
              <div className="bg-white border border-slate-200 rounded-2xl p-5 shadow-sm space-y-3">
                <h3 className="font-bold text-slate-900">AI 마케팅 제안</h3>
                <div>
                  <p className="text-[11px] font-bold text-slate-400">후킹 헤드라인</p>
                  <p className="text-sm font-bold text-slate-900 leading-relaxed">{outputs.sales_strategy.hook_headline}</p>
                </div>
                <div>
                  <p className="text-[11px] font-bold text-slate-400">톤앤매너</p>
                  <p className="text-sm text-slate-700 leading-relaxed">{outputs.sales_strategy.tone_and_manner}</p>
                </div>
              </div>
            ) : null}
          </aside>

          <main className="bg-white border border-slate-200 rounded-[28px] p-6 shadow-sm">
            <h3 className="font-bold text-slate-900 mb-4">완성 상세페이지 미리보기</h3>
            <div className="mx-auto w-[360px] max-w-full h-[620px] overflow-y-auto rounded-[32px] border-[10px] border-slate-900 bg-white shadow-xl">
              {pageAssembly.sections.map((section) => {
                const image = generatedAssets?.images?.find((asset) => asset.id === section.image_id);
                return (
                  <section key={section.id} className="p-5 border-b border-slate-100 space-y-3">
                    <span className="text-[10px] font-extrabold text-emerald-600 tracking-widest uppercase">{section.visual_role}</span>
                    <h4 className="text-sm font-extrabold text-slate-900 leading-snug">{section.title}</h4>
                    <p className="text-xs text-slate-600 leading-relaxed">{section.body}</p>
                    {image ? (
                      <div className="relative overflow-hidden rounded-xl border border-slate-100 bg-slate-50 aspect-video">
                        <img src={image.url} alt={section.title} className="w-full h-full object-cover" />
                        <span className="absolute top-2 right-2 rounded-full bg-emerald-600 px-2 py-0.5 text-[9px] font-bold text-white">
                          {sourceLabel(image.source_type)}
                        </span>
                      </div>
                    ) : null}
                  </section>
                );
              })}
            </div>
          </main>
        </div>

        <button
          type="button"
          onClick={handleNavigate}
          className="w-full max-w-[520px] py-4 bg-emerald-600 hover:bg-emerald-700 text-white rounded-2xl font-extrabold transition-all shadow-lg shadow-emerald-600/15"
        >
          생성된 상세페이지 보기
        </button>
      </div>
    );
  }

  return (
    <div className="min-h-[520px] flex items-center justify-center p-6">
      <div className="w-full max-w-xl bg-white rounded-[28px] border border-slate-100 shadow-sm p-8 space-y-6">
        <h2 className="text-2xl font-extrabold text-slate-900 text-center">AI 상세페이지 생성 진행 중...</h2>
        {GENERATION_STEPS.map((step, index) => {
          const isDone =
            isApiCompleted ||
            BACKEND_STAGE_GROUPS[index].every((stage) =>
              completedStages.includes(stage)
            );
          const isCurrent =
            index === currentStepIdx &&
            !isApiCompleted &&
            runStatus !== "failed";
          return (
            <div
              key={step}
              className={`flex items-center justify-between rounded-2xl border px-4 py-3 text-sm font-bold ${
                isCurrent ? "border-emerald-200 bg-emerald-50 text-emerald-800" : "border-slate-100 bg-white text-slate-400"
              }`}
            >
              <div className="flex items-center gap-3">
                <span className={`w-7 h-7 rounded-full flex items-center justify-center ${isDone ? "bg-emerald-200 text-emerald-700" : "bg-slate-100"}`}>
                  {isDone ? "✓" : index + 1}
                </span>
                <span>{step}</span>
              </div>
              <span className="text-xs">{isCurrent ? "진행 중" : isDone ? "완료" : "대기"}</span>
            </div>
          );
        })}
        {error ? <p className="text-center text-sm font-semibold text-rose-600">{error}</p> : null}
      </div>
    </div>
  );
}

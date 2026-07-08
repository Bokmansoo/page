"use client";

import React from "react";
import type { GenerationProjectStatus, GenerationStatusDashboard } from "@/lib/generationStatus";

function stateLabel(state: GenerationProjectStatus["state"]): string {
  return {
    not_started: "시작 전",
    created: "생성 준비",
    running: "생성 중",
    waiting_for_cost_approval: "비용 승인 대기",
    needs_review: "검수 필요",
    completed: "완료",
    failed: "실패",
  }[state];
}

function stageLabel(stage: string): string {
  return (
    {
      not_started: "시작 전",
      intake: "입력 정리",
      input_router: "입력 분석",
      source_collection: "자료 수집",
      product_understanding: "상품 이해",
      reference_analysis: "참고 자료 분석",
      sales_strategy: "판매 전략",
      page_planning: "상세페이지 기획",
      copywriting: "문구 작성",
      visual_planning: "이미지 기획",
      image_generation: "이미지 생성",
      page_assembly: "상세페이지 조립",
      qa_review: "검수",
      review_editor: "검수 편집",
      export: "출력",
    }[stage] ?? stage
  );
}

function stateClass(state: GenerationProjectStatus["state"]): string {
  if (state === "running" || state === "created") return "border-emerald-200 bg-emerald-50 text-emerald-700";
  if (state === "failed") return "border-rose-200 bg-rose-50 text-rose-700";
  if (state === "needs_review" || state === "waiting_for_cost_approval") return "border-amber-200 bg-amber-50 text-amber-700";
  if (state === "completed") return "border-blue-200 bg-blue-50 text-blue-700";
  return "border-slate-200 bg-slate-50 text-slate-600";
}

function actionHref(project: GenerationProjectStatus): string {
  if (project.state === "completed") {
    return `/workspace/projects/${project.project_id}/result`;
  }
  if (project.state === "needs_review") {
    return `/workspace/projects/${project.project_id}/page-editor?mode=review`;
  }
  if (project.state === "created" || project.state === "running" || project.state === "waiting_for_cost_approval") {
    return `/workspace?runId=${project.active_run?.id || ""}`;
  }
  if (project.state === "failed") {
    return `/workspace/operations?projectId=${project.project_id}`;
  }

  if (project.result_url) return project.result_url;
  if (project.review_url) return project.review_url;
  return `/workspace`;
}

function actionLabel(project: GenerationProjectStatus): string {
  if (project.state === "completed") return "결과 보기";
  if (project.state === "needs_review") return "검수하며 다듬기";
  if (project.state === "failed") return "상태 확인";
  if (project.state === "created" || project.state === "running" || project.state === "waiting_for_cost_approval") {
    return "이어서 진행";
  }
  return "작업 열기";
}

function focusMessage(project: GenerationProjectStatus): string {
  if (project.state === "completed") {
    return "같은 상품으로 이미 완성된 상세페이지가 있어요. 새로 만들기보다 결과를 확인하거나 검수 화면에서 다듬는 편이 안전합니다.";
  }
  if (project.state === "created" || project.state === "running" || project.state === "waiting_for_cost_approval") {
    return "같은 상품의 상세페이지 생성이 이미 진행 중이에요. 중복 생성으로 토큰과 시간이 다시 쓰이지 않도록 기존 작업을 이어서 진행해 주세요.";
  }
  if (project.state === "needs_review") {
    return "상세페이지 초안은 만들어졌고 검수만 남아 있어요. 문구와 이미지 후보를 확인한 뒤 필요한 부분만 다듬으면 됩니다.";
  }
  if (project.state === "failed") {
    return "이 작업은 중간에 실패했습니다. 실패 단계와 오류를 확인한 뒤 다시 시도해 주세요.";
  }
  return "이 상품의 작업 상태를 확인하고 다음 단계로 이어갈 수 있습니다.";
}

export default function GenerationStatusPanel({
  data,
  onRefresh,
  focusProjectId,
}: {
  data: GenerationStatusDashboard;
  onRefresh: () => void;
  focusProjectId?: string | null;
}) {
  const focusedProject = focusProjectId
    ? data.projects.find((project) => project.project_id === focusProjectId)
    : null;

  return (
    <section className="space-y-5">
      {focusedProject ? (
        <div className="rounded-3xl border border-emerald-200 bg-emerald-50 p-6 shadow-sm">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
            <div>
              <p className="text-xs font-black uppercase tracking-[0.25em] text-emerald-700">Current work</p>
              <h2 className="mt-2 text-2xl font-black text-slate-950">이미 진행 중인 상세페이지가 있습니다</h2>
              <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-700">{focusMessage(focusedProject)}</p>
            </div>
            <div className="flex flex-wrap gap-2">
              <a
                href="/workspace/projects"
                className="rounded-xl border border-emerald-200 bg-white px-4 py-3 text-sm font-bold text-emerald-800 hover:bg-emerald-100"
              >
                작업 목록에서 보기
              </a>
              <button
                type="button"
                onClick={onRefresh}
                className="rounded-xl border border-emerald-200 bg-white px-4 py-3 text-sm font-bold text-emerald-800 hover:bg-emerald-100"
              >
                상태 새로고침
              </button>
              <a
                href={actionHref(focusedProject)}
                className="rounded-xl bg-emerald-600 px-5 py-3 text-sm font-black text-white shadow-sm hover:bg-emerald-700"
              >
                {actionLabel(focusedProject)}
              </a>
            </div>
          </div>

          <div className="mt-5 grid gap-3 md:grid-cols-4">
            <StatusMetric label="상품" value={focusedProject.project_name} tone="light" />
            <StatusMetric label="상태" value={stateLabel(focusedProject.state)} tone="light" />
            <StatusMetric label="현재 단계" value={stageLabel(focusedProject.current_stage)} tone="light" />
            <StatusMetric label="진행률" value={`${focusedProject.progress_percent}%`} tone="light" />
          </div>
          {focusedProject.last_error ? (
            <p className="mt-4 rounded-2xl border border-rose-200 bg-white px-4 py-3 text-sm font-semibold text-rose-700">
              {focusedProject.last_error}
            </p>
          ) : null}
        </div>
      ) : null}

      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-extrabold text-slate-950">작업 상태</h2>
          <p className="mt-1 text-sm text-slate-500">
            진행 중인 상세페이지와 완료된 작업을 확인하고, 중복 생성을 막습니다.
          </p>
        </div>
        <button
          type="button"
          onClick={onRefresh}
          className="rounded-xl border border-slate-200 bg-white px-4 py-2 text-sm font-bold text-slate-700 hover:bg-slate-50"
        >
          새로고침
        </button>
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-6">
        <StatusMetric label="생성 중" value={data.summary.running} />
        <StatusMetric label="비용 승인" value={data.summary.waiting_for_cost_approval} />
        <StatusMetric label="검수 필요" value={data.summary.needs_review} />
        <StatusMetric label="완료" value={data.summary.completed} />
        <StatusMetric label="실패" value={data.summary.failed} />
        <StatusMetric label="실사용 비용" value={`$${data.summary.actual_cost.toFixed(4)}`} />
      </div>

      <div className="overflow-hidden rounded-3xl border border-slate-200 bg-white shadow-sm">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[920px] text-left text-sm">
            <thead className="border-b border-slate-200 bg-slate-50 text-xs font-black uppercase tracking-wider text-slate-500">
              <tr>
                <th className="p-4">상품</th>
                <th className="p-4">상태</th>
                <th className="p-4">단계</th>
                <th className="p-4">진행률</th>
                <th className="p-4">비용/토큰</th>
                <th className="p-4">다음 행동</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 text-slate-700">
              {data.projects.map((project) => {
                const isFocused = project.project_id === focusProjectId;
                return (
                  <tr key={project.project_id} className={isFocused ? "bg-emerald-50/80" : "hover:bg-slate-50"}>
                    <td className="p-4 font-black text-slate-950">{project.project_name}</td>
                    <td className="p-4">
                      <span className={`rounded-full border px-3 py-1 text-xs font-black ${stateClass(project.state)}`}>
                        {stateLabel(project.state)}
                      </span>
                    </td>
                    <td className="p-4 text-sm text-slate-600">{stageLabel(project.current_stage)}</td>
                    <td className="p-4">
                      <div className="h-2 w-36 overflow-hidden rounded-full bg-slate-100">
                        <div className="h-full bg-emerald-500" style={{ width: `${project.progress_percent}%` }} />
                      </div>
                      <div className="mt-1 text-xs text-slate-500">{project.progress_percent}%</div>
                    </td>
                    <td className="p-4 text-xs leading-5 text-slate-500">
                      <div>${project.cost.actual.toFixed(4)} / 예상 ${project.cost.estimated.toFixed(4)}</div>
                      <div>in {project.cost.token_input} / out {project.cost.token_output}</div>
                    </td>
                    <td className="p-4">
                      <a
                        className="inline-flex rounded-xl bg-slate-950 px-4 py-2 text-xs font-black text-white hover:bg-slate-800"
                        href={actionHref(project)}
                      >
                        {actionLabel(project)}
                      </a>
                      {project.last_error ? (
                        <p className="mt-2 max-w-xs truncate text-xs font-semibold text-rose-600">{project.last_error}</p>
                      ) : null}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );
}

function StatusMetric({
  label,
  value,
  tone = "default",
}: {
  label: string;
  value: React.ReactNode;
  tone?: "default" | "light";
}) {
  const className =
    tone === "light"
      ? "rounded-2xl border border-emerald-100 bg-white p-4"
      : "rounded-2xl border border-slate-200 bg-white p-4 shadow-sm";

  return (
    <div className={className}>
      <p className="text-[11px] font-black uppercase tracking-wider text-slate-500">{label}</p>
      <p className="mt-2 truncate text-xl font-black text-slate-950">{value}</p>
    </div>
  );
}

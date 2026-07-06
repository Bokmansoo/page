"use client";

import React from "react";
import type { GenerationStatusDashboard, GenerationProjectStatus } from "@/lib/generationStatus";

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

function stateClass(state: GenerationProjectStatus["state"]): string {
  if (state === "running") return "border-emerald-200 bg-emerald-50 text-emerald-700";
  if (state === "failed") return "border-rose-200 bg-rose-50 text-rose-700";
  if (state === "needs_review" || state === "waiting_for_cost_approval") return "border-amber-200 bg-amber-50 text-amber-700";
  if (state === "completed") return "border-blue-200 bg-blue-50 text-blue-700";
  return "border-slate-200 bg-slate-50 text-slate-600";
}

export default function GenerationStatusPanel({
  data,
  onRefresh,
}: {
  data: GenerationStatusDashboard;
  onRefresh: () => void;
}) {
  return (
    <section className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-extrabold text-white">현재 생성 작업 상태</h2>
          <p className="mt-1 text-xs text-slate-400">
            진행 중인 작업과 비용을 확인해 중복 생성을 막습니다.
          </p>
        </div>
        <button
          type="button"
          onClick={onRefresh}
          className="rounded-xl border border-slate-800 bg-slate-900 px-4 py-2 text-xs font-bold text-slate-200 hover:border-slate-700"
        >
          상태 새로고침
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

      <div className="overflow-hidden rounded-2xl border border-slate-900 bg-slate-950/30">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-slate-900 bg-slate-900/50 text-xs uppercase tracking-wider text-slate-400">
            <tr>
              <th className="p-4">상품</th>
              <th className="p-4">상태</th>
              <th className="p-4">단계</th>
              <th className="p-4">진행률</th>
              <th className="p-4">비용/토큰</th>
              <th className="p-4">다음 행동</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-900 text-slate-300">
            {data.projects.map((project) => (
              <tr key={project.project_id} className="hover:bg-slate-900/30">
                <td className="p-4 font-bold text-white">{project.project_name}</td>
                <td className="p-4">
                  <span className={`rounded-full border px-2 py-1 text-xs font-bold ${stateClass(project.state)}`}>
                    {stateLabel(project.state)}
                  </span>
                </td>
                <td className="p-4 text-xs text-slate-400">{project.current_stage}</td>
                <td className="p-4">
                  <div className="h-2 w-32 overflow-hidden rounded-full bg-slate-900">
                    <div className="h-full bg-emerald-500" style={{ width: `${project.progress_percent}%` }} />
                  </div>
                  <div className="mt-1 text-[10px] text-slate-500">{project.progress_percent}%</div>
                </td>
                <td className="p-4 text-xs">
                  <div>${project.cost.actual.toFixed(4)} / 예상 ${project.cost.estimated.toFixed(4)}</div>
                  <div className="text-slate-500">
                    in {project.cost.token_input} / out {project.cost.token_output}
                  </div>
                </td>
                <td className="p-4 text-xs">
                  {project.result_url ? (
                    <a className="font-bold text-emerald-400 hover:text-emerald-300" href={project.result_url}>
                      결과 보기
                    </a>
                  ) : project.review_url ? (
                    <a className="font-bold text-amber-400 hover:text-amber-300" href={project.review_url}>
                      검수하기
                    </a>
                  ) : (
                    <span className="text-slate-500">{project.recommended_action}</span>
                  )}
                  {project.last_error ? (
                    <p className="mt-1 max-w-xs truncate text-rose-400">{project.last_error}</p>
                  ) : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function StatusMetric({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="rounded-2xl border border-slate-900 bg-slate-950/40 p-4">
      <p className="text-[11px] font-bold uppercase tracking-wider text-slate-500">{label}</p>
      <p className="mt-2 text-2xl font-black text-white">{value}</p>
    </div>
  );
}

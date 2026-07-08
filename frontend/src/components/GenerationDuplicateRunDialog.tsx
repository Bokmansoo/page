"use client";

import React from "react";
import { useRouter } from "next/navigation";

interface DuplicateRunDetail {
  code: string;
  message: string;
  project_id: string;
  run_id?: string | null;
  state: string;
  status_url: string;
  result_url?: string | null;
  review_url?: string | null;
}

export default function GenerationDuplicateRunDialog({
  detail,
  onClose,
  onForceNew,
}: {
  detail: DuplicateRunDetail;
  onClose: () => void;
  onForceNew?: () => void;
}) {
  const router = useRouter();

  const handleContinue = () => {
    onClose();
    const state = detail.state;
    if (state === "created" || state === "running" || state === "waiting_for_cost_approval") {
      router.push(`/workspace?runId=${detail.run_id || ""}`);
    } else if (state === "completed") {
      router.push(detail.result_url || `/workspace/projects/${detail.project_id}/result`);
    } else if (state === "needs_review") {
      router.push(detail.review_url || `/workspace/projects/${detail.project_id}/page-editor?mode=review`);
    } else {
      router.push(`/workspace`);
    }
  };

  return (
    <div role="dialog" aria-modal="true" aria-label="이미 진행 중인 작업" className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/50 p-4">
      <div className="w-full max-w-lg rounded-2xl bg-white p-6 shadow-2xl">
        <p className="text-sm font-bold text-amber-700">중복 생성을 막았습니다</p>
        <h2 className="mt-2 text-xl font-black text-slate-950">이미 작업 중인 상세페이지가 있어요</h2>
        <p className="mt-3 text-sm leading-6 text-slate-600">
          {detail.message} 같은 상품을 다시 생성하면 토큰과 이미지 생성 비용이 중복으로 들어갈 수 있습니다.
        </p>
        <div className="mt-5 rounded-xl bg-slate-50 p-4 text-xs text-slate-600">
          <div>상태: {detail.state}</div>
          {detail.run_id ? <div>Run ID: {detail.run_id}</div> : null}
        </div>
        <div className="mt-6 flex flex-col gap-2">
          <button
            type="button"
            onClick={handleContinue}
            className="w-full rounded-xl bg-emerald-600 px-4 py-2.5 text-sm font-bold text-white hover:bg-emerald-700"
          >
            기존 작업 이어가기
          </button>
          <button
            type="button"
            onClick={() => {
              onForceNew?.();
              onClose();
            }}
            className="w-full rounded-xl border border-amber-200 bg-amber-50 px-4 py-2.5 text-sm font-bold text-amber-800 hover:bg-amber-100"
          >
            그래도 새 작업으로 다시 만들기
          </button>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => {
                onClose();
                router.push("/workspace/projects");
              }}
              className="flex-1 rounded-xl border border-slate-200 bg-white px-4 py-2 text-sm font-bold text-slate-700 hover:bg-slate-50"
            >
              작업 목록 확인
            </button>
            <button
              type="button"
              onClick={onClose}
              className="rounded-xl border border-slate-200 bg-white px-4 py-2 text-sm font-bold text-slate-500 hover:bg-slate-50"
            >
              취소
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

export type { DuplicateRunDetail };

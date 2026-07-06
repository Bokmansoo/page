"use client";

import React from "react";

interface CopyRewriteComparisonProps {
  originalTitle: string;
  originalBody: string;
  proposedTitle: string;
  proposedBody: string;
  changeSummary: string;
  groundingWarnings?: string[];
  onApply: () => void;
  onCancel: () => void;
}

export default function CopyRewriteComparison({
  originalTitle,
  originalBody,
  proposedTitle,
  proposedBody,
  changeSummary,
  groundingWarnings = [],
  onApply,
  onCancel,
}: CopyRewriteComparisonProps) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4"
      role="dialog"
      aria-label="AI 수정안 비교"
      onClick={(e) => {
        if (e.target === e.currentTarget) onCancel();
      }}
    >
      <div className="w-full max-w-3xl rounded-3xl bg-white p-6 shadow-2xl">
        <h2 className="text-lg font-extrabold text-slate-900">AI 수정안 비교</h2>
        <p className="mt-1 text-xs text-slate-500">{changeSummary}</p>

        {groundingWarnings.length > 0 ? (
          <div className="mt-3 rounded-xl border border-amber-200 bg-amber-50 p-3">
            <p className="text-xs font-bold text-amber-700">주의 사항</p>
            {groundingWarnings.map((w, i) => (
              <p key={i} className="mt-1 text-xs text-amber-600">
                {w}
              </p>
            ))}
          </div>
        ) : null}

        <div className="mt-5 grid grid-cols-2 gap-4">
          <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
            <p className="mb-2 text-xs font-bold text-slate-500">수정 전</p>
            <p className="text-sm font-extrabold text-slate-900">{originalTitle}</p>
            <p className="mt-2 text-xs leading-relaxed text-slate-600">{originalBody}</p>
          </div>
          <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-4">
            <p className="mb-2 text-xs font-bold text-emerald-700">수정 후</p>
            <p className="text-sm font-extrabold text-emerald-900">{proposedTitle}</p>
            <p className="mt-2 text-xs leading-relaxed text-emerald-800">{proposedBody}</p>
          </div>
        </div>

        <div className="mt-6 flex justify-end gap-3">
          <button
            type="button"
            onClick={onCancel}
            className="rounded-xl border border-slate-200 bg-white px-5 py-2 text-sm font-bold text-slate-600 hover:bg-slate-50"
          >
            취소
          </button>
          <button
            type="button"
            onClick={onApply}
            className="rounded-xl bg-emerald-600 px-5 py-2 text-sm font-bold text-white hover:bg-emerald-700"
          >
            이 수정안 적용
          </button>
        </div>
      </div>
    </div>
  );
}

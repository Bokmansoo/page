"use client";

import React from "react";

interface AiCopyRewriteCompareModalProps {
  isOpen: boolean;
  originalTitle: string;
  originalBody: string;
  proposedTitle: string;
  proposedBody: string;
  changeSummary: string;
  groundingWarnings?: string[];
  onApply: () => void;
  onRetry: () => void;
  onCancel: () => void;
}

export default function AiCopyRewriteCompareModal({
  isOpen,
  originalTitle,
  originalBody,
  proposedTitle,
  proposedBody,
  changeSummary,
  groundingWarnings = [],
  onApply,
  onRetry,
  onCancel,
}: AiCopyRewriteCompareModalProps) {
  if (!isOpen) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/60 p-4 backdrop-blur-sm"
      role="dialog"
      aria-label="AI 수정안 비교"
      onClick={(e) => {
        if (e.target === e.currentTarget) onCancel();
      }}
    >
      <div className="w-full max-w-3xl rounded-3xl bg-white p-6 shadow-2xl border border-slate-100 animate-in fade-in zoom-in duration-200">
        <div className="flex items-center justify-between border-b border-slate-100 pb-4">
          <div>
            <h2 className="text-lg font-extrabold text-slate-900">AI 수정안 비교</h2>
            <p className="mt-1 text-xs text-slate-500">{changeSummary}</p>
          </div>
          <button
            type="button"
            onClick={onCancel}
            className="text-slate-400 hover:text-slate-600 transition-colors"
          >
            <svg className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {groundingWarnings.length > 0 && (
          <div className="mt-4 rounded-2xl border border-amber-100 bg-amber-50/50 p-4">
            <p className="text-xs font-bold text-amber-800 flex items-center gap-1.5">
              <span>⚠️ 주의 사항</span>
            </p>
            <div className="mt-1.5 space-y-1">
              {groundingWarnings.map((w, i) => (
                <p key={i} className="text-xs text-amber-700 leading-relaxed">
                  • {w}
                </p>
              ))}
            </div>
          </div>
        )}

        <div className="mt-5 grid grid-cols-1 md:grid-cols-2 gap-4">
          <div className="rounded-2xl border border-slate-200 bg-slate-50/70 p-5">
            <p className="mb-3 text-[10px] font-extrabold uppercase tracking-wider text-slate-400">수정 전</p>
            <p className="text-base font-extrabold text-slate-900 leading-snug">{originalTitle}</p>
            <p className="mt-3 text-xs leading-relaxed text-slate-600 whitespace-pre-wrap">{originalBody}</p>
          </div>
          
          <div className="rounded-2xl border border-emerald-200 bg-emerald-50/30 p-5">
            <p className="mb-3 text-[10px] font-extrabold uppercase tracking-wider text-emerald-600">수정 후</p>
            <p className="text-base font-extrabold text-emerald-950 leading-snug">{proposedTitle}</p>
            <p className="mt-3 text-xs leading-relaxed text-emerald-800 whitespace-pre-wrap">{proposedBody}</p>
          </div>
        </div>

        <div className="mt-6 flex flex-wrap items-center justify-end gap-3 border-t border-slate-100 pt-4">
          <button
            type="button"
            onClick={onCancel}
            className="rounded-xl border border-slate-200 bg-white px-5 py-2.5 text-xs font-bold text-slate-600 transition-colors hover:bg-slate-50"
          >
            취소
          </button>
          
          <button
            type="button"
            onClick={onRetry}
            className="rounded-xl border border-emerald-200 bg-emerald-50 px-5 py-2.5 text-xs font-bold text-emerald-700 transition-colors hover:bg-emerald-100"
          >
            다시 생성
          </button>
          
          <button
            type="button"
            onClick={onApply}
            className="rounded-xl bg-emerald-600 px-5 py-2.5 text-xs font-bold text-white transition-colors hover:bg-emerald-700 shadow-md shadow-emerald-600/10"
          >
            이 수정안 적용
          </button>
        </div>
      </div>
    </div>
  );
}

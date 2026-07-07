"use client";

import React from "react";

interface PlanningModeSelectorProps {
  mode: "quality" | "quick";
  onChange: (mode: "quality" | "quick") => void;
}

export default function PlanningModeSelector({ mode, onChange }: PlanningModeSelectorProps) {
  return (
    <div className="space-y-3">
      <label className="block text-sm font-semibold text-slate-700">기획 모드 선택</label>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <button
          type="button"
          onClick={() => onChange("quality")}
          className={`flex flex-col rounded-2xl border-2 p-5 text-left transition-all ${
            mode === "quality"
              ? "border-emerald-600 bg-emerald-50/50 shadow-md shadow-emerald-100"
              : "border-slate-100 bg-white hover:border-slate-200 hover:bg-slate-50/50"
          }`}
        >
          <div className="mb-2 flex w-full items-center justify-between">
            <span className="text-sm font-bold text-slate-900">품질 모드 추천</span>
            <span
              className={`rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider ${
                mode === "quality" ? "bg-emerald-600 text-white" : "bg-slate-100 text-slate-500"
              }`}
            >
              Recommend
            </span>
          </div>
          <p className="text-xs leading-relaxed text-slate-500">
            AI가 먼저 기획 초안을 만들고, 판매자가 섹션 구조와 문구를 검수한 뒤 상세페이지를 조립합니다.
          </p>
        </button>

        <button
          type="button"
          onClick={() => onChange("quick")}
          className={`flex flex-col rounded-2xl border-2 p-5 text-left transition-all ${
            mode === "quick"
              ? "border-emerald-600 bg-emerald-50/50 shadow-md shadow-emerald-100"
              : "border-slate-100 bg-white hover:border-slate-200 hover:bg-slate-50/50"
          }`}
        >
          <div className="mb-2 flex w-full items-center justify-between">
            <span className="text-sm font-bold text-slate-900">빠른 모드</span>
            <span
              className={`rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider ${
                mode === "quick" ? "bg-emerald-600 text-white" : "bg-slate-100 text-slate-500"
              }`}
            >
              Fast
            </span>
          </div>
          <p className="text-xs leading-relaxed text-slate-500">
            기획 검수 단계를 건너뛰고, 입력한 상품 정보를 바탕으로 바로 상세페이지 생성을 진행합니다.
          </p>
        </button>
      </div>
    </div>
  );
}

"use client";

import React from "react";

export interface OutlineSection {
  id: string;
  section_type: string;
  title: string;
  body_copy: string;
  image_asset_id: string | null;
  sort_order: number;
  is_visible: boolean;
  warnings?: string[];
}

interface GeneratedPageOutlineProps {
  sections: OutlineSection[];
  selectedSectionId: string | null;
  onSelectSection: (id: string) => void;
  isFinalVersion?: boolean;
}

export default function GeneratedPageOutline({
  sections,
  selectedSectionId,
  onSelectSection,
  isFinalVersion = false,
}: GeneratedPageOutlineProps) {
  const visibleSections = sections.filter((section) => section.is_visible);

  return (
    <aside className="bg-white border border-slate-200 rounded-3xl p-5 shadow-sm space-y-5">
      <div className="space-y-1">
        <p className="text-xs font-bold text-emerald-700">검수 흐름</p>
        <h2 className="text-lg font-extrabold text-slate-900">상세페이지 구성</h2>
        <p className="text-xs text-slate-500 leading-relaxed">
          문구와 이미지 배치를 확인하고 수정할 섹션을 선택하세요.
        </p>
      </div>

      <div className="rounded-2xl bg-emerald-50 border border-emerald-100 p-3 text-xs text-emerald-800 flex items-center justify-between">
        <span className="font-bold">최종본 상태</span>
        <span className="font-extrabold">{isFinalVersion ? "지정됨" : "검수 중"}</span>
      </div>

      <div className="space-y-2">
        {visibleSections.map((section, index) => {
          const warningCount = section.warnings?.length ?? 0;
          const isSelected = selectedSectionId === section.id;

          return (
            <button
              key={section.id}
              type="button"
              onClick={() => onSelectSection(section.id)}
              className={`w-full text-left rounded-2xl border p-4 transition-all ${
                isSelected
                  ? "border-emerald-500 bg-emerald-50 shadow-sm"
                  : "border-slate-200 bg-white hover:border-emerald-200 hover:bg-slate-50"
              }`}
            >
              <div className="flex items-center justify-between gap-3">
                <span className="text-[11px] font-extrabold text-emerald-700 tracking-wide">
                  {String(index + 1).padStart(2, "0")} {section.section_type.replace(/_/g, " ")}
                </span>
                {warningCount > 0 ? (
                  <span className="rounded-full bg-amber-50 px-2 py-0.5 text-[10px] font-bold text-amber-700 border border-amber-100">
                    확인 {warningCount}
                  </span>
                ) : null}
              </div>
              <p className="mt-2 text-sm font-extrabold text-slate-900 line-clamp-2">
                {section.title || "제목 없음"}
              </p>
              <p className="mt-1 text-xs text-slate-500 line-clamp-2 leading-relaxed">
                {section.body_copy || "본문 문구가 없습니다."}
              </p>
            </button>
          );
        })}
      </div>
    </aside>
  );
}

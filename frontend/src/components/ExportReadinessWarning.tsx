"use client";

import React from "react";
import { useRouter } from "next/navigation";

interface Blocker {
  section_id: string;
  code: string;
  message: string;
}

interface ExportReadinessWarningProps {
  blockers: Blocker[];
  projectId: string;
}

const BLOCKER_MESSAGES: Record<string, string> = {
  visual_image_asset_required: "이미지 에셋이 필요한 섹션이 있습니다",
  visual_invalid_visual_kind: "올바르지 않은 시각 유형이 있습니다",
  visual_invalid_html_layout: "올바르지 않은 HTML 레이아웃이 있습니다",
  visual_html_cards_required: "카드형 섹션에 내용이 비어 있습니다",
  visual_spec_rows_required: "스펙 테이블에 항목이 비어 있습니다",
  asset_not_eligible: "일부 이미지가 내보내기 조건을 충족하지 않습니다",
  internal_edit_marker: "AI 수정 표식이 남아 있는 섹션이 있습니다",
};

function blockerLabel(code: string): string {
  return BLOCKER_MESSAGES[code] || code.replace(/_/g, " ");
}

export default function ExportReadinessWarning({
  blockers,
  projectId,
}: ExportReadinessWarningProps) {
  const router = useRouter();

  if (blockers.length === 0) return null;

  return (
    <div className="mx-auto mb-4 w-full max-w-[760px] rounded-xl border border-amber-200 bg-amber-50 p-4">
      <p className="text-sm font-extrabold text-amber-800">
        다운로드 전 확인이 필요합니다
      </p>
      <ul className="mt-2 space-y-1">
        {blockers.map((blocker, idx) => (
          <li key={idx} className="flex items-start gap-2 text-xs text-amber-700">
            <span className="mt-0.5 shrink-0">•</span>
            <span>{blockerLabel(blocker.code)}</span>
          </li>
        ))}
      </ul>
      <button
        type="button"
        onClick={() =>
          router.push(`/workspace/projects/${projectId}/page-editor?mode=review`)
        }
        className="mt-3 rounded-lg bg-amber-600 px-4 py-2 text-xs font-bold text-white hover:bg-amber-700"
      >
        검수하며 다듬기에서 해결하기
      </button>
    </div>
  );
}

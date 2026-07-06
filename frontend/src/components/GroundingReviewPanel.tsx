'use client';

import React from 'react';

export interface GroundingWarning {
  risk_type: string;
  phrase: string;
  reason: string;
  suggestion: string;
}

export interface SectionReview {
  id: string;
  section_type: string;
  title: string;
  body_copy: string;
  grounding_warnings?: GroundingWarning[];
  matched_facts?: string[];
}

export interface GroundingSummary {
  warning_count: number;
  grounded_section_count: number;
  used_fact_count: number;
}

interface GroundingReviewPanelProps {
  summary: GroundingSummary | null;
  sections: SectionReview[];
  selectedSectionId: string | null;
  onSelectSection: (id: string) => void;
}

export default function GroundingReviewPanel({
  summary,
  sections,
  selectedSectionId,
  onSelectSection,
}: GroundingReviewPanelProps) {
  const warningCount = summary?.warning_count ?? 0;
  const groundedCount = summary?.grounded_section_count ?? 0;
  const usedFactCount = summary?.used_fact_count ?? 0;

  return (
    <div className="flex flex-col h-full text-slate-200">
      {/* 1. 상단 카드 요약 통계 */}
      <div className="grid grid-cols-3 gap-2.5 mb-6">
        <div className={`p-3 rounded-2xl border transition-all duration-300 ${
          warningCount > 0 
            ? 'bg-rose-950/20 border-rose-900/50 text-rose-300 hover:bg-rose-950/30' 
            : 'bg-emerald-950/20 border-emerald-900/50 text-emerald-300 hover:bg-emerald-950/30'
        }`}>
          <div className="text-[10px] uppercase font-bold tracking-wider opacity-75">주의 필요</div>
          <div className="text-xl font-extrabold mt-1">{warningCount}건</div>
        </div>

        <div className="p-3 bg-blue-950/20 border border-blue-900/50 text-blue-300 rounded-2xl hover:bg-blue-950/30 transition-all duration-300">
          <div className="text-[10px] uppercase font-bold tracking-wider opacity-75">근거 연결</div>
          <div className="text-xl font-extrabold mt-1">{groundedCount}개 섹션</div>
        </div>

        <div className="p-3 bg-indigo-950/20 border border-indigo-900/50 text-indigo-300 rounded-2xl hover:bg-indigo-950/30 transition-all duration-300">
          <div className="text-[10px] uppercase font-bold tracking-wider opacity-75">사실 카드 사용</div>
          <div className="text-xl font-extrabold mt-1">{usedFactCount}개</div>
        </div>
      </div>

      {/* 2. 섹션별 검수 상세 내용 */}
      <h3 className="text-xs font-bold text-slate-500 uppercase tracking-widest mb-3">섹션별 검수 상세</h3>
      <div className="flex-1 space-y-4 overflow-y-auto pr-1">
        {sections.map((sec) => {
          const hasWarnings = (sec.grounding_warnings?.length ?? 0) > 0;
          const matchedFacts = sec.matched_facts ?? [];
          const isSelected = sec.id === selectedSectionId;

          return (
            <div
              key={sec.id}
              onClick={() => onSelectSection(sec.id)}
              className={`p-4 rounded-2xl border transition-all duration-200 cursor-pointer ${
                isSelected
                  ? 'bg-slate-900 border-blue-500 shadow-lg shadow-blue-500/5'
                  : 'bg-slate-900/40 border-slate-800 hover:border-slate-700'
              }`}
            >
              {/* 섹션 머리말 */}
              <div className="flex items-center justify-between mb-2.5">
                <span className="text-[10px] font-mono text-slate-400 bg-slate-800 px-2 py-0.5 rounded uppercase">
                  {sec.section_type}
                </span>
                {hasWarnings && (
                  <span className="text-[10px] font-semibold text-rose-400 bg-rose-950/50 border border-rose-900/40 px-2 py-0.5 rounded-full">
                    검토 필요
                  </span>
                )}
              </div>

              <h4 className="text-sm font-semibold text-slate-200 mb-2 truncate">
                {sec.title || '(제목 없는 섹션)'}
              </h4>

              {/* 연결된 사실 카드 */}
              {matchedFacts.length > 0 ? (
                <div className="mb-3">
                  <div className="text-[10px] text-slate-400 font-bold mb-1">연결된 사실 카드 ({matchedFacts.length})</div>
                  <div className="flex flex-wrap gap-1">
                    {matchedFacts.map((fact, idx) => (
                      <span
                        key={idx}
                        className="text-[10px] bg-blue-950/40 border border-blue-900/30 text-blue-300 px-2 py-0.5 rounded"
                      >
                        ✓ {fact}
                      </span>
                    ))}
                  </div>
                </div>
              ) : (
                <div className="text-[10px] text-slate-500 italic mb-3">연결된 사실 카드가 없습니다.</div>
              )}

              {/* 위험 경고 */}
              {hasWarnings && (
                <div className="space-y-2 pt-2 border-t border-slate-800/80">
                  {sec.grounding_warnings?.map((warning, idx) => (
                    <div key={idx} className="bg-rose-950/10 border border-rose-900/30 rounded-xl p-3 text-xs">
                      <div className="flex items-center space-x-1.5 text-rose-400 font-bold mb-1">
                        <span>⚠️</span>
                        <span>미검증 위험 문구: &quot;{warning.phrase}&quot;</span>
                      </div>
                      <div className="text-slate-300 leading-relaxed mb-1.5">
                        <span className="font-semibold text-slate-400">사유:</span> {warning.reason}
                      </div>
                      <div className="text-emerald-400 leading-relaxed bg-emerald-950/10 border border-emerald-900/20 px-2.5 py-1.5 rounded-lg">
                        <span className="font-bold">💡 수정 제안:</span> {warning.suggestion}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

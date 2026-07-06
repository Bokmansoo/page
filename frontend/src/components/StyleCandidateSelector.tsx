'use client';

import React, { useState } from 'react';

export interface StyleCandidate {
  key: string;
  name: string;
  is_ai_recommended: boolean;
  channel_fit: string;
  sales_strategy: string;
  design_direction: string;
  preview_summary: string;
  reason: string;
}

interface StyleCandidateSelectorProps {
  candidates: StyleCandidate[];
  selectedKey: string | null;
  onSelect: (key: string) => void;
  onRegenerate: (feedbackOption: string) => void;
  generating: boolean;
  onGeneratePage: () => void;
  confirmedFactCount?: number;
  categoryConfirmed?: boolean;
}

export default function StyleCandidateSelector({
  candidates,
  selectedKey,
  onSelect,
  onRegenerate,
  generating,
  onGeneratePage,
  confirmedFactCount = 0,
  categoryConfirmed = true,
}: StyleCandidateSelectorProps) {
  const [showRegenOptions, setShowRegenOptions] = useState(false);
  const feedbackOptions = [
    '더 감성적으로',
    '더 스펙 중심으로',
    '더 쿠팡스럽게',
    '더 스마트스토어스럽게',
    '더 짧고 강하게',
  ];

  const getChannelFitLabel = (fit: string) => {
    switch (fit) {
      case 'coupang':
        return '쿠팡 적합';
      case 'smartstore':
        return '스마트스토어 적합';
      default:
        return '둘 다 가능';
    }
  };

  const getChannelFitStyle = (fit: string) => {
    switch (fit) {
      case 'coupang':
        return 'bg-orange-950/60 text-orange-400 border-orange-900/60';
      case 'smartstore':
        return 'bg-emerald-950/60 text-emerald-400 border-emerald-900/60';
      default:
        return 'bg-blue-950/60 text-blue-400 border-blue-900/60';
    }
  };

  const isButtonDisabled = generating || !selectedKey || confirmedFactCount < 3 || !categoryConfirmed;

  return (
    <div className="w-full max-w-5xl mx-auto space-y-8 py-4 px-4 text-slate-100">
      <div className="text-center space-y-3">
        <div className="inline-flex items-center space-x-2 bg-indigo-950/60 text-indigo-400 border border-indigo-900/60 px-4 py-1.5 rounded-full text-xs font-semibold tracking-wide">
          <span>✨ Step 2: 스타일 전략 선택</span>
        </div>
        <h2 className="text-3xl font-extrabold tracking-tight bg-gradient-to-r from-blue-400 via-indigo-400 to-purple-400 bg-clip-text text-transparent">
          어떤 판매 전략으로 상세페이지를 만들까요?
        </h2>
        <p className="text-slate-400 text-sm max-w-2xl mx-auto leading-relaxed">
          상품에 특화된 7단 설득 구조와 최적화 템플릿을 조합한 3개의 스타일 후보입니다. 브랜드 톤앤매너에 어울리는 스타일을 선택해 주세요.
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6 pt-4">
        {candidates.map((c) => {
          const isSelected = selectedKey === c.key;
          return (
            <div
              key={c.key}
              onClick={() => onSelect(c.key)}
              className={`group flex flex-col bg-slate-900/40 border rounded-2xl p-6 transition-all duration-300 cursor-pointer relative hover:translate-y-[-4px] hover:shadow-xl ${
                isSelected
                  ? 'border-indigo-500 ring-2 ring-indigo-500/50 bg-slate-900/80 shadow-indigo-500/10'
                  : 'border-slate-800 hover:border-slate-700 bg-slate-900/30'
              }`}
            >
              {c.is_ai_recommended && (
                <span className="absolute top-[-12px] left-6 px-3 py-1 bg-gradient-to-r from-indigo-500 to-purple-600 text-white rounded-full text-[10px] font-bold tracking-wider uppercase shadow-md shadow-indigo-500/20">
                  AI 추천
                </span>
              )}

              <div className="flex justify-between items-center mb-4">
                <h3 className="text-lg font-bold text-slate-100 group-hover:text-white transition-colors">
                  {c.name}
                </h3>
                <span
                  className={`px-2 py-0.5 border rounded-md text-[10px] font-semibold ${getChannelFitStyle(
                    c.channel_fit
                  )}`}
                >
                  {getChannelFitLabel(c.channel_fit)}
                </span>
              </div>

              <div className="space-y-4 flex-1">
                <div>
                  <span className="text-[10px] font-bold text-slate-500 uppercase tracking-widest block mb-1">
                    판매 소구 전략
                  </span>
                  <p className="text-slate-300 text-xs leading-relaxed">
                    {c.sales_strategy}
                  </p>
                </div>

                <div>
                  <span className="text-[10px] font-bold text-slate-500 uppercase tracking-widest block mb-1">
                    디자인 구성 방향
                  </span>
                  <p className="text-slate-300 text-xs leading-relaxed">
                    {c.design_direction}
                  </p>
                </div>

                <div>
                  <span className="text-[10px] font-bold text-slate-500 uppercase tracking-widest block mb-1">
                    미리보기 요약
                  </span>
                  <p className="text-slate-300 text-xs leading-relaxed italic bg-slate-950/40 p-2.5 rounded-lg border border-slate-900/60">
                    &quot;{c.preview_summary}&quot;
                  </p>
                </div>

                <div>
                  <span className="text-[10px] font-bold text-slate-500 uppercase tracking-widest block mb-1">
                    추천 이유
                  </span>
                  <p className="text-slate-400 text-[11px] leading-relaxed">
                    {c.reason}
                  </p>
                </div>
              </div>

              <div className="mt-6 pt-4 border-t border-slate-800/80">
                <div
                  className={`w-full py-2.5 rounded-xl text-center text-xs font-semibold tracking-wide transition-all duration-200 ${
                    isSelected
                      ? 'bg-indigo-600 text-white font-bold shadow-lg shadow-indigo-600/15'
                      : 'bg-slate-800 text-slate-400 hover:bg-slate-700 hover:text-slate-200'
                  }`}
                >
                  {isSelected ? '선택 완료 ✓' : '이 스타일 선택'}
                </div>
              </div>
            </div>
          );
        })}
      </div>

      <div className="flex flex-col items-center justify-center space-y-4 pt-6 max-w-md mx-auto">
        <button
          onClick={onGeneratePage}
          disabled={isButtonDisabled}
          className="w-full py-4 rounded-xl bg-gradient-to-r from-blue-500 via-indigo-500 to-purple-600 hover:from-blue-600 hover:to-purple-700 text-white font-bold transition-all duration-300 shadow-lg shadow-indigo-500/20 disabled:opacity-30 disabled:pointer-events-none disabled:shadow-none tracking-wide text-sm flex items-center justify-center space-x-2"
        >
          {generating ? (
            <>
              <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin"></div>
              <span>AI 상세페이지 초안 작성 중...</span>
            </>
          ) : (
            <span>선택한 스타일로 초안 만들기 ✨</span>
          )}
        </button>

        {!generating && selectedKey && (confirmedFactCount < 3 || !categoryConfirmed) && (
          <div className="text-center text-xs text-amber-400 bg-amber-950/20 border border-amber-900/40 p-2.5 rounded-xl w-full leading-relaxed animate-fadeIn">
            <p className="font-bold">⚠️ 생성이 일시 비활성화되었습니다:</p>
            <ul className="list-inside text-[11px] text-amber-300/80 mt-1 space-y-0.5">
              {confirmedFactCount < 3 && (
                <li>확인된 사실 카드 3개 이상 필요 (현재 확정: {confirmedFactCount}개)</li>
              )}
              {!categoryConfirmed && (
                <li>카테고리 확정 필요</li>
              )}
            </ul>
          </div>
        )}

        <div className="relative w-full text-center">
          <button
            onClick={() => setShowRegenOptions(!showRegenOptions)}
            className="text-xs text-slate-500 hover:text-indigo-400 font-semibold underline underline-offset-4 transition-colors"
          >
            마음에 드는 후보가 없으신가요? (다른 스타일 다시 추천)
          </button>

          {showRegenOptions && (
            <div className="absolute top-8 left-1/2 -translate-x-1/2 w-64 bg-slate-900 border border-slate-800 rounded-xl p-2.5 shadow-2xl z-30 space-y-1">
              <span className="text-[9px] font-bold text-slate-500 uppercase tracking-widest block px-2 pb-1.5 border-b border-slate-800 text-left">
                재추천 피드백 방향 선택
              </span>
              {feedbackOptions.map((opt) => (
                <button
                  key={opt}
                  onClick={() => {
                    onRegenerate(opt);
                    setShowRegenOptions(false);
                  }}
                  className="w-full text-left px-3 py-2 text-xs hover:bg-slate-800 rounded-lg text-slate-300 hover:text-white transition-colors"
                >
                  {opt}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

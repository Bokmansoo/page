import React from 'react';
import { WorkflowStepKey } from './WorkflowStepHeader';

const NEXT_ACTION_MESSAGES: Record<WorkflowStepKey, string> = {
  raw_input: "상품명, 상품 링크, 이미지 또는 텍스트 정보를 입력해 주세요.",
  facts_verification: "상세페이지에 사용할 사실 카드를 확인해 주세요.",
  style_selection: "AI가 추천한 스타일 후보 중 하나를 선택해 주세요.",
  page_editor: "상세페이지 문구와 섹션 순서를 확인해 주세요.",
  export: "최종본을 지정하고 긴 이미지 또는 섹션별 ZIP으로 저장해 주세요.",
};

interface NextActionPanelProps {
  currentStep: WorkflowStepKey;
  confirmedFactCount?: number;
  categoryConfirmed?: boolean;
  serverError?: boolean;
}

export default function NextActionPanel({
  currentStep,
  confirmedFactCount = 0,
  categoryConfirmed = true,
  serverError = false,
}: NextActionPanelProps) {
  
  if (serverError) {
    return (
      <div className="w-full bg-rose-950/20 border border-rose-500/30 rounded-2xl p-4 flex items-start space-x-3.5 backdrop-blur-md animate-fadeIn mb-6">
        <span className="text-xl">🚨</span>
        <div className="space-y-1">
          <h4 className="text-xs font-bold text-rose-400">시스템 오류</h4>
          <p className="text-xs text-rose-300/80 leading-relaxed">
            백엔드 서버와 연결하지 못했습니다. 서버가 실행 중인지 확인해 주세요.
          </p>
        </div>
      </div>
    );
  }

  // 사실 확인 또는 스타일 선택 단계에서 사실 카드 부족 시 우선 노출
  const isFactsValidationNeeded = (currentStep === 'facts_verification' || currentStep === 'style_selection') && confirmedFactCount < 3;
  // 사실 확인 또는 스타일 선택 단계에서 카테고리 미확정 시 우선 노출
  const isCategoryValidationNeeded = (currentStep === 'facts_verification' || currentStep === 'style_selection') && !categoryConfirmed;

  return (
    <div className="w-full bg-slate-900/30 border border-slate-800 rounded-2xl p-4 flex items-start space-x-3.5 backdrop-blur-sm shadow-md mb-6 animate-fadeIn">
      <span className="text-xl shrink-0 mt-0.5">💡</span>
      <div className="space-y-2 flex-1">
        <h4 className="text-xs font-bold text-indigo-400 uppercase tracking-widest">현재 할 일 안내</h4>
        <p className="text-xs text-slate-300 leading-relaxed font-semibold">
          {NEXT_ACTION_MESSAGES[currentStep]}
        </p>

        {(isFactsValidationNeeded || isCategoryValidationNeeded) && (
          <div className="mt-3 p-3 bg-amber-950/20 border border-amber-900/45 rounded-xl space-y-2 text-xs">
            <p className="font-bold text-amber-400 flex items-center space-x-1">
              <span>⚠️</span>
              <span>다음 단계를 위해 다음 사항이 충족되어야 합니다:</span>
            </p>
            <ul className="list-disc list-inside text-[11px] text-amber-300/85 space-y-1">
              {isFactsValidationNeeded && (
                <li>
                  확인된 사실 카드가 3개 이상 필요합니다. (현재 확정: <strong className="text-white">{confirmedFactCount}개</strong>)
                </li>
              )}
              {isCategoryValidationNeeded && (
                <li>
                  카테고리를 확정해야 상세페이지 구조를 안정적으로 만들 수 있습니다. 생활/리빙 상품이면 Living을 선택해 주세요.
                </li>
              )}
            </ul>
          </div>
        )}
      </div>
    </div>
  );
}

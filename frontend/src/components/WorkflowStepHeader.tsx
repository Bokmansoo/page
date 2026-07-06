import React from 'react';

export const SELLFORM_WORKFLOW_STEPS = [
  { key: "raw_input", label: "1 자료 입력" },
  { key: "facts_verification", label: "2 사실 확인" },
  { key: "style_selection", label: "3 스타일 선택" },
  { key: "page_editor", label: "4 상세페이지 편집" },
  { key: "export", label: "5 저장/내보내기" },
] as const;

export type WorkflowStepKey = (typeof SELLFORM_WORKFLOW_STEPS)[number]['key'];

interface WorkflowStepHeaderProps {
  currentStep: WorkflowStepKey;
}

export default function WorkflowStepHeader({ currentStep }: WorkflowStepHeaderProps) {
  const currentIndex = SELLFORM_WORKFLOW_STEPS.findIndex(step => step.key === currentStep);

  return (
    <div className="w-full bg-slate-900/50 border border-slate-800/80 rounded-2xl p-4 backdrop-blur-md shadow-lg mb-6">
      <div className="flex flex-col md:flex-row items-center justify-between gap-4 md:gap-2">
        {SELLFORM_WORKFLOW_STEPS.map((step, idx) => {
          const isCurrent = step.key === currentStep;
          const isCompleted = idx < currentIndex;
          const isPending = idx > currentIndex;

          return (
            <React.Fragment key={step.key}>
              <div className="flex items-center space-x-3.5">
                <div
                  className={`w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold transition-all duration-300 ${
                    isCurrent
                      ? 'bg-blue-600 text-white ring-4 ring-blue-500/20'
                      : isCompleted
                      ? 'bg-emerald-600/20 border border-emerald-500 text-emerald-400'
                      : 'bg-slate-950/60 border border-slate-800 text-slate-500'
                  }`}
                >
                  {isCompleted ? '✓' : idx + 1}
                </div>
                <div className="flex flex-col">
                  <span
                    className={`text-xs font-bold tracking-wide transition-colors duration-300 ${
                      isCurrent
                        ? 'text-blue-400'
                        : isCompleted
                        ? 'text-emerald-400'
                        : 'text-slate-500'
                    }`}
                  >
                    {step.label}
                  </span>
                  {isCompleted && (
                    <span className="text-[9px] text-emerald-500/80 font-medium">완료</span>
                  )}
                  {isCurrent && (
                    <span className="text-[9px] text-blue-400 font-medium animate-pulse">진행 중</span>
                  )}
                  {isPending && (
                    <span className="text-[9px] text-slate-600 font-medium">대기</span>
                  )}
                </div>
              </div>
              {idx < SELLFORM_WORKFLOW_STEPS.length - 1 && (
                <div className="hidden md:block flex-1 h-[2px] bg-slate-800/60 mx-4 max-w-[60px]" />
              )}
            </React.Fragment>
          );
        })}
      </div>
    </div>
  );
}

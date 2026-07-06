'use client';

import React, { useState } from 'react';

export type OrchestrationState =
  | 'intake_received'
  | 'understanding_ready'
  | 'strategy_ready'
  | 'visual_plan_ready'
  | 'image_cost_approval_required'
  | 'images_generating'
  | 'images_ready_for_review'
  | 'copy_ready'
  | 'page_ready'
  | 'package_ready'
  | 'failed_needs_input';

export interface GenerationProgressPanelProps {
  currentStatus: OrchestrationState | string;
  onApproveCost: () => Promise<void>;
  onRegenerateOrSkip?: (action: 'approve' | 'reject' | 'regenerate' | 'skip') => Promise<void>;
}

export default function GenerationProgressPanel({
  currentStatus,
  onApproveCost,
  onRegenerateOrSkip,
}: GenerationProgressPanelProps) {
  const [approving, setApproving] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  // 단계별 텍스트 매핑
  const stateMappings: Record<string, { label: string; desc: string; progress: number }> = {
    intake_received: { label: '상품 이해 중', desc: '입력된 정보를 기반으로 제품 특성을 분석하고 있습니다.', progress: 10 },
    understanding_ready: { label: '상품 이해 중', desc: '제품 정보 분석을 성공적으로 완료했습니다.', progress: 20 },
    strategy_ready: { label: '판매 전략 설계 중', desc: '제품의 매력 소구점과 판매 전략을 설계하고 있습니다.', progress: 30 },
    visual_plan_ready: { label: '이미지 연출 준비 중', desc: '각 광고 섹션별 이미지 연출 계획을 기획하고 있습니다.', progress: 40 },
    image_cost_approval_required: { label: '이미지 생성 승인 대기', desc: '고비용 AI 이미지 생성 승인을 대기하고 있습니다.', progress: 50 },
    images_generating: { label: 'AI 이미지 생성 중', desc: '기획된 구도에 맞춰 AI 이미지를 연출하고 있습니다.', progress: 65 },
    images_ready_for_review: { label: '생성 이미지 확인 필요', desc: '연출된 이미지가 정확성 요건을 만족하는지 검토 중입니다.', progress: 75 },
    copy_ready: { label: '문구 생성 중', desc: '전략과 이미지를 토대로 고전환율 광고 카피를 뽑아내고 있습니다.', progress: 85 },
    page_ready: { label: '상세페이지 구성 중', desc: '텍스트와 이미지를 조립해 상세페이지 시안을 만들고 있습니다.', progress: 95 },
    package_ready: { label: '판매 패키지 완성 중', desc: 'Figma, PNG 및 등록 데이터셋 패키징을 완료했습니다.', progress: 100 },
    failed_needs_input: { label: '수동 입력 필요', desc: '자동 정보 수집이 제한되어 추가적인 입력 보완이 필요합니다.', progress: 50 },
  };

  const currentInfo = stateMappings[currentStatus] || {
    label: '진행 중',
    desc: '상세페이지 파이프라인 처리가 계속되고 있습니다.',
    progress: 50,
  };

  const handleApprove = async () => {
    try {
      setApproving(true);
      setErrorMsg(null);
      await onApproveCost();
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : '승인 요청에 실패했습니다.';
      setErrorMsg(message);
    } finally {
      setApproving(false);
    }
  };

  return (
    <div className="w-full max-w-2xl mx-auto p-6 bg-slate-900/60 border border-slate-800/80 rounded-2xl backdrop-blur-md shadow-2xl space-y-6">
      {/* Progress Title Section */}
      <div className="flex justify-between items-center">
        <div>
          <span className="text-[10px] font-mono font-bold tracking-widest text-slate-500 uppercase">Orchestration Progress</span>
          <h3 className="text-base font-bold text-slate-100 mt-0.5 bg-gradient-to-r from-blue-400 to-indigo-400 bg-clip-text text-transparent">
            {currentInfo.label}
          </h3>
        </div>
        <span className="text-xs font-mono font-bold text-blue-400 bg-blue-950/40 border border-blue-900/50 px-3 py-1 rounded-full">
          {currentInfo.progress}%
        </span>
      </div>

      {/* Progress Bar */}
      <div className="w-full h-2.5 bg-slate-950 rounded-full overflow-hidden border border-slate-900">
        <div
          className="h-full bg-gradient-to-r from-blue-500 to-indigo-500 rounded-full transition-all duration-500 ease-out"
          style={{ width: `${currentInfo.progress}%` }}
        />
      </div>

      {/* Description */}
      <p className="text-xs text-slate-400 leading-relaxed bg-slate-950/30 p-3.5 rounded-xl border border-slate-850/60">
        {currentInfo.desc}
      </p>

      {/* Cost Approval Mode UI */}
      {currentStatus === 'image_cost_approval_required' && (
        <div className="mt-4 p-5 rounded-xl bg-indigo-950/20 border border-indigo-900/40 space-y-4">
          <div className="flex items-start space-x-3 text-xs text-indigo-300">
            <span className="text-lg leading-none">💰</span>
            <div className="space-y-1">
              <p className="font-bold text-slate-200">AI 이미지 생성 비용 승인 요청</p>
              <p className="text-slate-400 leading-normal">
                기획된 컷에 기반해 고비용 AI 이미지 생성을 시작하기 위해 요금 결제 승인이 필요합니다.
              </p>
            </div>
          </div>
          {errorMsg && (
            <p className="text-[11px] text-rose-400">{errorMsg}</p>
          )}
          <button
            onClick={handleApprove}
            disabled={approving}
            className="w-full py-2.5 bg-indigo-600 hover:bg-indigo-700 text-white font-bold text-xs rounded-lg transition-all shadow-lg hover:shadow-indigo-500/20 disabled:opacity-40"
          >
            {approving ? '비용 결제 진행 중...' : '비용 승인 및 AI 이미지 생성 시작'}
          </button>
        </div>
      )}

      {/* Image Verification Mode UI (Task 4: Recovery Option) */}
      {currentStatus === 'images_ready_for_review' && onRegenerateOrSkip && (
        <div className="mt-4 p-5 rounded-xl bg-amber-950/10 border border-amber-900/30 space-y-4">
          <div className="flex items-start space-x-3 text-xs text-amber-400">
            <span className="text-lg leading-none">⚠️</span>
            <div className="space-y-1">
              <p className="font-bold text-slate-200">생성 이미지 검수 필요</p>
              <p className="text-slate-400 leading-normal">
                품질 혹은 제품 정합성이 미흡할 경우 다시 제작하거나, 기존 사진만으로 상세페이지를 만들고 생성을 건너뛸 수 있습니다.
              </p>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-2">
            <button
              onClick={() => onRegenerateOrSkip('regenerate')}
              className="flex-1 py-2.5 bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-200 text-xs font-bold rounded-lg transition-all"
            >
              🔄 AI 이미지 재생성 요청
            </button>
            <button
              onClick={() => onRegenerateOrSkip('approve')}
              className="flex-1 py-2.5 bg-amber-600 hover:bg-amber-700 text-white text-xs font-bold rounded-lg transition-all"
            >
              ⏭️ 검토 통과 및 최종 완성
            </button>
            <button
              onClick={() => onRegenerateOrSkip('reject')}
              className="flex-1 py-2.5 bg-rose-950/60 hover:bg-rose-900/70 border border-rose-900/60 text-rose-100 text-xs font-bold rounded-lg transition-all"
            >
              reject and revise
            </button>
            <button
              onClick={() => onRegenerateOrSkip('skip')}
              className="flex-1 py-2.5 bg-slate-900 hover:bg-slate-800 border border-slate-700 text-slate-300 text-xs font-bold rounded-lg transition-all"
            >
              continue with original photo
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

'use client';

import React, { useState, useEffect, useCallback } from 'react';

export interface ImageGenerationJob {
  job_id: string;
  section_id: string;
  role: string;
  source_asset_ids: string[];
  prompt: string;
  negative_prompt: string;
  preserve_product_identity: boolean;
  output_size: string;
  cost_tier: string;
  status:
    | 'planned'
    | 'needs_generation'
    | 'awaiting_cost_approval'
    | 'generating'
    | 'needs_review'
    | 'approved'
    | 'rejected'
    | 'failed';
  output_asset_id?: string;
  error_code?: string;
  warnings?: string[];
  attempt_count?: number;
}

interface ProjectAsset {
  id: string;
  filename: string;
  file_path: string;
  mime_type: string;
  source_type: string;
}

interface VisualPackagePanelProps {
  projectId: string;
  backendUrl: string;
  headers: Record<string, string>;
  projectAssets: ProjectAsset[];
  onUpdateSuccess?: () => void;
}

const ROLE_LABELS: Record<string, string> = {
  representative_product: '대표 상품 이미지 (대표컷)',
  cutout_product: '누끼 제품 이미지 (제품 단독)',
  lifestyle_scene: '실내/실외 연출 이미지 (라이프스타일)',
  problem_scene: '고객 고민 연출 이미지 (문제 상황)',
  benefit_visual: '소구점 도식화 이미지 (기능 설명)',
  detail_closeup: '상세 접사 이미지 (디테일/소재)',
  comparison_graphic: '비교표 그래픽 (대비 효과)',
  badge_set: '안전 인증/아이콘 (신뢰 보증)',
  faq_graphic: '자주 묻는 질문 그래픽 (안내 카드)',
  thumbnail: '썸네일 이미지 (목록 대표)',
  cta_visual: '구매 촉진 배너 (최종 유도)',
};

const ROLE_DESCRIPTIONS: Record<string, string> = {
  representative_product: '상세페이지 상단 및 커버에서 제품을 가장 잘 표현하는 핵심 컷',
  cutout_product: '배경 없이 제품 본연의 형태만 뚜렷하게 보여주는 스펙성 단독 컷',
  lifestyle_scene: '실제 주거 환경이나 야외에서 조화롭게 사용되는 느낌을 주는 감성 컷',
  problem_scene: '제품 사용 전 고객이 겪는 덥고 불편한 상황을 극적으로 대변하는 연출 컷',
  benefit_visual: '텍스트 소구점만으로는 부족한 특장점을 도표나 시각 자료로 설명하는 컷',
  detail_closeup: '제품의 재질감, 결합 부위, 작동 버튼 등 세밀한 만듦새를 클로즈업한 컷',
  comparison_graphic: '타사 일반 제품과의 성능이나 소재 차이를 표 형태로 한눈에 대조하는 컷',
  badge_set: '인증 마크, 정품 마크 등 신뢰감을 높이는 그래픽 영역 (실제 마크는 레이어로 합성됩니다)',
  faq_graphic: '자주 들어오는 문의 사항을 정리한 설명 비주얼 (텍스트는 편집 레이어로 얹어집니다)',
  thumbnail: '검색 목록이나 광고 소재로 활용하기 좋게 강조된 정사각형 썸네일',
  cta_visual: '상세페이지 최하단에서 바로 구매 버튼을 클릭하도록 유도하는 최종 강조 컷',
};

const ERROR_EXPLANATIONS: Record<string, string> = {
  MODERATION_REJECTED: '안전 정책 및 모더레이션 기준에 의해 생성 요청이 거절되었습니다. 다른 지시문을 시도해 주세요.',
  QUALITY_GATE_FAILED: '이미지 품질 적합성 검사(해상도 및 빈 화면 체크)를 통과하지 못해 AI 생성본이 기각되었습니다.',
  IDENTITY_GATE_REJECTED: '브랜드 정체성 규정 위반(텍스트 또는 무단 로고 삽입)으로 감지되어 AI 품질 필터에서 반려되었습니다.',
  RATE_LIMIT_EXCEEDED: '현재 AI 생성기 사용량이 많아 차단되었습니다. 잠시 후 다시 시도해 주세요.',
  TIMEOUT: 'AI 생성 서버 응답이 지연되어 시간 초과가 발생했습니다.',
  AUTHENTICATION_FAILED: 'AI 연동 모듈 API Key 인증 오류가 발생했습니다.',
};

export default function VisualPackagePanel({
  projectId,
  backendUrl,
  headers,
  projectAssets,
  onUpdateSuccess,
}: VisualPackagePanelProps) {
  const [jobs, setJobs] = useState<ImageGenerationJob[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [regenerating, setRegenerating] = useState<boolean>(false);
  const [updatingJobId, setUpdatingJobId] = useState<string | null>(null);
  const [editingJobId, setEditingJobId] = useState<string | null>(null);
  const [manualPromptText, setManualPromptText] = useState<string>('');
  const [showAssetSelectorForJobId, setShowAssetSelectorForJobId] = useState<string | null>(null);
  const [confirmingCostJobId, setConfirmingCostJobId] = useState<string | null>(null);

  // 1. Fetch visual package
  const loadVisualPackage = useCallback(async (showLoader = true) => {
    try {
      if (showLoader) setLoading(true);
      const res = await fetch(`${backendUrl}/projects/${projectId}/visual-package`, {
        headers,
      });
      if (res.ok) {
        const data = await res.json();
        setJobs(data);
      }
    } catch (err) {
      console.error('Failed to load visual package:', err);
    } finally {
      if (showLoader) setLoading(false);
    }
  }, [backendUrl, projectId, headers]);

  useEffect(() => {
    loadVisualPackage();
  }, [projectId, loadVisualPackage]);

  // 2. Poll for generating or cost-approving jobs
  useEffect(() => {
    const hasGenerating = jobs.some((j) => j.status === 'generating');
    if (!hasGenerating) return;

    const interval = setInterval(() => {
      loadVisualPackage(false);
    }, 3000);

    return () => clearInterval(interval);
  }, [jobs, loadVisualPackage]);

  // 3. Cache Invalidation & Regeneration Flow
  const handleRegenerate = async () => {
    if (
      !window.confirm(
        '비주얼 패키지 기획서를 초기화하고 새로 생성하시겠습니까? 현재 생성된 AI 이미지 및 수정사항이 모두 리셋됩니다.'
      )
    ) {
      return;
    }
    try {
      setRegenerating(true);
      const res = await fetch(`${backendUrl}/projects/${projectId}/visual-package/regenerate`, {
        method: 'POST',
        headers,
      });
      if (res.ok) {
        const data = await res.json();
        setJobs(data);
        if (onUpdateSuccess) onUpdateSuccess();
      } else {
        alert('기획서 재생성에 실패했습니다.');
      }
    } catch (err) {
      console.error('Failed to regenerate visual package:', err);
    } finally {
      setRegenerating(false);
    }
  };

  // 4. Action Handlers using job_id
  const handleUpdateJob = async (jobId: string, payload: Partial<ImageGenerationJob>) => {
    try {
      setUpdatingJobId(jobId);
      const res = await fetch(`${backendUrl}/projects/${projectId}/visual-package/jobs/${jobId}/update`, {
        method: 'POST',
        headers: {
          ...headers,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(payload),
      });
      if (res.ok) {
        const updatedJob = await res.json();
        setJobs((prev) => prev.map((j) => (j.job_id === jobId ? updatedJob : j)));
        if (onUpdateSuccess) onUpdateSuccess();
      } else {
        const errData = await res.json();
        alert(`수정에 실패했습니다: ${errData.detail || '검증 에러'}`);
      }
    } catch (err) {
      console.error('Error updating job:', err);
    } finally {
      setUpdatingJobId(null);
    }
  };



  const startEditingPrompt = (job: ImageGenerationJob) => {
    setEditingJobId(job.job_id);
    setManualPromptText(job.prompt);
  };

  const saveManualPrompt = async (jobId: string) => {
    if (!manualPromptText.trim()) return;
    await handleUpdateJob(jobId, {
      prompt: manualPromptText,
      status: 'needs_generation',
    });
    setEditingJobId(null);
  };

  const selectOriginalPhoto = async (jobId: string, assetId: string, assetFilename: string) => {
    await handleUpdateJob(jobId, {
      status: 'planned',
      source_asset_ids: [assetId],
      prompt: `Original product photo used: {filename: ${assetFilename}}`,
      preserve_product_identity: true,
    });
    setShowAssetSelectorForJobId(null);
  };

  const makeAiImage = async (job: ImageGenerationJob) => {
    const isProductRelated = ['representative_product', 'cutout_product', 'lifestyle_scene', 'detail_closeup'].includes(
      job.role
    );
    const sourceIds = isProductRelated ? projectAssets.filter((a) => a.mime_type.startsWith('image/')).map((a) => a.id) : [];

    await handleUpdateJob(job.job_id, {
      status: 'needs_generation',
      source_asset_ids: sourceIds,
      preserve_product_identity: isProductRelated && sourceIds.length > 0,
      prompt:
        job.prompt.startsWith('Original product photo used:') || job.prompt.startsWith('Original photo used:')
          ? ''
          : job.prompt,
    });
  };

  // AI API Integration Triggers (Sprint 44.5)
  const triggerGenerate = async (jobId: string, costApproved = false) => {
    try {
      setUpdatingJobId(jobId);
      const res = await fetch(`${backendUrl}/projects/${projectId}/visual-jobs/${jobId}/generate`, {
        method: 'POST',
        headers: {
          ...headers,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ cost_approved: costApproved }),
      });
      if (res.ok) {
        const updatedJob = await res.json();
        setJobs((prev) => prev.map((j) => (j.job_id === jobId ? updatedJob : j)));
        setConfirmingCostJobId(null);
        if (onUpdateSuccess) onUpdateSuccess();
      } else {
        const errData = await res.json();
        alert(`생성 요청 실패: ${errData.detail || '에러 발생'}`);
      }
    } catch (err) {
      console.error('Error generating image:', err);
    } finally {
      setUpdatingJobId(null);
    }
  };

  const triggerApprove = async (jobId: string) => {
    try {
      setUpdatingJobId(jobId);
      const res = await fetch(`${backendUrl}/projects/${projectId}/visual-jobs/${jobId}/approve`, {
        method: 'POST',
        headers,
      });
      if (res.ok) {
        const updatedJob = await res.json();
        setJobs((prev) => prev.map((j) => (j.job_id === jobId ? updatedJob : j)));
        if (onUpdateSuccess) onUpdateSuccess();
      }
    } catch (err) {
      console.error('Error approving image:', err);
    } finally {
      setUpdatingJobId(null);
    }
  };

  const triggerReject = async (jobId: string) => {
    try {
      setUpdatingJobId(jobId);
      const res = await fetch(`${backendUrl}/projects/${projectId}/visual-jobs/${jobId}/reject`, {
        method: 'POST',
        headers,
      });
      if (res.ok) {
        const updatedJob = await res.json();
        setJobs((prev) => prev.map((j) => (j.job_id === jobId ? updatedJob : j)));
        if (onUpdateSuccess) onUpdateSuccess();
      }
    } catch (err) {
      console.error('Error rejecting image:', err);
    } finally {
      setUpdatingJobId(null);
    }
  };

  const triggerRegenerate = async (jobId: string, revisedPrompt?: string) => {
    try {
      setUpdatingJobId(jobId);
      const res = await fetch(`${backendUrl}/projects/${projectId}/visual-jobs/${jobId}/regenerate`, {
        method: 'POST',
        headers: {
          ...headers,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ prompt: revisedPrompt }),
      });
      if (res.ok) {
        const updatedJob = await res.json();
        setJobs((prev) => prev.map((j) => (j.job_id === jobId ? updatedJob : j)));
        if (onUpdateSuccess) onUpdateSuccess();
      }
    } catch (err) {
      console.error('Error regenerating image:', err);
    } finally {
      setUpdatingJobId(null);
    }
  };

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center py-20 space-y-4">
        <div className="w-8 h-8 border-4 border-indigo-500 border-t-transparent rounded-full animate-spin"></div>
        <p className="text-xs text-slate-400 font-medium">비주얼 패키지 기획서를 구성하고 있습니다...</p>
      </div>
    );
  }

  return (
    <div className="w-full space-y-6 text-slate-200">
      <div className="border-b border-slate-800/80 pb-4 mb-4 flex items-start justify-between">
        <div className="space-y-0.5">
          <h3 className="text-sm font-bold text-slate-200 flex items-center space-x-2">
            <span>🖼️ 비주얼 패키지 기획서</span>
            <span className="text-[10px] bg-indigo-950 text-indigo-400 px-2 py-0.5 border border-indigo-900/60 rounded-full font-normal">
              Sprint 44.5 AI
            </span>
          </h3>
          <p className="text-[11px] text-slate-500 mt-1 leading-relaxed">
            상세페이지 이미지 기획과 AI 프롬프트 계약서를 관리합니다.
          </p>
        </div>
        <button
          onClick={handleRegenerate}
          disabled={regenerating}
          className="px-2.5 py-1 bg-slate-800 hover:bg-slate-700 disabled:opacity-50 text-slate-300 rounded text-[10px] font-bold transition-all flex items-center space-x-1 border border-slate-750"
        >
          {regenerating ? (
            <span className="w-2.5 h-2.5 border-2 border-slate-300 border-t-transparent rounded-full animate-spin"></span>
          ) : (
            <span>🔄</span>
          )}
          <span>기획 초기화</span>
        </button>
      </div>

      <div className="space-y-4 max-h-[70vh] overflow-y-auto pr-1">
        {jobs.map((job) => {
          const isUpdating = updatingJobId === job.job_id;
          const isEditing = editingJobId === job.job_id;
          const isAssetSelectorOpen = showAssetSelectorForJobId === job.job_id;

          const matchedAsset =
            job.source_asset_ids && job.source_asset_ids.length > 0
              ? projectAssets.find((a) => a.id === job.source_asset_ids[0])
              : null;

          const matchedOutputAsset = job.output_asset_id
            ? projectAssets.find((a) => a.id === job.output_asset_id)
            : null;

          return (
            <div
              key={job.job_id}
              className={`p-4 rounded-xl border transition-all duration-300 relative ${
                job.status === 'planned'
                  ? 'bg-slate-900/30 border-emerald-900/60 shadow-sm shadow-emerald-950/10'
                  : job.status === 'approved'
                  ? 'bg-indigo-950/20 border-indigo-900/60 shadow-sm shadow-indigo-950/20'
                  : job.status === 'needs_review'
                  ? 'bg-amber-950/20 border-amber-900/60 shadow-sm'
                  : job.status === 'rejected'
                  ? 'bg-slate-900/40 border-slate-700/80'
                  : job.status === 'failed'
                  ? 'bg-red-950/20 border-red-900/60'
                  : 'bg-slate-900/50 border-slate-800/80 hover:border-slate-700'
              }`}
            >
              {/* Card Header: Role & Status */}
              <div className="flex items-start justify-between mb-2">
                <div className="space-y-0.5">
                  <h4 className="text-xs font-bold text-slate-100">{ROLE_LABELS[job.role] || job.role}</h4>
                  <p className="text-[10px] text-slate-500 leading-normal max-w-xs">{ROLE_DESCRIPTIONS[job.role]}</p>
                </div>

                <div className="flex items-center space-x-1.5">
                  {job.status === 'planned' && (
                    <span className="inline-flex items-center space-x-1 px-2 py-0.5 bg-emerald-950/60 text-emerald-400 border border-emerald-900/60 rounded text-[9px] font-semibold">
                      <span>✓</span>
                      <span>원본 사진 사용</span>
                    </span>
                  )}
                  {job.status === 'needs_generation' && (
                    <span className="inline-flex items-center space-x-1 px-2 py-0.5 bg-slate-800 text-slate-400 border border-slate-700 rounded text-[9px] font-semibold">
                      <span>✨</span>
                      <span>AI 이미지 생성 가능</span>
                    </span>
                  )}
                  {job.status === 'awaiting_cost_approval' && (
                    <span className="inline-flex items-center space-x-1 px-2 py-0.5 bg-yellow-950/60 text-yellow-400 border border-yellow-900/60 rounded text-[9px] font-semibold">
                      <span>⏳</span>
                      <span>비용 승인 필요</span>
                    </span>
                  )}
                  {job.status === 'generating' && (
                    <span className="inline-flex items-center space-x-1 px-2 py-0.5 bg-blue-950/60 text-blue-400 border border-blue-900/60 rounded text-[9px] font-semibold">
                      <span className="w-2 h-2 border border-blue-400 border-t-transparent rounded-full animate-spin"></span>
                      <span>생성 중</span>
                    </span>
                  )}
                  {job.status === 'needs_review' && (
                    <span className="inline-flex items-center space-x-1 px-2 py-0.5 bg-amber-950/60 text-amber-400 border border-amber-900/60 rounded text-[9px] font-semibold">
                      <span>⚠️</span>
                      <span>검수 필요</span>
                    </span>
                  )}
                  {job.status === 'approved' && (
                    <span className="inline-flex items-center space-x-1 px-2 py-0.5 bg-indigo-950/80 text-indigo-400 border border-indigo-900/80 rounded text-[9px] font-semibold">
                      <span>✓</span>
                      <span>선택됨</span>
                    </span>
                  )}
                  {job.status === 'rejected' && (
                    <span className="inline-flex items-center space-x-1 px-2 py-0.5 bg-slate-800 text-slate-300 border border-slate-700 rounded text-[9px] font-semibold">
                      <span>AI 생성본 미사용</span>
                    </span>
                  )}
                  {job.status === 'failed' && (
                    <span className="inline-flex items-center space-x-1 px-2 py-0.5 bg-red-950/60 text-red-400 border border-red-900/60 rounded text-[9px] font-semibold">
                      <span>✕</span>
                      <span>생성 실패</span>
                    </span>
                  )}
                </div>
              </div>

              {/* Reference & Output Image Previews */}
              <div className="flex gap-4 my-3 items-center">
                {/* 1. Original Reference Image */}
                {matchedAsset && (
                  <div className="space-y-1">
                    <span className="text-[9px] text-slate-500 block font-semibold">원본 참조 이미지</span>
                    <img
                      src={`${backendUrl.replace('/api/v1', '')}/uploads/${matchedAsset.filename}`}
                      className="w-20 h-20 object-cover rounded-lg border border-slate-800"
                      alt="Original Reference"
                    />
                  </div>
                )}

                {/* Arrow indicator */}
                {matchedAsset &&
                  (job.status === 'needs_review' ||
                    job.status === 'approved' ||
                    job.status === 'rejected') && (
                  <div className="text-slate-600 text-lg font-bold">➔</div>
                )}

                {/* 2. Generated Output Image */}
                {(job.status === 'needs_review' ||
                  job.status === 'approved' ||
                  job.status === 'rejected') &&
                  job.output_asset_id && (
                  <div className="space-y-1">
                    <span className="text-[9px] text-indigo-400 block font-semibold">AI 생성 결과</span>
                    <img
                      src={
                        matchedOutputAsset
                          ? `${backendUrl.replace('/api/v1', '')}/uploads/${matchedOutputAsset.filename}`
                          : `${backendUrl.replace('/api/v1', '')}/uploads/ai_generated/ai_${job.job_id}_${
                              job.attempt_count || 1
                            }.png`
                      }
                      className="w-20 h-20 object-cover rounded-lg border border-indigo-800"
                      alt="AI Generated Output"
                    />
                  </div>
                )}
              </div>

              {/* Mapped Original Asset Bar */}
              {job.status === 'planned' && (
                <div className="mt-2 mb-2 p-2 rounded bg-slate-950/40 border border-slate-800/40 flex items-center justify-between text-[11px]">
                  <span className="text-slate-400 truncate max-w-[240px]">
                    📸 <strong>연결된 자산:</strong>{' '}
                    {matchedAsset ? matchedAsset.filename : job.prompt.replace('Original product photo used: ', '')}
                  </span>
                  <button
                    onClick={() => setShowAssetSelectorForJobId(job.job_id)}
                    className="text-[9px] text-blue-400 hover:text-blue-300 font-semibold underline cursor-pointer"
                  >
                    사진 변경
                  </button>
                </div>
              )}

              {/* Prompt Text / Form */}
              <div className="space-y-1.5 mt-2">
                <span className="text-[9px] font-bold text-slate-500 uppercase tracking-widest">비주얼 연출 지시문</span>

                {isEditing ? (
                  <div className="space-y-2 mt-1">
                    <textarea
                      value={manualPromptText}
                      onChange={(e) => setManualPromptText(e.target.value)}
                      className="w-full p-2 bg-slate-950 border border-slate-800 rounded-lg text-xs text-slate-300 leading-normal focus:outline-none focus:border-indigo-500"
                      rows={3}
                    />
                    <div className="flex justify-end space-x-2">
                      <button
                        onClick={() => setEditingJobId(null)}
                        className="px-2 py-1 bg-slate-800 hover:bg-slate-700 text-slate-400 rounded text-[10px] font-semibold"
                      >
                        취소
                      </button>
                      <button
                        onClick={() => saveManualPrompt(job.job_id)}
                        className="px-2 py-1 bg-indigo-600 hover:bg-indigo-700 text-white rounded text-[10px] font-semibold"
                      >
                        저장
                      </button>
                    </div>
                  </div>
                ) : (
                  <p className="text-xs text-slate-300 leading-relaxed bg-slate-950/30 p-2.5 rounded-lg border border-slate-900/60 italic font-serif">
                    &quot;{job.prompt || '지시문을 입력해 주세요.'}&quot;
                  </p>
                )}
              </div>

              {/* Identity Warnings Display */}
              {job.warnings && job.warnings.length > 0 && (
                <div className="bg-amber-950/40 border border-amber-900/60 p-2.5 rounded-lg text-[10px] text-amber-300 space-y-1 mt-2.5">
                  <div className="font-bold flex items-center space-x-1 text-amber-400">
                    <span>⚠️</span>
                    <span>품질 및 브랜드 정체성 일치성 검사 경고:</span>
                  </div>
                  <ul className="list-disc list-inside space-y-0.5 pl-1 opacity-90">
                    {job.warnings.map((w, idx) => (
                      <li key={idx} className="leading-relaxed">
                        {w}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {/* Error Explanation Card */}
              {job.status === 'failed' && job.error_code && (
                <div className="bg-red-950/30 border border-red-900/60 p-2.5 rounded-lg text-[10px] text-red-300 mt-2.5 space-y-1">
                  <div className="font-bold text-red-400">생성 실패 사유:</div>
                  <p className="leading-relaxed">
                    {ERROR_EXPLANATIONS[job.error_code] || `생성 오류가 발생했습니다 (${job.error_code}).`}
                  </p>
                </div>
              )}

              {/* Config Badges */}
              {job.status !== 'planned' && (
                <div className="flex flex-wrap gap-2 mt-3 text-[9px] text-slate-500 border-t border-slate-900/50 pt-2">
                  <span>
                    📐 크기: <strong>{job.output_size}</strong>
                  </span>
                  <span>
                    💳 예상 비용: <strong className="text-indigo-400">{job.cost_tier}</strong>
                  </span>
                  <span>
                    🛡️ 아이덴티티 유지:{' '}
                    <strong className={job.preserve_product_identity ? 'text-emerald-400' : 'text-slate-400'}>
                      {job.preserve_product_identity ? 'ON (참조 활성)' : 'OFF'}
                    </strong>
                  </span>
                </div>
              )}

              {/* Cost Confirmation Approval Gate */}
              {confirmingCostJobId === job.job_id && (
                <div className="mt-3 p-3 bg-indigo-950/40 border border-indigo-900/50 rounded-lg space-y-2.5">
                  <div className="text-[10px] text-indigo-300 leading-relaxed font-medium">
                    본 이미지 생성 작업은 <strong className="text-white underline">{job.cost_tier}</strong> 등급의 비용이
                    과금됩니다. 진행하시겠습니까?
                  </div>
                  <div className="flex space-x-2">
                    <button
                      onClick={() => setConfirmingCostJobId(null)}
                      className="px-2.5 py-1 bg-slate-800 hover:bg-slate-700 text-slate-400 rounded text-[10px] font-bold"
                    >
                      취소
                    </button>
                    <button
                      onClick={() => triggerGenerate(job.job_id, true)}
                      className="px-2.5 py-1 bg-indigo-600 hover:bg-indigo-700 text-white rounded text-[10px] font-bold"
                    >
                      비용 승인 및 생성 시작
                    </button>
                  </div>
                </div>
              )}

              {/* Control Action Buttons Grid */}
              <div className="grid grid-cols-4 gap-2 mt-4 border-t border-slate-850/60 pt-3">
                {/* 1. Use original photo */}
                {job.status === 'planned' ? (
                  <button
                    disabled={isUpdating}
                    onClick={() => setShowAssetSelectorForJobId(isAssetSelectorOpen ? null : job.job_id)}
                    className="py-1.5 bg-slate-800/80 hover:bg-slate-700/90 text-slate-300 rounded-lg text-[10px] font-semibold transition-all disabled:opacity-50"
                  >
                    📸 사진 변경
                  </button>
                ) : (
                  <button
                    disabled={isUpdating}
                    onClick={() => triggerReject(job.job_id)}
                    className="py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-400 rounded-lg text-[10px] font-semibold transition-all disabled:opacity-50"
                  >
                    📸 원본 사진 사용
                  </button>
                )}

                {/* 2. AI Generate or Approve depending on state */}
                {job.status === 'planned' && (
                  <button
                    disabled={isUpdating}
                    onClick={() => makeAiImage(job)}
                    className="py-1.5 bg-indigo-600/10 hover:bg-indigo-600/20 text-indigo-400 border border-indigo-500/20 rounded-lg text-[10px] font-semibold transition-all disabled:opacity-50"
                  >
                    ✨ AI 이미지로
                  </button>
                )}

                {(job.status === 'needs_generation' || job.status === 'awaiting_cost_approval') && (
                  <button
                    disabled={isUpdating || confirmingCostJobId === job.job_id}
                    onClick={() => setConfirmingCostJobId(job.job_id)}
                    className="py-1.5 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg text-[10px] font-bold transition-all disabled:opacity-50"
                  >
                    ⚡ AI 이미지 생성
                  </button>
                )}

                {job.status === 'generating' && (
                  <div className="py-1.5 bg-slate-800 text-slate-500 rounded-lg text-[10px] font-semibold text-center select-none flex items-center justify-center space-x-1.5">
                    <span className="w-2.5 h-2.5 border border-slate-500 border-t-transparent rounded-full animate-spin"></span>
                    <span>생성 대기중</span>
                  </div>
                )}

                {job.status === 'needs_review' && (
                  <button
                    disabled={isUpdating}
                    onClick={() => triggerApprove(job.job_id)}
                    className="py-1.5 bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg text-[10px] font-bold transition-all disabled:opacity-50"
                  >
                    ✓ 이 이미지 사용
                  </button>
                )}

                {job.status === 'approved' && (
                  <div className="py-1.5 bg-indigo-950 text-indigo-400 border border-indigo-900 rounded-lg text-[10px] font-semibold text-center select-none">
                    선택됨
                  </div>
                )}

                {(job.status === 'failed' || job.status === 'rejected') && (
                  <button
                    disabled={isUpdating}
                    onClick={() => setConfirmingCostJobId(job.job_id)}
                    className="py-1.5 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg text-[10px] font-bold transition-all disabled:opacity-50"
                  >
                    재생성
                  </button>
                )}

                {/* 3. Re-recommendation */}
                <button
                  disabled={isUpdating || job.status === 'planned' || job.status === 'generating'}
                  onClick={() => triggerRegenerate(job.job_id)}
                  className="py-1.5 bg-slate-800/80 hover:bg-slate-700/90 text-slate-400 rounded-lg text-[10px] font-semibold transition-all disabled:opacity-50"
                >
                  🔄 다시 기획하기
                </button>

                {/* 4. Direct Prompt Edit */}
                <button
                  disabled={isUpdating || isEditing || job.status === 'generating'}
                  onClick={() => startEditingPrompt(job)}
                  className="py-1.5 bg-slate-800/80 hover:bg-slate-700/90 text-slate-400 rounded-lg text-[10px] font-semibold transition-all disabled:opacity-50"
                >
                  ✏️ 직접 설명
                </button>
              </div>

              {/* Asset Selector Dropdown/Modal */}
              {isAssetSelectorOpen && (
                <div className="absolute left-4 right-4 bottom-14 bg-slate-950 border border-slate-800 rounded-xl p-3 shadow-2xl z-20 space-y-2 max-h-[180px] overflow-y-auto">
                  <div className="flex items-center justify-between pb-1.5 border-b border-slate-900">
                    <span className="text-[10px] font-bold text-slate-500">배치할 상품 이미지 자산 선택</span>
                    <button
                      onClick={() => setShowAssetSelectorForJobId(null)}
                      className="text-slate-500 hover:text-slate-300 text-xs"
                    >
                      ✕
                    </button>
                  </div>
                  {projectAssets.filter((a) => a.mime_type.startsWith('image/')).length > 0 ? (
                    <div className="space-y-1">
                      {projectAssets
                        .filter((a) => a.mime_type.startsWith('image/'))
                        .map((asset) => (
                          <button
                            key={asset.id}
                            onClick={() => selectOriginalPhoto(job.job_id, asset.id, asset.filename)}
                            className="w-full text-left p-1.5 text-[10px] hover:bg-slate-900 rounded text-slate-300 hover:text-white transition-colors truncate"
                          >
                            🖼️ {asset.filename}
                          </button>
                        ))}
                    </div>
                  ) : (
                    <p className="text-[10px] text-amber-400 py-2">
                      프로젝트에 등록된 상품 이미지 자산이 없습니다. 먼저 이미지를 업로드해 주세요.
                    </p>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

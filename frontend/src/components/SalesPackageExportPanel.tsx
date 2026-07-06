'use client';

import React, { useState, useEffect, useCallback } from 'react';
import FigmaExportDialog from './figma/FigmaExportDialog';

interface SalesPackageData {
  long_png: {
    file_path: string | null;
    url: string | null;
  };
  editable_web_page: {
    url: string;
  };
  figma_payload: {
    payload: Record<string, unknown>;
    asset_map: Record<string, string>;
  };
  marketplace_package: {
    title: string;
    tags: string[];
    category: string | null;
    representative_image: string | null;
    detail_page_artifact: string | null;
    price: number | null;
    delivery: string | null;
    returns: string | null;
    seo_metadata: {
      title: string;
      description: string;
      keywords: string;
    };
  };
  marketplace_readiness: {
    ready: boolean;
    missing_fields: string[];
    package_hash: string;
    approved: boolean;
    approved_at: string | null;
  };
  copy_sheet: Array<{
    id: string;
    section_type: string;
    title: string | null;
    body_copy: string | null;
  }>;
  visual_assets: Array<{
    id: string;
    filename: string;
    file_path: string;
    mime_type: string;
    source_type: string;
  }>;
}

export interface SalesPackageExportPanelProps {
  projectId: string;
  backendUrl: string;
  headers: Record<string, string>;
  onSwitchToEditTab?: () => void;
}

export default function SalesPackageExportPanel({
  projectId,
  backendUrl,
  headers,
  onSwitchToEditTab,
}: SalesPackageExportPanelProps) {
  const [salesPkg, setSalesPkg] = useState<SalesPackageData | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [submitMessage, setSubmitMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);
  const [isFigmaOpen, setIsFigmaOpen] = useState(false);

  const fetchSalesPackage = useCallback(async () => {
    try {
      setLoading(true);
      const res = await fetch(`${backendUrl}/projects/${projectId}/sales-package`, {
        headers,
      });
      if (res.ok) {
        const data = await res.json();
        setSalesPkg(data);
      }
    } catch (err) {
      console.error('Failed to load sales package:', err);
    } finally {
      setLoading(false);
    }
  }, [backendUrl, projectId, headers]);

  useEffect(() => {
    fetchSalesPackage();
  }, [fetchSalesPackage]);

  if (loading) {
    return (
      <div className="flex items-center justify-center p-12 text-slate-400">
        <div className="w-6 h-6 border-2 border-emerald-500 border-t-transparent rounded-full animate-spin mr-3" />
        <span className="text-xs">세일즈 패키지 데이터를 구성하고 있습니다...</span>
      </div>
    );
  }

  if (!salesPkg) {
    return (
      <div className="p-8 text-center bg-slate-900/30 rounded-xl border border-slate-800 text-slate-500 text-xs">
        패키지 데이터를 구성하지 못했습니다. 먼저 상세페이지 초안을 생성해 주세요.
      </div>
    );
  }

  const { marketplace_package, marketplace_readiness, long_png, copy_sheet, visual_assets } = salesPkg;

  const isValidMarketplaceData = marketplace_readiness.ready;

  const handlePngDownload = () => {
    if (long_png.url) {
      const fullUrl = long_png.url.startsWith('http') ? long_png.url : `${backendUrl.replace(/\/api\/v1\/?$/, '')}${long_png.url}`;
      window.open(fullUrl, '_blank');
    } else {
      alert('출력된 세로 이미지가 존재하지 않습니다. 먼저 상세페이지 검수 및 내보내기 화면에서 판매처 이미지 패키지를 생성해 주세요.');
    }
  };

  const handleMarketplacePrepare = async () => {
    if (!isValidMarketplaceData) {
      alert(`마켓플레이스 등록에 필요한 필수 정보가 누락되었습니다: ${marketplace_readiness.missing_fields.join(', ')}`);
      return;
    }

    const confirmApprove = window.confirm('현재 상품 정보와 상세페이지 이미지 패키지를 마켓 등록 준비본으로 승인하시겠습니까?');
    if (!confirmApprove) return;

    try {
      setSubmitting(true);
      setSubmitMessage(null);
      const prepareRes = await fetch(`${backendUrl}/projects/${projectId}/marketplace/packages`, {
        method: 'POST',
        headers: {
          ...headers,
          'Content-Type': 'application/json',
        },
      });
      const prepareData = await prepareRes.json();
      if (!prepareRes.ok) {
        setSubmitMessage({
          type: 'error',
          text: `실패: ${prepareData.detail?.message || prepareData.detail || '마켓 등록 준비 중 오류가 발생했습니다.'}`,
        });
        return;
      }

      const approveRes = await fetch(`${backendUrl}/projects/${projectId}/marketplace/packages/approve`, {
        method: 'POST',
        headers: {
          ...headers,
          'Content-Type': 'application/json',
        },
      });
      const approveData = await approveRes.json();
      if (!approveRes.ok) {
        setSubmitMessage({
          type: 'error',
          text: `실패: ${approveData.detail?.message || approveData.detail || '마켓 등록 준비본 승인 중 오류가 발생했습니다.'}`,
        });
        return;
      }

      setSubmitMessage({
        type: 'success',
        text: '등록 데이터 준비본이 승인되었습니다. 실제 외부 마켓 전송은 별도 제출 단계에서 진행됩니다.',
      });
      fetchSalesPackage();
    } catch (err) {
      console.error(err);
      setSubmitMessage({
        type: 'error',
        text: '네트워크 연결 오류로 마켓 등록 준비에 실패했습니다.',
      });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="space-y-6 max-w-5xl mx-auto p-6 bg-slate-900/40 border border-slate-800/80 rounded-2xl backdrop-blur-md shadow-2xl">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between pb-4 border-b border-slate-850">
        <div>
          <h3 className="text-lg font-bold text-slate-100 bg-gradient-to-r from-emerald-400 to-teal-400 bg-clip-text text-transparent">
            📦 통합 세일즈 패키지 아웃풋
          </h3>
          <p className="text-xs text-slate-400 mt-1">
            상세페이지 이미지, 마켓플레이스 정보, Figma 디자인본 및 텍스트 데이터의 원스톱 내보내기 경로입니다.
          </p>
        </div>
        <div className="flex items-center gap-2 mt-4 md:mt-0">
          {isValidMarketplaceData ? (
            <span className="text-[11px] bg-emerald-950/80 text-emerald-400 border border-emerald-800/60 px-3 py-1 rounded-full font-bold flex items-center gap-1.5 animate-pulse">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400"></span>
              {marketplace_readiness.approved ? '등록 데이터 승인됨' : '등록 데이터 준비됨 (Ready)'}
            </span>
          ) : (
            <span className="text-[11px] bg-amber-950/80 text-amber-400 border border-amber-800/60 px-3 py-1 rounded-full font-bold flex items-center gap-1.5">
              <span className="w-1.5 h-1.5 rounded-full bg-amber-400"></span>
              필수 마켓 정보 누락
            </span>
          )}
        </div>
      </div>

      {/* Action Buttons Grid */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {/* PNG 저장 */}
        <button
          onClick={handlePngDownload}
          className="flex flex-col items-center justify-center p-4 rounded-xl border border-slate-800 bg-slate-950/40 hover:bg-slate-950 hover:border-slate-700 transition-all text-center space-y-2 group"
        >
          <span className="text-2xl group-hover:scale-110 transition-transform">🖼️</span>
          <span className="text-xs font-bold text-slate-200">PNG 저장</span>
          <span className="text-[10px] text-slate-500">모바일 가이드 이미지 아웃풋</span>
        </button>

        {/* 웹에서 수정 */}
        <button
          onClick={onSwitchToEditTab}
          className="flex flex-col items-center justify-center p-4 rounded-xl border border-slate-800 bg-slate-950/40 hover:bg-slate-950 hover:border-slate-700 transition-all text-center space-y-2 group"
        >
          <span className="text-2xl group-hover:scale-110 transition-transform">✏️</span>
          <span className="text-xs font-bold text-slate-200">웹에서 수정</span>
          <span className="text-[10px] text-slate-500">에디터 일반 편집 탭 전환</span>
        </button>

        {/* Figma로 편집 */}
        <button
          onClick={() => setIsFigmaOpen(true)}
          className="flex flex-col items-center justify-center p-4 rounded-xl border border-slate-800 bg-slate-950/40 hover:bg-slate-950 hover:border-slate-700 transition-all text-center space-y-2 group"
        >
          <span className="text-2xl group-hover:scale-110 transition-transform">🎨</span>
          <span className="text-xs font-bold text-slate-200">Figma로 편집</span>
          <span className="text-[10px] text-slate-500">피그마 플러그인 고급 편집</span>
        </button>

        {/* 마켓 등록 준비 */}
        <button
          onClick={handleMarketplacePrepare}
          disabled={submitting || !isValidMarketplaceData}
          className={`flex flex-col items-center justify-center p-4 rounded-xl border transition-all text-center space-y-2 group ${
            isValidMarketplaceData
              ? 'bg-emerald-600/10 border-emerald-500/50 hover:bg-emerald-600/20 hover:border-emerald-400'
              : 'bg-slate-950/20 border-slate-900 opacity-50 cursor-not-allowed'
          }`}
        >
          <span className="text-2xl group-hover:scale-110 transition-transform">🛒</span>
          <span className="text-xs font-bold text-slate-200">{submitting ? '준비 중...' : '마켓 등록 준비'}</span>
          <span className="text-[10px] text-slate-500">마켓플레이스 정보 승인</span>
        </button>
      </div>

      {submitMessage && (
        <div className={`p-3.5 rounded-xl border text-xs leading-relaxed ${
          submitMessage.type === 'success' ? 'bg-emerald-950/30 border-emerald-900 text-emerald-400' : 'bg-rose-950/30 border-rose-900 text-rose-400'
        }`}>
          {submitMessage.text}
        </div>
      )}

      {/* Main Info Blocks */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6 pt-4">
        {/* Marketplace Data Detail Card */}
        <div className="bg-slate-950/60 border border-slate-850 rounded-xl p-5 space-y-4">
          <h4 className="text-xs font-bold text-slate-400 uppercase tracking-wider">🛒 마켓플레이스 기본 데이터</h4>
          <div className="space-y-2.5 text-xs">
            <div className="flex justify-between py-1 border-b border-slate-900">
              <span className="text-slate-500 font-semibold">상품 제목</span>
              <span className="text-slate-200">{marketplace_package.title || '(없음)'}</span>
            </div>
            <div className="flex justify-between py-1 border-b border-slate-900">
              <span className="text-slate-500 font-semibold">판매 가격</span>
              <span className="text-emerald-400 font-bold">
                {marketplace_package.price ? `${marketplace_package.price.toLocaleString()}원` : '(미지정)'}
              </span>
            </div>
            <div className="flex justify-between py-1 border-b border-slate-900">
              <span className="text-slate-500 font-semibold">카테고리</span>
              <span className="text-slate-200">{marketplace_package.category || '(미지정)'}</span>
            </div>
            <div className="flex justify-between py-1 border-b border-slate-900">
              <span className="text-slate-500 font-semibold">배송비 정보</span>
              <span className="text-slate-200">{marketplace_package.delivery}</span>
            </div>
            <div className="flex justify-between py-1 border-b border-slate-900">
              <span className="text-slate-500 font-semibold">반품/교환</span>
              <span className="text-slate-200">{marketplace_package.returns}</span>
            </div>
            <div className="flex flex-col gap-1 py-1 border-b border-slate-900">
              <span className="text-slate-500 font-semibold">대표 이미지</span>
              {marketplace_package.representative_image ? (
                <div className="flex items-center gap-2 mt-1">
                  <div className="w-10 h-10 rounded bg-slate-900 border border-slate-800 flex items-center justify-center overflow-hidden">
                    <img
                      src={`${backendUrl.replace(/\/api\/v1\/?$/, '')}${marketplace_package.representative_image}`}
                      alt="대표"
                      className="w-full h-full object-cover"
                    />
                  </div>
                  <span className="text-[10px] text-slate-500 truncate max-w-[200px]">
                    {marketplace_package.representative_image}
                  </span>
                </div>
              ) : (
                <span className="text-rose-400 italic">⚠️ 이미지 없음</span>
              )}
            </div>
            <div className="flex flex-col gap-1 py-1">
              <span className="text-slate-500 font-semibold">상세페이지 이미지 (Artifact)</span>
              {marketplace_package.detail_page_artifact ? (
                <span className="text-emerald-400 font-mono text-[10px] break-all">
                  {marketplace_package.detail_page_artifact}
                </span>
              ) : (
                <span className="text-rose-400 italic">
                  ⚠️ 상세페이지 이미지 패키지가 완성되지 않았습니다. (PNG 내보내기를 먼저 수행하세요)
                </span>
              )}
            </div>
          </div>
        </div>

        {/* Assets & Text Sheets Summary */}
        <div className="space-y-4 flex flex-col justify-between">
          {/* Copy Sheet Summary */}
          <div className="bg-slate-950/60 border border-slate-850 rounded-xl p-5">
            <h4 className="text-xs font-bold text-slate-400 uppercase tracking-wider mb-3">📄 카피 시트 텍스트 추출 ({copy_sheet.length}개 섹션)</h4>
            <div className="space-y-2 max-h-40 overflow-y-auto pr-2 scrollbar-thin scrollbar-thumb-slate-800">
              {copy_sheet.map((sec, idx) => (
                <div key={sec.id || idx} className="p-2.5 rounded bg-slate-900/50 border border-slate-850/50 text-[10px] space-y-1">
                  <div className="flex items-center justify-between text-slate-500">
                    <span className="font-mono uppercase">{sec.section_type}</span>
                    <span>#{idx + 1}</span>
                  </div>
                  {sec.title && <p className="font-bold text-slate-350">{sec.title}</p>}
                  {sec.body_copy && <p className="text-slate-400 line-clamp-2 leading-relaxed">{sec.body_copy}</p>}
                </div>
              ))}
            </div>
          </div>

          {/* Visual Assets Summary */}
          <div className="bg-slate-950/60 border border-slate-850 rounded-xl p-5">
            <h4 className="text-xs font-bold text-slate-400 uppercase tracking-wider mb-3">🖼️ 패키지 이미지 자산 ({visual_assets.length}개)</h4>
            <div className="flex gap-2 overflow-x-auto pb-2 scrollbar-thin scrollbar-thumb-slate-800">
              {visual_assets.length === 0 ? (
                <span className="text-[10px] text-slate-500 italic">등록된 이미지 자산이 없습니다.</span>
              ) : (
                visual_assets.map((asset) => (
                  <div key={asset.id} className="flex-shrink-0 w-12 h-12 rounded bg-slate-900 border border-slate-800 overflow-hidden relative group">
                    <img
                      src={`${backendUrl.replace(/\/api\/v1\/?$/, '')}/uploads/${asset.filename}`}
                      alt={asset.filename}
                      className="w-full h-full object-cover group-hover:scale-110 transition-transform"
                    />
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Figma Dialog Modal Container */}
      <FigmaExportDialog
        isOpen={isFigmaOpen}
        onClose={() => setIsFigmaOpen(false)}
        projectId={projectId}
        backendUrl={backendUrl}
        headers={headers}
      />
    </div>
  );
}

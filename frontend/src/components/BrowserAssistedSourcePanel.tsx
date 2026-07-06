'use client';

import React, { useState } from 'react';

interface BulkFactResponse {
  id: string;
  project_id: string;
  fact_text: string;
  source_text?: string;
  source_asset_id?: string;
  verification_status: "unknown" | "confirmed" | "needs_revision";
  created_at: string;
  updated_at: string;
}

interface BrowserAssistedSourcePanelProps {
  projectId: string;
  sourceUrl?: string;
  onSuccess: (createdFacts: BulkFactResponse[], createdCount: number, duplicateCount: number, failedCount: number) => void;
}

interface FactCandidate {
  fact_text: string;
  source_text: string;
}

interface BulkParseResponse {
  candidate_count: number;
  excluded_count: number;
  items: FactCandidate[];
}

export default function BrowserAssistedSourcePanel({
  projectId,
  sourceUrl,
  onSuccess,
}: BrowserAssistedSourcePanelProps) {
  const [pastedText, setPastedText] = useState('');
  const [candidates, setCandidates] = useState<FactCandidate[]>([]);
  const [excludedCount, setExcludedCount] = useState(0);
  const [isParsing, setIsParsing] = useState(false);
  const [isSaving, setIsSaving] = useState(false);

  // 1. 백엔드 파서를 사용해 텍스트를 사실 후보로 변환
  const handleExtractCandidates = async () => {
    if (!pastedText.trim()) {
      alert('상세 설명 또는 스펙 정보를 입력해 주세요.');
      return;
    }

    try {
      setIsParsing(true);
      const uid = localStorage.getItem("X-Mock-User-Id") || "00000000-0000-0000-0000-000000000001";
      const wid = localStorage.getItem("X-Mock-Workspace-Id") || "00000000-0000-0000-0000-000000000002";

      const res = await fetch(`http://localhost:8001/api/v1/projects/${projectId}/facts/bulk/parse`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Mock-User-Id': uid,
          'X-Mock-Workspace-Id': wid,
        },
        body: JSON.stringify({
          text: pastedText,
          max_items: 50,
        }),
      });

      if (!res.ok) {
        throw new Error('붙여넣은 정보를 사실 후보로 변환하지 못했습니다.');
      }

      const result = (await res.json()) as BulkParseResponse;

      if (result.items.length === 0) {
        alert('상품 스펙으로 보이는 3자 이상의 유효한 텍스트 줄을 찾지 못했습니다.');
        return;
      }

      setCandidates(result.items);
      setExcludedCount(result.excluded_count);
    } catch (err) {
      alert(err instanceof Error ? err.message : '오류가 발생했습니다.');
    } finally {
      setIsParsing(false);
    }
  };

  // 2. 개별 후보 리스트에서 특정 항목 제외
  const handleRemoveCandidate = (index: number) => {
    setCandidates((prev) => prev.filter((_, idx) => idx !== index));
  };

  // 3. 백엔드 /facts/bulk API 전송
  const handleSaveFacts = async () => {
    if (candidates.length === 0) return;

    try {
      setIsSaving(true);
      const uid = localStorage.getItem("X-Mock-User-Id") || "00000000-0000-0000-0000-000000000001";
      const wid = localStorage.getItem("X-Mock-Workspace-Id") || "00000000-0000-0000-0000-000000000002";

      const res = await fetch(`http://localhost:8001/api/v1/projects/${projectId}/facts/bulk`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Mock-User-Id': uid,
          'X-Mock-Workspace-Id': wid,
        },
        body: JSON.stringify({
          items: candidates,
          default_status: 'unknown', // 브라우저 수집은 사용자 검수를 거쳐야 하므로 초기 'unknown'
        }),
      });

      if (!res.ok) {
        throw new Error('사실 일괄 저장에 실패했습니다.');
      }

      const result = await res.json();
      onSuccess(result.created, result.created_count, result.duplicate_count, result.failed_count || 0);
      
      // 상태 초기화
      setPastedText('');
      setCandidates([]);
    } catch (err) {
      alert(err instanceof Error ? err.message : '오류가 발생했습니다.');
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <div className="w-full bg-slate-900/40 border border-slate-800/80 rounded-2xl p-5 backdrop-blur-md space-y-5 shadow-xl">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 border-b border-slate-800/80 pb-3.5">
        <div>
          <h3 className="text-sm font-bold text-indigo-400 flex items-center gap-1.5">
            <span>🌐</span> 브라우저 보조 정보 수집기 (Sprint 24)
          </h3>
          <p className="text-[11px] text-slate-400 mt-1 leading-relaxed">
            자동 수집이 제한된 쇼핑몰(쿠팡 등)은 직접 페이지를 열어 상품명, 모델명, 용량, 소재, 구성품, 사용시간 같은 핵심 스펙을 복사해 사실 후보로 변환할 수 있습니다.
          </p>
        </div>
        {sourceUrl && (
          <a
            href={sourceUrl}
            target="_blank"
            rel="noreferrer"
            className="shrink-0 inline-flex items-center justify-center px-3.5 py-1.5 bg-indigo-600 hover:bg-indigo-700 text-white rounded-xl text-xs font-bold transition shadow-md shadow-indigo-600/10"
          >
            💻 상품 페이지 열기 ↗
          </a>
        )}
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
        {/* Left: Input Textarea */}
        <div className="space-y-3.5">
          <div className="space-y-1.5">
            <label className="text-[10px] font-extrabold text-slate-400 block uppercase tracking-wider">
              1. 상품 상세 정보 / 스펙 설명 복사 후 붙여넣기
            </label>
            <div className="rounded-xl border border-indigo-500/20 bg-indigo-500/5 p-3 text-[11px] leading-relaxed text-slate-300 space-y-1.5">
              <p className="font-bold text-indigo-300">복사하면 좋은 정보 예시</p>
              <p>모델명, 배터리 용량, 사용 시간, 충전 방식, 크기, 소재, 구성품, 호환 기기, 사용 방법</p>
              <p className="text-slate-500">배송비, 리뷰 수, 광고 문구처럼 구매 판단 근거가 약한 줄은 자동으로 제외될 수 있습니다.</p>
            </div>
            <textarea
              value={pastedText}
              onChange={(e) => setPastedText(e.target.value)}
              placeholder={`예:\n모델명: FAN JET ULTRA\n배터리: 4,800mAh\n최대 18시간 무선 사용 가능\nUSB-C 충전 지원`}
              rows={8}
              className="w-full bg-slate-950/60 border border-slate-800 rounded-xl p-3 text-xs text-slate-200 focus:border-indigo-500 focus:outline-none leading-relaxed resize-none font-mono placeholder:text-slate-600"
            />
          </div>

          <button
            type="button"
            onClick={handleExtractCandidates}
            disabled={isParsing}
            className="w-full py-2.5 bg-slate-800 hover:bg-slate-700 disabled:opacity-40 disabled:pointer-events-none text-slate-200 border border-slate-700 hover:border-slate-600 rounded-xl text-xs font-bold transition flex items-center justify-center gap-1.5"
          >
            <span>⚙️</span> {isParsing ? '후보 변환 중...' : '여러 사실 후보로 변환하기'}
          </button>
        </div>

        {/* Right: Candidates Preview & Save */}
        <div className="space-y-3.5 flex flex-col">
          <label className="text-[10px] font-extrabold text-slate-400 block uppercase tracking-wider shrink-0">
            2. 변환된 사실 카드 후보 미리보기 ({candidates.length}개)
          </label>
          {candidates.length > 0 && (
            <p className="text-[11px] text-slate-500">
              후보 {candidates.length}개를 찾았고, 배송/리뷰/광고성 문장 등 {excludedCount}개 줄은 제외했습니다.
            </p>
          )}

          <div className="flex-1 bg-slate-950/60 border border-slate-800 rounded-xl p-3 max-h-[195px] overflow-y-auto min-h-[150px] space-y-2">
            {candidates.length === 0 ? (
              <div className="h-full flex items-center justify-center text-xs text-slate-500 italic">
                왼쪽에 내용을 붙여넣고 변환을 진행하면 후보가 여기에 추출됩니다.
              </div>
            ) : (
              candidates.map((cand, idx) => (
                <div
                  key={idx}
                  className="p-2.5 bg-slate-900 border border-slate-850 rounded-lg flex items-start justify-between gap-2 text-xs text-slate-300 hover:border-slate-700 transition"
                >
                  <span className="leading-relaxed break-all">{cand.fact_text}</span>
                  <button
                    type="button"
                    onClick={() => handleRemoveCandidate(idx)}
                    className="text-slate-500 hover:text-rose-400 font-bold px-1 transition text-xs"
                    title="후보 제외"
                  >
                    ✕
                  </button>
                </div>
              ))
            )}
          </div>

          <button
            type="button"
            onClick={handleSaveFacts}
            disabled={candidates.length === 0 || isSaving}
            className="w-full py-2.5 bg-gradient-to-r from-blue-500 to-indigo-600 hover:from-blue-600 hover:to-indigo-700 disabled:opacity-30 disabled:pointer-events-none text-white rounded-xl text-xs font-extrabold transition shadow-lg shrink-0 flex items-center justify-center gap-1.5"
          >
            {isSaving ? (
              <span>저장 중...</span>
            ) : (
              <>
                <span>📥</span> 사실 검증 대기 후보로 저장하기
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}

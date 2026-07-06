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

interface BulkFactModalProps {
  isOpen: boolean;
  onClose: () => void;
  projectId: string;
  onSuccess: (createdFacts: BulkFactResponse[], createdCount: number, duplicateCount: number, failedCount: number) => void;
}


export type BulkFactInput = {
  fact_text: string;
  source_text?: string;
};

export default function BulkFactModal({ isOpen, onClose, projectId, onSuccess }: BulkFactModalProps) {
  const [inputText, setInputText] = useState('');
  const [defaultStatus, setDefaultStatus] = useState<'confirmed' | 'unknown' | 'needs_revision'>('confirmed');
  const [isSubmitting, setIsSubmitting] = useState(false);

  if (!isOpen) return null;

  const parseBulkFacts = (text: string): BulkFactInput[] => {
    const lines = text.split('\n');
    const items: BulkFactInput[] = [];

    for (const line of lines) {
      const trimmedLine = line.trim();
      if (!trimmedLine) continue;

      let factText = trimmedLine;
      let sourceText = '';

      if (trimmedLine.includes('| 근거:')) {
        const parts = trimmedLine.split('| 근거:');
        factText = parts[0].trim();
        sourceText = parts[1] ? parts[1].trim() : '';
      }

      if (factText) {
        items.push({
          fact_text: factText,
          source_text: sourceText || factText,
        });
      }
    }
    return items;
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const items = parseBulkFacts(inputText);
    if (items.length === 0) {
      alert('입력된 사실 정보가 없습니다.');
      return;
    }
    if (items.length > 50) {
      alert(`한 번에 최대 50개까지 입력할 수 있습니다. (현재: ${items.length}개)`);
      return;
    }

    try {
      setIsSubmitting(true);
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
          items,
          default_status: defaultStatus,
        }),
      });

      if (!res.ok) {
        throw new Error('일괄 사실 등록 실패');
      }

      const result = await res.json();
      onSuccess(result.created, result.created_count, result.duplicate_count, result.failed_count || 0);
      setInputText('');
      onClose();
    } catch (err) {
      alert(err instanceof Error ? err.message : '오류가 발생했습니다.');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4 animate-fadeIn">
      <div className="glass-card max-w-lg w-full bg-slate-950 border border-slate-800 p-6 rounded-2xl space-y-5 text-slate-200">
        <div className="flex justify-between items-center pb-2 border-b border-slate-800">
          <h3 className="text-sm font-bold text-indigo-400">여러 사실 한번에 추가 (Bulk Fact Input)</h3>
          <button
            onClick={onClose}
            className="text-slate-400 hover:text-white font-semibold text-xs"
            disabled={isSubmitting}
          >
            닫기
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-1">
            <label className="text-[10px] font-bold text-slate-400 block uppercase">
              사실 및 근거 입력 (한 줄에 하나씩, 최대 50개)
            </label>
            <p className="text-[10px] text-slate-500 mb-1 leading-relaxed">
              형식: 사실 문장 | 근거: 근거 문장 (근거 생략 시 사실과 동일하게 지정)<br />
              예시: 4,800mAh 배터리를 탑재했습니다. | 근거: 4,800mAh 대용량 배터리
            </p>
            <textarea
              value={inputText}
              onChange={(e) => setInputText(e.target.value)}
              placeholder="여기에 복사한 텍스트들을 줄바꿈으로 구분해 붙여넣으세요..."
              rows={8}
              required
              className="w-full bg-slate-900 border border-slate-800 rounded-xl p-3 text-xs text-slate-200 focus:border-indigo-500 focus:outline-none leading-relaxed resize-none font-mono"
            />
          </div>

          <div className="space-y-2">
            <label className="text-[10px] font-bold text-slate-400 block uppercase">기본 검증 상태</label>
            <div className="flex items-center space-x-4">
              <label className="flex items-center space-x-2 text-xs cursor-pointer">
                <input
                  type="radio"
                  name="defaultStatus"
                  value="confirmed"
                  checked={defaultStatus === 'confirmed'}
                  onChange={() => setDefaultStatus('confirmed')}
                  className="accent-indigo-500"
                />
                <span className="text-slate-300">확인됨 (Confirmed)</span>
              </label>
              <label className="flex items-center space-x-2 text-xs cursor-pointer">
                <input
                  type="radio"
                  name="defaultStatus"
                  value="needs_revision"
                  checked={defaultStatus === 'needs_revision'}
                  onChange={() => setDefaultStatus('needs_revision')}
                  className="accent-indigo-500"
                />
                <span className="text-slate-300">수정 필요 (Needs Revision)</span>
              </label>
              <label className="flex items-center space-x-2 text-xs cursor-pointer">
                <input
                  type="radio"
                  name="defaultStatus"
                  value="unknown"
                  checked={defaultStatus === 'unknown'}
                  onChange={() => setDefaultStatus('unknown')}
                  className="accent-indigo-500"
                />
                <span className="text-slate-300">모름 (Unknown)</span>
              </label>
            </div>
          </div>

          <div className="flex justify-end space-x-2 pt-2 border-t border-slate-900">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 border border-slate-800 hover:text-white rounded-xl text-xs font-semibold"
              disabled={isSubmitting}
            >
              취소
            </button>
            <button
              type="submit"
              disabled={isSubmitting}
              className="btn-primary px-4 py-2 rounded-xl text-xs font-semibold disabled:opacity-50"
            >
              {isSubmitting ? '저장 중...' : '사실 일괄 저장'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

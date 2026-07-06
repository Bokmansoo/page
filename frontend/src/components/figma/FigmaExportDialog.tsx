'use client';

import Link from 'next/link';
import { useEffect, useRef, useState } from 'react';
import FigmaExportStatus, { FigmaExportState } from './FigmaExportStatus';

interface FigmaExportDialogProps {
  isOpen: boolean;
  onClose: () => void;
  projectId: string;
  backendUrl: string;
  headers: Record<string, string>;
  pollTimeoutMs?: number;
}

function isValidFigmaDesignUrl(value: string): boolean {
  try {
    const url = new URL(value);
    const parts = url.pathname.split('/').filter(Boolean);
    return (
      url.protocol === 'https:' &&
      (url.hostname === 'figma.com' || url.hostname === 'www.figma.com') &&
      parts[0] === 'design' &&
      Boolean(parts[1])
    );
  } catch {
    return false;
  }
}

export default function FigmaExportDialog({
  isOpen,
  onClose,
  projectId,
  backendUrl,
  headers,
  pollTimeoutMs = 120_000,
}: FigmaExportDialogProps) {
  const [activeTab, setActiveTab] = useState<'live' | 'plugin'>('plugin');

  // Live Export States
  const [targetFileUrl, setTargetFileUrl] = useState('');
  const [status, setStatus] = useState<FigmaExportState>('idle');
  const [jobId, setJobId] = useState<string | null>(null);
  const [authUrl, setAuthUrl] = useState<string | null>(null);
  const [resultNodeUrl, setResultNodeUrl] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const startedAt = useRef<number | null>(null);

  // Figma Plugin States
  const [ticketCode, setTicketCode] = useState<string | null>(null);
  const [ticketExpiresAt, setTicketExpiresAt] = useState<string | null>(null);
  const [isGeneratingTicket, setIsGeneratingTicket] = useState(false);
  const [copySuccess, setCopySuccess] = useState(false);
  const [ticketError, setTicketError] = useState<string | null>(null);
  const [isDownloadingPackage, setIsDownloadingPackage] = useState(false);
  const [packageError, setPackageError] = useState<string | null>(null);

  useEffect(() => {
    if (!jobId || !['queued', 'authenticating', 'rendering'].includes(status)) {
      return;
    }

    const checkStatus = async () => {
      if (startedAt.current && Date.now() - startedAt.current >= pollTimeoutMs) {
        setStatus('timeout');
        setErrorMessage(
          'Figma 응답이 2분 안에 완료되지 않았습니다. 잠시 후 다시 시도해 주세요.',
        );
        return;
      }
      try {
        const response = await fetch(
          `${backendUrl}/projects/${projectId}/page/figma/exports/${jobId}`,
          { headers },
        );
        if (!response.ok) return;
        const data = await response.json();
        setStatus(data.status);
        if (data.status === 'completed') {
          setResultNodeUrl(data.result_node_url || null);
          setErrorMessage(null);
        } else if (data.status === 'failed') {
          setErrorMessage(data.error_message || 'Figma 내보내기에 실패했습니다.');
          setAuthUrl(
            data.error_code === 'AUTH_REQUIRED' ? data.auth_url || null : null,
          );
        }
      } catch {
        setErrorMessage('Figma 작업 상태를 확인하지 못했습니다.');
      }
    };

    void checkStatus();
    const timer = window.setInterval(checkStatus, 1000);
    return () => window.clearInterval(timer);
  }, [backendUrl, headers, jobId, pollTimeoutMs, projectId, status]);

  const startExport = async () => {
    if (!isValidFigmaDesignUrl(targetFileUrl)) {
      setErrorMessage(
        'https://www.figma.com/design/... 형식의 편집 가능한 Design URL을 입력해 주세요.',
      );
      return;
    }

    setStatus('queued');
    setErrorMessage(null);
    setAuthUrl(null);
    setResultNodeUrl(null);
    startedAt.current = Date.now();
    try {
      const response = await fetch(
        `${backendUrl}/projects/${projectId}/page/figma/live-export`,
        {
          method: 'POST',
          headers: { ...headers, 'Content-Type': 'application/json' },
          body: JSON.stringify({ target_file_url: targetFileUrl }),
        },
      );
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.detail || 'Figma 작업을 시작하지 못했습니다.');
      }
      setJobId(data.job_id);
      setStatus(data.status);
    } catch (error) {
      setStatus('failed');
      setErrorMessage(
        error instanceof Error ? error.message : 'Figma 작업을 시작하지 못했습니다.',
      );
    }
  };

  const retry = async () => {
    if (!jobId) return;
    setStatus('queued');
    setErrorMessage(null);
    setAuthUrl(null);
    startedAt.current = Date.now();
    try {
      const response = await fetch(
        `${backendUrl}/projects/${projectId}/page/figma/exports/${jobId}/retry`,
        { method: 'POST', headers },
      );
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.detail || '재시도하지 못했습니다.');
      }
      setStatus(data.status);
    } catch (error) {
      setStatus('failed');
      setErrorMessage(
        error instanceof Error ? error.message : '재시도하지 못했습니다.',
      );
    }
  };

  // Figma Plugin Operations
  const handleGenerateTicket = async () => {
    setIsGeneratingTicket(true);
    setTicketError(null);
    setTicketCode(null);
    try {
      const response = await fetch(
        `${backendUrl}/projects/${projectId}/page/figma-plugin/tickets`,
        {
          method: 'POST',
          headers,
        },
      );
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.detail || '티켓 코드를 생성하지 못했습니다.');
      }
      setTicketCode(data.code);
      setTicketExpiresAt(data.expires_at);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : '오류가 발생했습니다.';
      setTicketError(message);
    } finally {
      setIsGeneratingTicket(false);
    }
  };

  const handleCopyCode = () => {
    if (!ticketCode) return;
    void navigator.clipboard.writeText(ticketCode).then(() => {
      setCopySuccess(true);
      setTimeout(() => setCopySuccess(false), 2000);
    });
  };

  const handleDownloadPackage = async () => {
    setIsDownloadingPackage(true);
    setPackageError(null);
    try {
      const response = await fetch(
        `${backendUrl}/projects/${projectId}/page/figma-plugin/package.json`,
        { headers },
      );
      if (!response.ok) {
        if (response.status === 413) {
          throw new Error('자산 크기가 20MB 제한을 초과하여 다운로드할 수 없습니다.');
        }
        const data = await response.json().catch(() => ({ detail: 'JSON 다운로드 실패' }));
        throw new Error(data.detail || 'JSON 다운로드 실패');
      }
      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `sellform-package-${projectId}.json`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'JSON 다운로드 실패';
      setPackageError(message);
    } finally {
      setIsDownloadingPackage(false);
    }
  };

  const formatExpiration = (isoString: string) => {
    try {
      const date = new Date(isoString);
      return date.toLocaleString('ko-KR', { timeZone: 'Asia/Seoul' });
    } catch {
      return isoString;
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm">
      <div className="w-full max-w-lg overflow-hidden rounded-2xl border border-slate-800 bg-slate-900 shadow-2xl">
        <div className="flex items-center justify-between border-b border-slate-800 px-6 py-5">
          <h3 className="font-bold text-slate-100">Figma 플러그인으로 내보내기</h3>
          <button
            onClick={onClose}
            aria-label="닫기"
            className="text-slate-400 hover:text-white text-xl"
          >
            ×
          </button>
        </div>

        {/* Tabs Bar */}
        <div className="flex border-b border-slate-800 bg-slate-950/20">
          <button
            onClick={() => setActiveTab('plugin')}
            className={`flex-1 py-3 text-xs font-semibold border-b-2 transition-all ${
              activeTab === 'plugin'
                ? 'border-blue-500 text-blue-400'
                : 'border-transparent text-slate-400 hover:text-slate-200'
            }`}
          >
            Figma에서 고급 편집
          </button>
        </div>

        <div className="space-y-5 p-6">
          {activeTab === 'live' ? (
            // Live Export Content
            <div className="space-y-5">
              {status === 'idle' ? (
                <>
                  <p className="text-xs leading-relaxed text-slate-400">
                    편집 권한이 있는 Figma Design 파일에 860px 상세페이지 프레임을
                    만듭니다.
                  </p>
                  <input
                    id="figma-url-input"
                    value={targetFileUrl}
                    onChange={event => setTargetFileUrl(event.target.value)}
                    placeholder="https://www.figma.com/design/..."
                    className="w-full rounded-xl border border-slate-800 bg-slate-950 px-4 py-3 text-xs text-white outline-none focus:border-blue-500"
                  />
                  <button
                    id="figma-start-export-btn"
                    onClick={startExport}
                    className="w-full rounded-xl bg-blue-600 py-3 text-xs font-bold text-white hover:bg-blue-700"
                  >
                    Figma Live 내보내기 시작
                  </button>
                </>
              ) : (
                <FigmaExportStatus status={status} />
              )}

              {errorMessage && (
                <p className="text-xs leading-relaxed text-rose-400">
                  {errorMessage}
                </p>
              )}

              {status === 'completed' && resultNodeUrl && (
                <a
                  id="figma-view-link"
                  href={resultNodeUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex rounded-lg bg-emerald-600 px-4 py-2 text-xs font-bold text-white"
                >
                  Figma에서 확인하기
                </a>
              )}

              {status === 'failed' && authUrl && (
                <div className="flex gap-2">
                  <a
                    id="figma-auth-link"
                    href={authUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex-1 rounded-lg bg-indigo-600 py-2 text-center text-xs font-bold text-white"
                  >
                    Figma 인증하기
                  </a>
                  <button
                    id="figma-retry-auth-btn"
                    onClick={retry}
                    className="flex-1 rounded-lg bg-emerald-600 py-2 text-xs font-bold text-white"
                  >
                    인증 후 재시도
                  </button>
                </div>
              )}

              {((status === 'failed' && !authUrl) || status === 'timeout') && (
                <button
                  id="figma-retry-btn"
                  onClick={jobId ? retry : startExport}
                  className="rounded-lg bg-rose-600 px-4 py-2 text-xs font-bold text-white"
                >
                  다시 시도
                </button>
              )}

              {status !== 'idle' && (
                <Link
                  href={`/workspace/projects/${projectId}/export`}
                  className="block text-xs font-semibold text-blue-300 hover:text-blue-200"
                >
                  PNG 내보내기로 계속하기
                </Link>
              )}
            </div>
          ) : (
            // Figma Plugin Content
            <div className="space-y-6">
              <div className="rounded-xl border border-slate-800 bg-slate-950/40 p-4">
                <h4 className="text-xs font-bold text-slate-200 mb-2">1. Figma 플러그인 연동 및 고급 편집</h4>
                <p className="text-[11px] leading-relaxed text-slate-400 mb-4">
                  일회용 인증 코드를 발급받아 Figma 플러그인 앱에 입력하시면 캔버스에서 더 정밀하고 고급화된 레이아웃 및 텍스트 편집이 가능합니다.
                </p>

                {ticketCode ? (
                  <div className="space-y-3">
                    <div className="flex items-center gap-2">
                      <div className="flex-1 rounded-lg bg-slate-950 border border-slate-800 px-4 py-3 text-center text-base font-bold tracking-widest text-emerald-400 select-all font-mono">
                        {ticketCode}
                      </div>
                      <button
                        onClick={handleCopyCode}
                        className={`rounded-lg px-4 py-3 text-xs font-bold transition-all ${
                          copySuccess ? 'bg-emerald-600 text-white' : 'bg-slate-800 text-slate-200 hover:bg-slate-700'
                        }`}
                      >
                        {copySuccess ? '복사됨!' : '복사'}
                      </button>
                    </div>
                    {ticketExpiresAt && (
                      <p className="text-[10px] text-slate-500 text-right">
                        만료 시간 (10분 유효): {formatExpiration(ticketExpiresAt)}
                      </p>
                    )}
                  </div>
                ) : (
                  <button
                    onClick={handleGenerateTicket}
                    disabled={isGeneratingTicket}
                    className="w-full rounded-lg bg-blue-600 py-2.5 text-xs font-bold text-white hover:bg-blue-700 disabled:opacity-50"
                  >
                    {isGeneratingTicket ? '생성 중...' : '인증 코드 생성'}
                  </button>
                )}

                {ticketError && (
                  <p className="text-[11px] text-rose-400 mt-2">{ticketError}</p>
                )}
              </div>

              <div className="rounded-xl border border-slate-800 bg-slate-950/40 p-4">
                <h4 className="text-xs font-bold text-slate-200 mb-2">2. 오프라인 백업 패키지 다운로드</h4>
                <p className="text-[11px] leading-relaxed text-slate-400 mb-4">
                  Figma 플러그인으로 직접 코드를 전송하기 어려운 오프라인 환경인 경우, 디자인 패키지 파일을 다운로드받아 직접 업로드하여 가져올 수 있습니다. (최대 20MB 제한)
                </p>

                <button
                  onClick={handleDownloadPackage}
                  disabled={isDownloadingPackage}
                  className="w-full rounded-lg bg-slate-800 border border-slate-700 py-2.5 text-xs font-bold text-slate-200 hover:bg-slate-700 disabled:opacity-50"
                >
                  {isDownloadingPackage ? '패키지 생성 및 다운로드 중...' : 'JSON 패키지 다운로드'}
                </button>

                {packageError && (
                  <p className="text-[11px] text-rose-400 mt-2">{packageError}</p>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

'use client';

export type FigmaExportState =
  | 'idle'
  | 'queued'
  | 'authenticating'
  | 'rendering'
  | 'completed'
  | 'failed'
  | 'timeout';

const STEPS: Array<{ key: FigmaExportState; label: string }> = [
  { key: 'queued', label: '대기' },
  { key: 'authenticating', label: '인증' },
  { key: 'rendering', label: '생성' },
  { key: 'completed', label: '완료' },
];

const ORDER: Record<FigmaExportState, number> = {
  idle: -1,
  queued: 0,
  authenticating: 1,
  rendering: 2,
  completed: 3,
  failed: -1,
  timeout: -1,
};

export default function FigmaExportStatus({
  status,
}: {
  status: FigmaExportState;
}) {
  if (status === 'idle') return null;

  return (
    <div
      id={`status-${status}`}
      className="grid grid-cols-4 gap-2"
      aria-label="Figma 내보내기 진행 상태"
    >
      {STEPS.map((step, index) => {
        const completed = status === 'completed' || ORDER[status] > index;
        const current = status === step.key;
        return (
          <div key={step.key} className="flex flex-col items-center gap-2">
            <div
              className={`flex h-7 w-7 items-center justify-center rounded-full text-xs font-bold ${
                completed
                  ? 'bg-emerald-600 text-white'
                  : current
                    ? 'animate-pulse bg-blue-600 text-white'
                    : 'bg-slate-800 text-slate-500'
              }`}
            >
              {completed ? '✓' : index + 1}
            </div>
            <span
              className={`text-[10px] font-bold ${
                current ? 'text-blue-400' : 'text-slate-500'
              }`}
            >
              {step.label}
            </span>
          </div>
        );
      })}
    </div>
  );
}

"use client";

import React from "react";

export interface PlanningCard {
  id: string;
  type: string;
  label: string;
  title: string;
  bullets: string[];
  source_fact_ids: string[];
  visual_strategy: string;
  is_enabled: boolean;
  sort_order: number;
}

interface PlanningDraftCardProps {
  card: PlanningCard;
  index: number;
  totalCards: number;
  onChange: (updatedCard: PlanningCard) => void;
  onMoveUp: () => void;
  onMoveDown: () => void;
}

const visualStrategyLabels: Record<string, string> = {
  image_overlay: "이미지 오버레이",
  lifestyle_image: "라이프스타일 이미지",
  graphic_chart: "비교/그래픽",
  text_only: "텍스트 중심",
  html_graphic: "HTML 그래픽",
};

export default function PlanningDraftCard({
  card,
  index,
  totalCards,
  onChange,
  onMoveUp,
  onMoveDown,
}: PlanningDraftCardProps) {
  const handleTitleChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    onChange({ ...card, title: event.target.value });
  };

  const handleBulletChange = (bulletIndex: number, value: string) => {
    const updatedBullets = [...card.bullets];
    updatedBullets[bulletIndex] = value;
    onChange({ ...card, bullets: updatedBullets });
  };

  const handleAddBullet = () => {
    onChange({ ...card, bullets: [...card.bullets, ""] });
  };

  const handleRemoveBullet = (bulletIndex: number) => {
    onChange({
      ...card,
      bullets: card.bullets.filter((_, indexToKeep) => indexToKeep !== bulletIndex),
    });
  };

  const toggleEnabled = () => {
    onChange({ ...card, is_enabled: !card.is_enabled });
  };

  return (
    <div
      data-planning-card={card.type}
      className={`rounded-2xl border p-6 transition-all duration-200 ${
        card.is_enabled
          ? "border-slate-200 bg-white shadow-sm hover:border-slate-300"
          : "border-slate-100 bg-slate-50/70 opacity-70"
      }`}
    >
      <div className="mb-4 flex items-center justify-between border-b border-slate-100 pb-3">
        <div className="flex flex-wrap items-center gap-2">
          <span className="rounded-lg bg-slate-100 px-2.5 py-1 text-xs font-bold text-slate-600">
            {index + 1}
          </span>
          <span className="text-sm font-extrabold text-slate-800">{card.label}</span>
          <span className="rounded border border-emerald-100 bg-emerald-50 px-2 py-0.5 text-[10px] font-semibold text-emerald-700">
            {visualStrategyLabels[card.visual_strategy] || card.visual_strategy}
          </span>
        </div>

        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={onMoveUp}
            disabled={index === 0}
            className="rounded-lg p-1.5 text-slate-400 transition-colors hover:bg-slate-50 hover:text-slate-700 disabled:opacity-30"
            title="위로 이동"
            aria-label={`${card.label} 위로 이동`}
          >
            ↑
          </button>
          <button
            type="button"
            onClick={onMoveDown}
            disabled={index === totalCards - 1}
            className="rounded-lg p-1.5 text-slate-400 transition-colors hover:bg-slate-50 hover:text-slate-700 disabled:opacity-30"
            title="아래로 이동"
            aria-label={`${card.label} 아래로 이동`}
          >
            ↓
          </button>
          <button
            type="button"
            onClick={toggleEnabled}
            className={`ml-2 rounded-lg px-3 py-1.5 text-xs font-bold transition-all ${
              card.is_enabled
                ? "bg-slate-100 text-slate-600 hover:bg-slate-200"
                : "bg-emerald-600 text-white hover:bg-emerald-700"
            }`}
          >
            {card.is_enabled ? "숨기기" : "표시하기"}
          </button>
        </div>
      </div>

      <div className="space-y-4">
        <div>
          <label className="mb-1 block text-[11px] font-bold uppercase tracking-wider text-slate-400">
            제목 / 메시지
          </label>
          <input
            type="text"
            value={card.title}
            onChange={handleTitleChange}
            disabled={!card.is_enabled}
            className="w-full rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-sm font-medium transition-all focus:border-emerald-500 focus:outline-none focus:ring-2 focus:ring-emerald-500/20 disabled:bg-slate-50 disabled:text-slate-400"
            placeholder="이 섹션의 제목을 입력하세요"
          />
        </div>

        <div className="space-y-2">
          <label className="mb-1 block text-[11px] font-bold uppercase tracking-wider text-slate-400">
            본문 포인트
          </label>
          {card.bullets.map((bullet, bulletIndex) => (
            <div key={`${card.id}-bullet-${bulletIndex}`} className="flex items-center gap-2">
              <span className="text-sm text-slate-400">•</span>
              <input
                type="text"
                value={bullet}
                onChange={(event) => handleBulletChange(bulletIndex, event.target.value)}
                disabled={!card.is_enabled}
                className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs transition-all focus:border-emerald-500 focus:outline-none focus:ring-2 focus:ring-emerald-500/20 disabled:bg-slate-50 disabled:text-slate-400"
                placeholder="상세 설명 포인트를 적어주세요"
              />
              <button
                type="button"
                onClick={() => handleRemoveBullet(bulletIndex)}
                disabled={!card.is_enabled || card.bullets.length <= 1}
                className="rounded-lg px-2 py-1 text-xs font-bold text-slate-400 hover:bg-rose-50 hover:text-rose-600 disabled:opacity-30"
              >
                삭제
              </button>
            </div>
          ))}
          <button
            type="button"
            onClick={handleAddBullet}
            disabled={!card.is_enabled}
            className="rounded-lg border border-dashed border-slate-200 px-3 py-2 text-xs font-bold text-slate-500 hover:border-emerald-200 hover:bg-emerald-50 hover:text-emerald-700 disabled:opacity-30"
          >
            포인트 추가
          </button>
        </div>
      </div>
    </div>
  );
}

"use client";

import React, { useState } from "react";
import { useRouter } from "next/navigation";
import { apiUrl } from "@/lib/api";
import PlanningDraftCard, { PlanningCard } from "./PlanningDraftCard";

interface PlanningDraftEditorProps {
  projectId: string;
  initialCards: PlanningCard[];
}

const defaultHeaders = () => {
  const uid = localStorage.getItem("X-Mock-User-Id") || "00000000-0000-0000-0000-000000000001";
  const wid = localStorage.getItem("X-Mock-Workspace-Id") || "00000000-0000-0000-0000-000000000002";
  return {
    "Content-Type": "application/json",
    "X-Mock-User-Id": uid,
    "X-Mock-Workspace-Id": wid,
  };
};

export default function PlanningDraftEditor({ projectId, initialCards }: PlanningDraftEditorProps) {
  const router = useRouter();
  const [cards, setCards] = useState<PlanningCard[]>(initialCards);
  const [isSaving, setIsSaving] = useState(false);
  const [isApproving, setIsApproving] = useState(false);
  const [message, setMessage] = useState<{ type: "success" | "error"; text: string } | null>(null);

  const handleCardChange = (index: number, updatedCard: PlanningCard) => {
    const updatedCards = [...cards];
    updatedCards[index] = updatedCard;
    setCards(updatedCards);
  };

  const handleMoveCard = (index: number, direction: "up" | "down") => {
    if (direction === "up" && index === 0) return;
    if (direction === "down" && index === cards.length - 1) return;

    const swapIndex = direction === "up" ? index - 1 : index + 1;
    const updatedCards = [...cards];
    [updatedCards[index], updatedCards[swapIndex]] = [updatedCards[swapIndex], updatedCards[index]];
    setCards(updatedCards.map((card, sortOrder) => ({ ...card, sort_order: sortOrder })));
  };

  const saveDraft = async () => {
    const res = await fetch(apiUrl(`/api/v1/projects/${projectId}/planning-draft`), {
      method: "PATCH",
      headers: defaultHeaders(),
      body: JSON.stringify({ cards }),
    });

    if (!res.ok) {
      throw new Error("기획 초안을 저장하지 못했습니다.");
    }

    const data = await res.json();
    setCards(data.cards);
    return data.cards as PlanningCard[];
  };

  const handleSaveDraft = async () => {
    setIsSaving(true);
    setMessage(null);
    try {
      await saveDraft();
      setMessage({ type: "success", text: "기획안이 임시 저장되었습니다." });
    } catch (err) {
      setMessage({
        type: "error",
        text: err instanceof Error ? err.message : "저장 중 알 수 없는 오류가 발생했습니다.",
      });
    } finally {
      setIsSaving(false);
    }
  };

  const handleApproveDraft = async () => {
    setIsApproving(true);
    setMessage(null);
    try {
      await saveDraft();

      const res = await fetch(apiUrl(`/api/v1/projects/${projectId}/planning-draft/approve`), {
        method: "POST",
        headers: defaultHeaders(),
      });

      if (!res.ok) {
        throw new Error("상세페이지 조립 처리에 실패했습니다.");
      }

      router.push(`/workspace/projects/${projectId}/result`);
    } catch (err) {
      setMessage({
        type: "error",
        text: err instanceof Error ? err.message : "조립 처리 중 오류가 발생했습니다.",
      });
      setIsApproving(false);
    }
  };

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <div className="sticky top-0 z-10 flex items-center justify-between border-b border-slate-100 bg-slate-50/90 py-4 backdrop-blur-md">
        <div>
          <h2 className="text-xl font-black text-slate-900">상세페이지 기획 검수</h2>
          <p className="mt-1 text-xs text-slate-500">
            상세페이지를 조립하기 전에 섹션 구성과 판매 문구를 다듬어 주세요.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={handleSaveDraft}
            disabled={isSaving || isApproving}
            className="rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-xs font-bold text-slate-700 transition-all hover:bg-slate-50 disabled:opacity-50"
          >
            {isSaving ? "저장 중..." : "임시 저장"}
          </button>
          <button
            type="button"
            onClick={handleApproveDraft}
            disabled={isSaving || isApproving}
            className="rounded-xl bg-emerald-600 px-5 py-2.5 text-xs font-black text-white shadow-lg shadow-emerald-100 transition-all hover:bg-emerald-700 disabled:opacity-50"
          >
            {isApproving ? "조립 중..." : "상세페이지 조립하기 →"}
          </button>
        </div>
      </div>

      {message && (
        <div
          role="status"
          className={`flex items-center rounded-xl border px-4 py-3 text-sm ${
            message.type === "success"
              ? "border-emerald-100 bg-emerald-50 text-emerald-700"
              : "border-rose-100 bg-rose-50 text-rose-700"
          }`}
        >
          <span className="mr-2">{message.type === "success" ? "✓" : "!"}</span>
          <span>{message.text}</span>
        </div>
      )}

      <div className="space-y-4">
        {cards.map((card, index) => (
          <PlanningDraftCard
            key={card.id}
            card={card}
            index={index}
            totalCards={cards.length}
            onChange={(updatedCard) => handleCardChange(index, updatedCard)}
            onMoveUp={() => handleMoveCard(index, "up")}
            onMoveDown={() => handleMoveCard(index, "down")}
          />
        ))}
      </div>

      <div className="flex justify-end gap-3 border-t border-slate-100 pt-6">
        <button
          type="button"
          onClick={handleSaveDraft}
          disabled={isSaving || isApproving}
          className="rounded-2xl border border-slate-200 bg-white px-5 py-3.5 text-sm font-bold text-slate-700 transition-all hover:bg-slate-50 disabled:opacity-50"
        >
          {isSaving ? "저장 중..." : "임시 저장"}
        </button>
        <button
          type="button"
          onClick={handleApproveDraft}
          disabled={isSaving || isApproving}
          className="rounded-2xl bg-emerald-600 px-6 py-3.5 text-sm font-black text-white shadow-lg shadow-emerald-100 transition-all hover:bg-emerald-700 disabled:opacity-50"
        >
          {isApproving ? "상세페이지 조립 중..." : "상세페이지 조립하기"}
        </button>
      </div>
    </div>
  );
}

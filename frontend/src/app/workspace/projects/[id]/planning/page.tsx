"use client";

import React, { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { apiUrl } from "@/lib/api";
import PlanningDraftEditor from "@/components/planning/PlanningDraftEditor";
import { PlanningCard } from "@/components/planning/PlanningDraftCard";

const defaultHeaders = () => {
  const uid = localStorage.getItem("X-Mock-User-Id") || "00000000-0000-0000-0000-000000000001";
  const wid = localStorage.getItem("X-Mock-Workspace-Id") || "00000000-0000-0000-0000-000000000002";
  return {
    "Content-Type": "application/json",
    "X-Mock-User-Id": uid,
    "X-Mock-Workspace-Id": wid,
  };
};

export default function ProjectPlanningPage() {
  const params = useParams();
  const projectId = params.id as string;

  const [cards, setCards] = useState<PlanningCard[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [statusText, setStatusText] = useState("기획안을 불러오는 중입니다...");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;

    const fetchPlanningDraft = async () => {
      try {
        const endpoint = apiUrl(`/api/v1/projects/${projectId}/planning-draft`);
        const getRes = await fetch(endpoint, {
          headers: defaultHeaders(),
          cache: "no-store",
        });

        if (getRes.status === 404) {
          if (!active) return;
          setStatusText("AI 기획 초안을 생성하는 중입니다...");

          const postRes = await fetch(endpoint, {
            method: "POST",
            headers: defaultHeaders(),
          });

          if (!postRes.ok) {
            throw new Error("AI 기획 초안 생성에 실패했습니다.");
          }

          const postData = await postRes.json();
          if (active) {
            setCards(postData.cards);
            setLoading(false);
          }
        } else if (!getRes.ok) {
          throw new Error("기획 초안 조회에 실패했습니다.");
        } else {
          const getData = await getRes.json();
          if (active) {
            setCards(getData.cards);
            setLoading(false);
          }
        }
      } catch (err) {
        if (active) {
          setError(err instanceof Error ? err.message : "기획안 조회 또는 생성 중 오류가 발생했습니다.");
          setLoading(false);
        }
      }
    };

    void fetchPlanningDraft();

    return () => {
      active = false;
    };
  }, [projectId]);

  if (loading) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center bg-slate-50 p-6 text-slate-800">
        <div className="flex w-full max-w-md flex-col items-center space-y-6 rounded-3xl border border-slate-100 bg-white p-10 text-center shadow-xl">
          <div className="relative h-16 w-16">
            <div className="absolute inset-0 animate-spin rounded-full border-4 border-emerald-100 border-t-emerald-600" />
          </div>
          <div className="space-y-2">
            <h3 className="text-lg font-extrabold text-slate-900">기획 초안 준비 중</h3>
            <p className="text-xs leading-relaxed text-slate-500">{statusText}</p>
          </div>
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-slate-100">
            <div className="h-full w-2/5 animate-pulse rounded-full bg-emerald-600" />
          </div>
          <p className="text-[10px] font-medium text-slate-400">
            상세페이지를 만들기 전, 판매 구조와 섹션 흐름을 먼저 구성하고 있습니다.
          </p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-50 p-6 text-slate-800">
        <div className="w-full max-w-md space-y-6 rounded-3xl border border-rose-100 bg-white p-8 text-center shadow-xl">
          <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full border border-rose-100 bg-rose-50 text-xl font-extrabold text-rose-600">
            !
          </div>
          <div className="space-y-2">
            <h3 className="font-extrabold text-slate-900">기획안을 불러오지 못했습니다.</h3>
            <p className="text-xs text-rose-600">{error}</p>
          </div>
          <button
            type="button"
            onClick={() => window.location.reload()}
            className="w-full rounded-xl bg-slate-900 py-3 text-xs font-bold text-white transition-all hover:bg-slate-800"
          >
            다시 시도하기
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-50 p-6 text-slate-800 md:p-10">
      {cards ? (
        <PlanningDraftEditor projectId={projectId} initialCards={cards} />
      ) : (
        <div className="py-10 text-center font-bold text-slate-400">표시할 기획안이 없습니다.</div>
      )}
    </div>
  );
}

"use client";

import React, { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { apiUrl } from "@/lib/api";
import PlanningDraftEditor from "@/components/planning/PlanningDraftEditor";
import { PlanningCard } from "@/components/planning/PlanningDraftCard";

type SourceCapture = {
  id: string;
  url: string;
  platform: string;
  source_role: string;
  collection_status: "pending" | "collected" | "access_limited" | "failed";
  failure_code?: string | null;
  collected_image_count: number;
  collected_spec_count: number;
};

const defaultHeaders = () => {
  const uid = typeof window !== "undefined"
    ? localStorage.getItem("X-Mock-User-Id") || "00000000-0000-0000-0000-000000000001"
    : "00000000-0000-0000-0000-000000000001";
  const wid = typeof window !== "undefined"
    ? localStorage.getItem("X-Mock-Workspace-Id") || "00000000-0000-0000-0000-000000000002"
    : "00000000-0000-0000-0000-000000000002";
  return {
    "Content-Type": "application/json",
    "X-Mock-User-Id": uid,
    "X-Mock-Workspace-Id": wid,
  };
};

const captureStatusLabel = (capture: SourceCapture) => {
  if (capture.collection_status === "collected") {
    return `수집 완료 · 이미지 ${capture.collected_image_count}장 · 스펙 ${capture.collected_spec_count}개`;
  }
  if (capture.collection_status === "access_limited") {
    const reason: Record<string, string> = {
      http_403: "사이트 접근 제한(403)",
      login_required: "로그인 필요",
      captcha_required: "사람 확인 필요",
      dynamic_page: "동적 페이지 제한",
    };
    return `${reason[capture.failure_code || ""] || "사이트 접근 제한"} · 직접 업로드로 계속 가능`;
  }
  if (capture.collection_status === "failed") return "수집 실패 · 직접 업로드로 계속 가능";
  return "수집 대기 중";
};

export default function ProjectPlanningPage() {
  const params = useParams();
  const projectId = String(params.id);
  const [cards, setCards] = useState<PlanningCard[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [statusText, setStatusText] = useState("기획 초안을 불러오는 중입니다...");
  const [error, setError] = useState<string | null>(null);
  const [sourceCaptures, setSourceCaptures] = useState<SourceCapture[]>([]);

  useEffect(() => {
    let active = true;
    const fetchSourceCaptures = async () => {
      try {
        const response = await fetch(apiUrl(`/api/v1/projects/${projectId}/source-captures`), {
          headers: defaultHeaders(),
          cache: "no-store",
        });
        if (!response.ok) return;
        const captures = await response.json();
        if (active && Array.isArray(captures)) setSourceCaptures(captures);
      } catch {
        // Collection status is supplementary; planning remains available.
      }
    };
    void fetchSourceCaptures();
    return () => { active = false; };
  }, [projectId]);

  useEffect(() => {
    let active = true;
    const fetchPlanningDraft = async () => {
      try {
        setLoading(true);
        setError(null);
        const endpoint = apiUrl(`/api/v1/projects/${projectId}/planning-draft`);
        const getRes = await fetch(endpoint, { headers: defaultHeaders(), cache: "no-store" });
        if (getRes.status === 404) {
          if (!active) return;
          setStatusText("AI 기획 초안을 새로 준비하는 중입니다...");
          const postRes = await fetch(endpoint, { method: "POST", headers: defaultHeaders() });
          if (!postRes.ok) throw new Error("AI 기획 초안 생성에 실패했습니다.");
          const postData = await postRes.json();
          if (active) setCards(postData.cards ?? []);
        } else if (!getRes.ok) {
          throw new Error("기획 초안 조회에 실패했습니다.");
        } else {
          const getData = await getRes.json();
          if (active) setCards(getData.cards ?? []);
        }
      } catch (err) {
        if (active) setError(err instanceof Error ? err.message : "기획안을 준비하는 중 오류가 발생했습니다.");
      } finally {
        if (active) setLoading(false);
      }
    };
    void fetchPlanningDraft();
    return () => { active = false; };
  }, [projectId]);

  if (loading) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center bg-slate-50 p-6 text-slate-800">
        <div className="flex w-full max-w-md flex-col items-center space-y-6 rounded-3xl border border-slate-100 bg-white p-10 text-center shadow-xl">
          <div className="relative h-16 w-16"><div className="absolute inset-0 animate-spin rounded-full border-4 border-emerald-100 border-t-emerald-600" /></div>
          <div className="space-y-2">
            <h3 className="text-lg font-extrabold text-slate-900">기획 초안 준비 중</h3>
            <p className="text-xs leading-relaxed text-slate-500">{statusText}</p>
          </div>
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-slate-100"><div className="h-full w-2/5 animate-pulse rounded-full bg-emerald-600" /></div>
          <p className="text-[10px] font-medium text-slate-400">판매 구조와 섹션 흐름을 먼저 구성하고 있습니다.</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-50 p-6 text-slate-800">
        <div className="w-full max-w-md space-y-6 rounded-3xl border border-rose-100 bg-white p-8 text-center shadow-xl">
          <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full border border-rose-100 bg-rose-50 text-xl font-extrabold text-rose-600">!</div>
          <div className="space-y-2"><h3 className="font-extrabold text-slate-900">기획안을 불러오지 못했습니다</h3><p className="text-xs text-rose-600">{error}</p></div>
          <button type="button" onClick={() => window.location.reload()} className="w-full rounded-xl bg-slate-900 py-3 text-xs font-bold text-white hover:bg-slate-800">다시 시도하기</button>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-50 p-6 text-slate-800 md:p-10">
      {sourceCaptures.length > 0 && (
        <section className="mx-auto mb-5 max-w-4xl rounded-xl border border-slate-200 bg-white px-4 py-4 text-sm">
          <h2 className="font-bold text-slate-900">상품 링크 수집 결과</h2>
          <ul className="mt-3 space-y-2">
            {sourceCaptures.map((capture) => (
              <li key={capture.id} className={`rounded-lg px-3 py-2 ${capture.collection_status === "collected" ? "bg-emerald-50 text-emerald-800" : "bg-amber-50 text-amber-900"}`}>
                <span className="font-semibold">{capture.platform}</span>
                <span className="mx-2 text-slate-400">·</span>
                <span>{capture.source_role === "product" ? "상품 링크" : "참고 링크"}</span>
                <p className="mt-1 text-xs">{captureStatusLabel(capture)}</p>
              </li>
            ))}
          </ul>
          {sourceCaptures.some((capture) => capture.collection_status !== "collected") && (
            <p className="mt-3 text-xs leading-5 text-slate-600">링크 수집이 제한되어도 직접 올린 대표컷·기능컷·사용 장면·구성품 사진과 판매자 입력 정보를 우선 사용합니다.</p>
          )}
        </section>
      )}
      {cards && cards.length > 0 ? (
        <PlanningDraftEditor projectId={projectId} initialCards={cards} />
      ) : (
        <div className="py-10 text-center font-bold text-slate-400">표시할 기획안이 없습니다.</div>
      )}
    </div>
  );
}

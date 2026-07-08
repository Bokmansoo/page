"use client";

import React, { Suspense, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import GenerationStatusPanel from "@/components/GenerationStatusPanel";
import { apiUrl } from "@/lib/api";
import { fetchGenerationStatusDashboard, GenerationStatusDashboard, mockHeaders } from "@/lib/generationStatus";

export default function OperationsPage() {
  return (
    <Suspense fallback={<OperationsLoading />}>
      <OperationsPageContent />
    </Suspense>
  );
}

function OperationsPageContent() {
  const searchParams = useSearchParams();
  const focusProjectId = searchParams.get("projectId");
  const [loading, setLoading] = useState(true);
  const [seeding, setSeeding] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [generationStatus, setGenerationStatus] = useState<GenerationStatusDashboard | null>(null);

  const pageCopy = useMemo(() => {
    if (focusProjectId) {
      return {
        eyebrow: "Duplicate guard",
        title: "이미 작업 중인 상세페이지를 확인하세요",
        description:
          "같은 상품을 다시 생성하려고 해서 중복 생성 방지 화면으로 이동했습니다. 기존 작업을 이어서 진행하면 토큰과 시간을 아낄 수 있어요.",
      };
    }
    return {
      eyebrow: "My detail pages",
      title: "작업 상태",
      description: "생성 중인 상세페이지와 완료된 작업을 한곳에서 확인하고 이어서 진행하세요.",
    };
  }, [focusProjectId]);

  const fetchGenerationStatus = async () => {
    try {
      setLoading(true);
      const data = await fetchGenerationStatusDashboard();
      setGenerationStatus(data);
      setError(null);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "작업 상태를 불러오지 못했습니다.");
    } finally {
      setLoading(false);
    }
  };

  const handleSeed = async () => {
    if (!confirm("Mock 작업 상태 데이터를 생성할까요? 기존 테스트 데이터가 추가될 수 있습니다.")) {
      return;
    }

    try {
      setSeeding(true);
      const res = await fetch(apiUrl("/api/v1/operations/seed"), {
        method: "POST",
        headers: mockHeaders(),
      });

      if (!res.ok) {
        throw new Error("Mock 작업 상태 데이터 생성에 실패했습니다.");
      }

      await fetchGenerationStatus();
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : "Mock 데이터 생성 중 오류가 발생했습니다.");
    } finally {
      setSeeding(false);
    }
  };

  useEffect(() => {
    void fetchGenerationStatus();
  }, []);

  return (
    <div className="mx-auto max-w-7xl px-6 py-12">
      <div className="mb-8 flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <p className="text-xs font-black uppercase tracking-[0.3em] text-emerald-700">{pageCopy.eyebrow}</p>
          <h1 className="mt-3 text-4xl font-black tracking-tight text-slate-950">{pageCopy.title}</h1>
          <p className="mt-3 max-w-3xl text-base leading-7 text-slate-500">{pageCopy.description}</p>
        </div>
        <div className="flex gap-3">
          <button
            type="button"
            onClick={fetchGenerationStatus}
            disabled={loading}
            className="rounded-xl border border-slate-200 bg-white px-5 py-3 text-sm font-black text-slate-700 hover:bg-slate-50 disabled:opacity-60"
          >
            상태 새로고침
          </button>
          <button
            type="button"
            onClick={handleSeed}
            disabled={seeding}
            className="rounded-xl bg-violet-600 px-5 py-3 text-sm font-black text-white shadow-sm hover:bg-violet-700 disabled:opacity-60"
          >
            {seeding ? "생성 중..." : "Mock 실상태 시딩"}
          </button>
        </div>
      </div>

      {error ? (
        <div className="mb-6 rounded-2xl border border-rose-200 bg-rose-50 px-5 py-4 text-sm font-bold text-rose-700">
          {error} 백엔드가 실행 중인지 확인한 뒤 다시 시도해 주세요.
        </div>
      ) : null}

      {loading && !generationStatus ? (
        <OperationsLoading />
      ) : generationStatus ? (
        <GenerationStatusPanel data={generationStatus} onRefresh={fetchGenerationStatus} focusProjectId={focusProjectId} />
      ) : (
        <div className="rounded-3xl border border-dashed border-slate-200 bg-white py-20 text-center">
          <p className="text-lg font-black text-slate-950">작업 상태를 불러오지 못했습니다.</p>
          <p className="mt-2 text-sm text-slate-500">백엔드 서버를 켠 뒤 새로고침해 주세요.</p>
        </div>
      )}
    </div>
  );
}

function OperationsLoading() {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-20 text-slate-500">
      <div className="h-8 w-8 animate-spin rounded-full border-4 border-emerald-500 border-t-transparent" />
      <span className="text-sm font-bold">작업 상태를 확인하는 중입니다...</span>
    </div>
  );
}

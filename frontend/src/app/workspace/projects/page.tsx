"use client";

import React, { useEffect, useState } from "react";
import ProjectWorklist from "@/components/ProjectWorklist";
import { fetchProjectWorklist, ProjectWorklistItem } from "@/lib/projectWorklist";

export default function WorkspaceProjectsPage() {
  const [items, setItems] = useState<ProjectWorklistItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadProjects = async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await fetchProjectWorklist();
      setItems(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "작업 목록을 불러오지 못했습니다.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadProjects();
  }, []);

  return (
    <main className="mx-auto max-w-5xl space-y-6 px-6 py-10">
      <div className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
        <div>
          <p className="text-xs font-bold uppercase tracking-[0.18em] text-emerald-700">My detail pages</p>
          <h1 className="mt-2 text-3xl font-extrabold tracking-tight text-slate-900">작업 목록</h1>
          <p className="mt-2 text-sm text-slate-500">
            생성한 상세페이지를 다시 열고, 검수하거나 출력 이력에서 다운로드 파일을 확인하세요.
          </p>
        </div>
        <button
          type="button"
          onClick={loadProjects}
          disabled={loading}
          className="rounded-xl border border-slate-200 bg-white px-4 py-2 text-xs font-bold text-slate-600 hover:bg-slate-50 disabled:opacity-50"
        >
          {loading ? "불러오는 중..." : "새로고침"}
        </button>
      </div>

      {error && (
        <div className="rounded-xl border border-rose-100 bg-rose-50 px-4 py-3 text-sm text-rose-700">
          {error}
        </div>
      )}

      {loading ? (
        <div className="flex items-center justify-center rounded-3xl border border-slate-200 bg-white py-24">
          <div className="h-8 w-8 animate-spin rounded-full border-4 border-emerald-500 border-t-transparent" />
        </div>
      ) : (
        <ProjectWorklist items={items} />
      )}
    </main>
  );
}

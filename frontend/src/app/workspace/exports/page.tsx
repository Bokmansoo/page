"use client";

import React, { useEffect, useState } from "react";
import ExportHistoryTable from "@/components/ExportHistoryTable";
import { fetchExportHistory, ExportHistoryItem } from "@/lib/exportHistory";

export default function ExportHistoryPage() {
  const [items, setItems] = useState<ExportHistoryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadHistory = async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await fetchExportHistory();
      setItems(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "출력 이력을 불러오지 못했습니다.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadHistory();
  }, []);

  return (
    <main className="mx-auto max-w-5xl space-y-6 px-6 py-10">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-extrabold tracking-tight text-slate-900">출력 이력</h1>
          <p className="mt-1 text-sm text-slate-500">
            PNG, JPG 등으로 출력한 상세페이지 기록을 확인하고 다시 다운로드할 수 있습니다.
          </p>
        </div>
        <button
          type="button"
          onClick={loadHistory}
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
        <div className="flex items-center justify-center py-20">
          <div className="h-8 w-8 animate-spin rounded-full border-4 border-emerald-500 border-t-transparent" />
        </div>
      ) : (
        <ExportHistoryTable items={items} />
      )}
    </main>
  );
}

"use client";

import React from "react";
import type { ExportHistoryItem } from "@/lib/exportHistory";
import { apiUrl } from "@/lib/api";

function statusBadge(status: ExportHistoryItem["status"]) {
  switch (status) {
    case "completed":
      return <span className="rounded-full border border-emerald-200 bg-emerald-50 px-2.5 py-0.5 text-xs font-bold text-emerald-700">완료</span>;
    case "failed":
      return <span className="rounded-full border border-rose-200 bg-rose-50 px-2.5 py-0.5 text-xs font-bold text-rose-700">실패</span>;
    case "running":
      return <span className="rounded-full border border-blue-200 bg-blue-50 px-2.5 py-0.5 text-xs font-bold text-blue-700">진행 중</span>;
    default:
      return <span className="rounded-full border border-slate-200 bg-slate-50 px-2.5 py-0.5 text-xs font-bold text-slate-600">대기 중</span>;
  }
}

function downloadHref(url: string): string {
  return /^https?:\/\//i.test(url) ? url : apiUrl(url);
}

export default function ExportHistoryTable({ items }: { items: ExportHistoryItem[] }) {
  if (items.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center rounded-2xl border border-dashed border-slate-200 py-16 text-center">
        <svg className="mb-3 h-10 w-10 text-slate-300" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M8 4H6a2 2 0 00-2 2v12a2 2 0 002 2h12a2 2 0 002-2V6a2 2 0 00-2-2h-2m-4-1v8m0 0l3-3m-3 3L9 8m-5 5h2.586a1 1 0 01.707.293l2.414 2.414a1 1 0 00.707.293h3.172a1 1 0 00.707-.293l2.414-2.414a1 1 0 01.707-.293H20" />
        </svg>
        <p className="text-sm font-semibold text-slate-500">아직 출력 이력이 없습니다.</p>
        <p className="mt-1 text-xs text-slate-400">상세페이지를 생성하고 저장하면 여기에 기록됩니다.</p>
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white">
      <table className="w-full text-left text-sm">
        <thead className="border-b border-slate-100 bg-slate-50 text-xs font-bold uppercase tracking-wider text-slate-500">
          <tr>
            <th className="p-4">상품명</th>
            <th className="p-4">형식</th>
            <th className="p-4">상태</th>
            <th className="p-4">생성일</th>
            <th className="p-4">다운로드</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100 text-slate-700">
          {items.map((item) => (
            <tr key={item.id} className="hover:bg-slate-50/50">
              <td className="p-4 font-semibold text-slate-900">{item.project_name}</td>
              <td className="p-4">
                <span className="rounded-md bg-slate-100 px-2 py-0.5 text-xs font-bold text-slate-600">
                  {item.format.toUpperCase()}
                </span>
              </td>
              <td className="p-4">{statusBadge(item.status)}</td>
              <td className="p-4 text-xs text-slate-500">
                {new Date(item.created_at).toLocaleString("ko-KR")}
              </td>
              <td className="p-4">
                {item.status === "completed" && item.download_url ? (
                  <a
                    href={downloadHref(item.download_url)}
                    download={item.filename ?? undefined}
                    className="inline-flex items-center gap-1 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-1.5 text-xs font-bold text-emerald-700 hover:bg-emerald-100"
                  >
                    <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                    </svg>
                    다시 다운로드
                  </a>
                ) : item.status === "failed" && item.error_message ? (
                  <span className="text-xs text-rose-500" title={item.error_message}>
                    {item.error_message.length > 40 ? `${item.error_message.slice(0, 40)}...` : item.error_message}
                  </span>
                ) : (
                  <span className="text-xs text-slate-400">대기 중</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

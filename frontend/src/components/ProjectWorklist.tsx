"use client";

import Link from "next/link";
import type { ProjectWorklistItem, ProjectWorklistStatus } from "@/lib/projectWorklist";

const statusLabels: Record<ProjectWorklistStatus, { label: string; className: string }> = {
  generating: {
    label: "생성 중",
    className: "border-blue-200 bg-blue-50 text-blue-700",
  },
  needs_review: {
    label: "검수 필요",
    className: "border-amber-200 bg-amber-50 text-amber-700",
  },
  completed: {
    label: "완료",
    className: "border-emerald-200 bg-emerald-50 text-emerald-700",
  },
  failed: {
    label: "실패",
    className: "border-rose-200 bg-rose-50 text-rose-700",
  },
};

function formatDate(value: string) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  return date.toLocaleString("ko-KR");
}

function statusBadge(status: ProjectWorklistStatus) {
  const meta = statusLabels[status] ?? statusLabels.generating;
  return (
    <span className={`rounded-full border px-2.5 py-0.5 text-xs font-bold ${meta.className}`}>
      {meta.label}
    </span>
  );
}

export default function ProjectWorklist({ items }: { items: ProjectWorklistItem[] }) {
  if (items.length === 0) {
    return (
      <section className="flex flex-col items-center justify-center rounded-3xl border border-dashed border-slate-200 bg-white px-6 py-20 text-center">
        <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-2xl bg-emerald-50 text-emerald-600">
          <svg className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M12 4v16m8-8H4" />
          </svg>
        </div>
        <h2 className="text-lg font-extrabold text-slate-900">아직 생성한 상세페이지가 없습니다.</h2>
        <p className="mt-2 text-sm text-slate-500">
          첫 상세페이지를 만들면 이곳에서 결과, 검수, 출력 이력을 다시 확인할 수 있습니다.
        </p>
        <Link
          href="/workspace"
          className="mt-6 rounded-xl bg-emerald-600 px-5 py-2.5 text-sm font-bold text-white hover:bg-emerald-700"
        >
          첫 상세페이지 만들기
        </Link>
      </section>
    );
  }

  return (
    <div className="grid gap-4">
      {items.map((item) => (
        <article
          key={item.project_id}
          className="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm transition hover:border-emerald-200 hover:shadow-md"
        >
          <div className="flex flex-col gap-5 md:flex-row md:items-center md:justify-between">
            <div className="flex min-w-0 items-start gap-4">
              <div className="flex h-16 w-16 shrink-0 items-center justify-center overflow-hidden rounded-2xl bg-slate-100">
                {item.thumbnail_url ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={item.thumbnail_url} alt="" className="h-full w-full object-cover" />
                ) : (
                  <span className="text-xs font-bold text-slate-400">NO IMG</span>
                )}
              </div>
              <div className="min-w-0">
                <div className="mb-2 flex flex-wrap items-center gap-2">
                  {statusBadge(item.status)}
                  {item.last_export_status && (
                    <span className="rounded-full bg-slate-100 px-2.5 py-0.5 text-xs font-semibold text-slate-500">
                      최근 출력: {item.last_export_status}
                    </span>
                  )}
                </div>
                <h2 className="truncate text-lg font-extrabold text-slate-900">{item.project_name}</h2>
                <p className="mt-1 text-xs text-slate-500">마지막 수정: {formatDate(item.updated_at)}</p>
              </div>
            </div>

            <div className="flex flex-wrap gap-2 md:justify-end">
              {item.result_url && (
                <Link
                  href={item.result_url}
                  className="rounded-xl border border-slate-200 px-4 py-2 text-sm font-bold text-slate-700 hover:bg-slate-50"
                >
                  결과 보기
                </Link>
              )}
              {item.review_url && (
                <Link
                  href={item.review_url}
                  className="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-2 text-sm font-bold text-emerald-700 hover:bg-emerald-100"
                >
                  검수하며 다듬기
                </Link>
              )}
              <Link
                href={item.export_history_url}
                className="rounded-xl bg-slate-900 px-4 py-2 text-sm font-bold text-white hover:bg-slate-800"
              >
                출력 이력
              </Link>
            </div>
          </div>
        </article>
      ))}
    </div>
  );
}

"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { apiUrl } from "@/lib/api";
import type { ProjectWorklistItem, ProjectWorklistStatus } from "@/lib/projectWorklistCompat";

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

function resolveThumbnailUrl(url: string | null): string | null {
  if (!url) return null;
  if (/^(https?:|data:|blob:)/i.test(url)) return url;
  return apiUrl(url);
}

function ProjectThumbnail({ src, name }: { src: string | null; name: string }) {
  const [failed, setFailed] = useState(false);
  const thumbnailUrl = useMemo(() => resolveThumbnailUrl(src), [src]);

  if (!thumbnailUrl || failed) {
    return (
      <div className="flex h-20 w-20 shrink-0 items-center justify-center rounded-2xl bg-slate-100 text-xs font-extrabold text-slate-400">
        NO IMG
      </div>
    );
  }

  return (
    <div className="flex h-20 w-20 shrink-0 items-center justify-center overflow-hidden rounded-2xl border border-slate-100 bg-slate-100">
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={thumbnailUrl}
        alt={`${name} 썸네일`}
        className="h-full w-full object-cover"
        onError={() => setFailed(true)}
      />
    </div>
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
          <div className="grid gap-5 lg:grid-cols-[80px_minmax(0,1fr)_auto] lg:items-center">
            <div className="flex min-w-0 items-start gap-4 lg:contents">
              <ProjectThumbnail src={item.thumbnail_url} name={item.project_name} />
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

            <div className="flex flex-wrap gap-2 w-full lg:w-[320px] lg:justify-end">
              {item.status === "completed" && item.result_url && (
                <Link
                  href={item.result_url}
                  className="flex h-12 flex-1 items-center justify-center whitespace-nowrap rounded-xl border border-slate-200 px-4 text-sm font-bold text-slate-700 hover:bg-slate-50 lg:flex-initial"
                >
                  결과 보기
                </Link>
              )}
              {item.status === "needs_review" && item.review_url && (
                <Link
                  href={item.review_url}
                  className="flex h-12 flex-1 items-center justify-center whitespace-nowrap rounded-xl border border-emerald-200 bg-emerald-50 px-4 text-sm font-bold text-emerald-700 hover:bg-emerald-100 lg:flex-initial"
                >
                  검수하며 다듬기
                </Link>
              )}
              {item.status === "generating" && (
                <Link
                  href={item.run_id ? `/workspace?runId=${item.run_id}` : "/workspace"}
                  className="flex h-12 flex-1 items-center justify-center whitespace-nowrap rounded-xl border border-blue-200 bg-blue-50 px-4 text-sm font-bold text-blue-700 hover:bg-blue-100 lg:flex-initial"
                >
                  이어서 진행
                </Link>
              )}
              {item.status === "failed" && (
                <Link
                  href={`/workspace/operations?projectId=${item.project_id}`}
                  className="flex h-12 flex-1 items-center justify-center whitespace-nowrap rounded-xl border border-rose-200 bg-rose-50 px-4 text-sm font-bold text-rose-700 hover:bg-rose-100 lg:flex-initial"
                >
                  상태 확인
                </Link>
              )}
              <Link
                href={item.export_history_url}
                className="flex h-12 flex-1 items-center justify-center whitespace-nowrap rounded-xl bg-slate-900 px-4 text-sm font-bold text-white hover:bg-slate-800 lg:flex-initial"
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

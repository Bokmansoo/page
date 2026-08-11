"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { apiUrl, sessionFetch } from "@/lib/api";

type SessionInfo = {
  user: { id: string; email: string; name: string };
  workspace: { id: string; name: string };
  role: string;
};

export default function WorkspaceLayout({ children }: { children: React.ReactNode }) {
  const [session, setSession] = useState<SessionInfo | null>(null);

  useEffect(() => {
    sessionFetch(apiUrl("/api/v1/auth/session"))
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => setSession(data))
      .catch(() => setSession(null));
  }, []);

  const logout = async () => {
    const csrf = document.cookie.split("; ").find((row) => row.startsWith("sellform_csrf="))?.split("=")[1];
    await sessionFetch(apiUrl("/api/v1/auth/logout"), {
      method: "POST",
      headers: csrf ? { "X-CSRF-Token": decodeURIComponent(csrf) } : {},
    });
    setSession(null);
  };

  return (
    <div className="min-h-screen bg-slate-50 text-slate-800">
      <header className="sticky top-0 z-30 flex w-full items-center justify-between border-b border-slate-200 bg-white px-6 py-4">
        <div className="flex items-center gap-8">
          <Link href="/workspace" className="flex items-center gap-2.5">
            <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-emerald-500 font-bold text-white">S</span>
            <span className="text-lg font-bold text-slate-900">Sellform</span>
          </Link>
          <nav className="flex gap-6 text-sm font-medium text-slate-600">
            <Link href="/workspace" className="hover:text-emerald-700">AI 상세페이지 생성</Link>
            <Link href="/workspace/projects" className="hover:text-emerald-700">작업 목록</Link>
            <Link href="/workspace/exports" className="hover:text-emerald-700">출력 이력</Link>
            <Link href="/account" className="hover:text-emerald-700">계정</Link>
          </nav>
        </div>
        <div className="flex items-center gap-3 text-xs text-slate-600">
          {session ? (
            <>
              <span>{session.workspace.name} · {session.user.name}</span>
              <button onClick={logout} className="rounded border border-slate-300 px-2 py-1 hover:bg-slate-50">로그아웃</button>
            </>
          ) : (
            <Link href="/login" className="rounded border border-emerald-600 px-3 py-1.5 font-semibold text-emerald-700 hover:bg-emerald-50">로그인</Link>
          )}
        </div>
      </header>
      <main>{children}</main>
    </div>
  );
}

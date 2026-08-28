"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { apiUrl, sessionFetch } from "@/lib/api";

type Provider = { provider: "google" | "kakao" | "naver" | "development"; display_name?: string | null; linked_at?: string };
type SessionItem = { id: string; current: boolean; user_agent?: string | null; ip_address?: string | null; created_at?: string };
type AccountData = { user: { name: string; email: string }; providers: Provider[]; workspaces: { id: string; name: string; role: string }[] };

const providerName: Record<string, string> = { google: "Google", kakao: "카카오", naver: "네이버", development: "개발용 계정" };

function csrfHeaders() {
  const token = document.cookie.split("; ").find((item) => item.startsWith("sellform_csrf="))?.split("=")[1];
  return token ? { "X-CSRF-Token": decodeURIComponent(token) } : {};
}

export default function AccountPage() {
  const [account, setAccount] = useState<AccountData | null>(null);
  const [sessions, setSessions] = useState<SessionItem[]>([]);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState("");

  const load = async () => {
    const [accountResponse, sessionsResponse] = await Promise.all([sessionFetch(apiUrl("/api/v1/auth/account")), sessionFetch(apiUrl("/api/v1/auth/sessions"))]);
    if (!accountResponse.ok) throw new Error("계정 정보를 불러오지 못했습니다.");
    setAccount(await accountResponse.json());
    if (sessionsResponse.ok) setSessions((await sessionsResponse.json()).sessions ?? []);
  };

  useEffect(() => { load().catch((error: Error) => setMessage(error.message)); }, []);

  const request = async (path: string, options: RequestInit = {}) => {
    const headers = new Headers();
    Object.entries(csrfHeaders()).forEach(([key, value]) => {
      if (typeof value === "string") {
        headers.set(key, value);
      }
    });
    new Headers(options.headers).forEach((value, key) => {
      headers.set(key, value);
    });
    const response = await sessionFetch(apiUrl(path), { ...options, headers });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail ?? "요청을 처리하지 못했습니다.");
    return data;
  };

  const linkProvider = async (provider: "google" | "kakao" | "naver") => {
    try {
      setBusy(provider);
      const data = await request(`/api/v1/auth/link/${provider}?redirect_path=/account`);
      if (!data.authorization_url) throw new Error("연결 주소를 만들지 못했습니다.");
      window.location.assign(data.authorization_url);
    } catch (error) { setMessage(error instanceof Error ? error.message : "계정을 연결하지 못했습니다."); setBusy(""); }
  };

  const unlink = async (provider: string) => {
    if (!window.confirm(`${providerName[provider]} 연결을 해제할까요?`)) return;
    try { setBusy(provider); await request(`/api/v1/auth/accounts/${provider}`, { method: "DELETE" }); await load(); }
    catch (error) { setMessage(error instanceof Error ? error.message : "연결을 해제하지 못했습니다."); }
    finally { setBusy(""); }
  };

  const revoke = async (id: string) => {
    try { setBusy(id); await request(`/api/v1/auth/sessions/${id}`, { method: "DELETE" }); await load(); }
    catch (error) { setMessage(error instanceof Error ? error.message : "기기를 로그아웃하지 못했습니다."); }
    finally { setBusy(""); }
  };

  const withdraw = async () => {
    if (window.prompt("계정 탈퇴를 진행하려면 DELETE를 입력해 주세요.") !== "DELETE") return;
    try { setBusy("withdraw"); await request("/api/v1/auth/account", { method: "DELETE", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ confirmation: "DELETE" }) }); window.location.assign("/login"); }
    catch (error) { setMessage(error instanceof Error ? error.message : "계정 탈퇴를 진행하지 못했습니다."); setBusy(""); }
  };

  if (!account && !message) return <main className="p-10 text-center text-slate-500">계정 정보를 불러오는 중…</main>;
  if (!account) return <main className="p-10 text-center"><p className="text-red-700">{message}</p><Link href="/login" className="mt-4 inline-block text-emerald-700">로그인으로 이동</Link></main>;

  const linked = new Set(account.providers.map((provider) => provider.provider));
  return <main className="mx-auto max-w-3xl p-6 sm:p-10">
    <div className="mb-8 flex items-start justify-between gap-4"><div><p className="text-sm font-bold text-emerald-700">ACCOUNT & SECURITY</p><h1 className="mt-1 text-3xl font-bold text-slate-900">계정 및 보안</h1><p className="mt-2 text-sm text-slate-600">로그인 수단과 접속 중인 기기를 관리합니다.</p></div><Link href="/workspace" className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold">작업으로 돌아가기</Link></div>
    {message && <p className="mb-5 rounded-xl bg-red-50 p-4 text-sm text-red-700">{message}</p>}
    <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm"><h2 className="font-bold text-slate-900">내 계정</h2><p className="mt-3 text-lg font-semibold">{account.user.name}</p><p className="text-sm text-slate-500">{account.user.email}</p><div className="mt-5 flex flex-wrap gap-2">{account.workspaces.map((workspace) => <span key={workspace.id} className="rounded-full bg-emerald-50 px-3 py-1 text-xs font-semibold text-emerald-800">{workspace.name} · {workspace.role}</span>)}</div></section>
    <section className="mt-5 rounded-2xl border border-slate-200 bg-white p-6 shadow-sm"><h2 className="font-bold text-slate-900">연결된 로그인 수단</h2><p className="mt-1 text-sm text-slate-500">마지막 로그인 수단은 안전을 위해 해제할 수 없습니다.</p><div className="mt-5 space-y-3">{account.providers.map((provider) => <div key={provider.provider} className="flex items-center justify-between rounded-xl bg-slate-50 p-4"><span className="font-semibold">{providerName[provider.provider] ?? provider.provider}</span>{provider.provider !== "development" && <button disabled={busy === provider.provider} onClick={() => unlink(provider.provider)} className="text-sm font-semibold text-red-600 disabled:opacity-40">연결 해제</button>}</div>)}</div><div className="mt-5 grid grid-cols-1 gap-2 sm:grid-cols-3">{(["google", "kakao", "naver"] as const).filter((provider) => !linked.has(provider)).map((provider) => <button key={provider} disabled={busy !== ""} onClick={() => linkProvider(provider)} className="rounded-xl border border-slate-300 px-3 py-3 text-sm font-semibold hover:bg-slate-50 disabled:opacity-50">{providerName[provider]} 연결</button>)}</div></section>
    <section className="mt-5 rounded-2xl border border-slate-200 bg-white p-6 shadow-sm"><div className="flex items-center justify-between"><div><h2 className="font-bold text-slate-900">로그인된 기기</h2><p className="mt-1 text-sm text-slate-500">모르는 기기가 있으면 즉시 로그아웃하세요.</p></div><button disabled={busy !== ""} onClick={() => request("/api/v1/auth/logout-all", { method: "POST" }).then(() => window.location.assign("/login")).catch((error: Error) => setMessage(error.message))} className="text-sm font-semibold text-red-600">전체 로그아웃</button></div><div className="mt-4 space-y-2">{sessions.map((session) => <div key={session.id} className="flex items-center justify-between rounded-xl border border-slate-100 p-3 text-sm"><span>{session.current ? "현재 기기" : session.user_agent || "알 수 없는 기기"}</span>{!session.current && <button disabled={busy !== ""} onClick={() => revoke(session.id)} className="font-semibold text-red-600">로그아웃</button>}</div>)}</div></section>
    <section className="mt-5 rounded-2xl border border-red-100 bg-red-50 p-6"><h2 className="font-bold text-red-900">계정 탈퇴</h2><p className="mt-1 text-sm text-red-800">모든 로그인 수단과 기기 세션이 해제됩니다. 프로젝트 이력은 감사 기록으로 비식별 보관됩니다.</p><button disabled={busy !== "" || linked.has("development")} onClick={withdraw} className="mt-4 rounded-lg border border-red-300 px-3 py-2 text-sm font-semibold text-red-700 disabled:cursor-not-allowed disabled:opacity-40">{busy === "withdraw" ? "처리 중…" : "계정 탈퇴"}</button>{linked.has("development") && <p className="mt-2 text-xs text-red-700">개발용 계정은 로컬 검증을 위해 탈퇴할 수 없습니다.</p>}</section>
  </main>;
}

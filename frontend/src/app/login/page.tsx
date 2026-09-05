"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { apiUrl, sessionFetch } from "@/lib/api";

type ProviderName = "google" | "kakao" | "naver";

type Provider = {
  provider: ProviderName;
  configured: boolean;
  display_name?: string;
};

const providerCopy: Record<ProviderName, string> = {
  google: "Google로 계속하기",
  kakao: "카카오로 계속하기",
  naver: "네이버로 계속하기",
};

function ProviderLogo({ provider }: { provider: ProviderName }) {
  if (provider === "google") {
    return (
      <svg aria-hidden="true" viewBox="0 0 48 48" className="h-6 w-6">
        <path fill="#FFC107" d="M43.6 20H42V20H24v8h11.3C33.6 32.7 29.2 36 24 36c-6.6 0-12-5.4-12-12s5.4-12 12-12c3 0 5.7 1.1 7.8 3l5.7-5.7C34 6.1 29.2 4 24 4 13 4 4 13 4 24s9 20 20 20 20-9 20-20c0-1.3-.1-2.7-.4-4z" />
        <path fill="#FF3D00" d="M6.3 14.7l6.6 4.8C14.7 15.1 19 12 24 12c3 0 5.7 1.1 7.8 3l5.7-5.7C34 6.1 29.2 4 24 4c-7.7 0-14.3 4.4-17.7 10.7z" />
        <path fill="#4CAF50" d="M24 44c5.1 0 9.8-1.9 13.4-5l-6.2-5.2C29.2 35.2 26.7 36 24 36c-5.2 0-9.6-3.3-11.3-8l-6.6 5.1C9.5 39.5 16.2 44 24 44z" />
        <path fill="#1976D2" d="M43.6 20H42V20H24v8h11.3c-.8 2.2-2.2 4.1-4.1 5.8l.1-.1 6.2 5.2C37.1 39.2 44 34 44 24c0-1.3-.1-2.7-.4-4z" />
      </svg>
    );
  }

  if (provider === "kakao") {
    return (
      <span aria-hidden="true" className="flex h-6 w-6 items-center justify-center rounded-full bg-[#FEE500]">
        <svg viewBox="0 0 48 48" className="h-[17px] w-[17px] fill-[#191600]">
          <path d="M24 8C14.1 8 6 14.3 6 22.2c0 5.1 3.3 9.6 8.2 12.1l-1.9 7.1c-.1.5.4.9.8.6l8.3-5.4c.9.1 1.8.2 2.6.2 9.9 0 18-6.3 18-14.2S33.9 8 24 8Zm-6.4 16.8a2.3 2.3 0 1 1 0-4.6 2.3 2.3 0 0 1 0 4.6Zm6.4 0a2.3 2.3 0 1 1 0-4.6 2.3 2.3 0 0 1 0 4.6Zm6.4 0a2.3 2.3 0 1 1 0-4.6 2.3 2.3 0 0 1 0 4.6Z" />
        </svg>
      </span>
    );
  }

  return (
    <span aria-hidden="true" className="flex h-6 w-6 items-center justify-center rounded-[5px] bg-[#03C75A] text-[15px] font-black leading-none text-white">N</span>
  );
}

export default function LoginPage() {
  const [providers, setProviders] = useState<Provider[]>([]);
  const [developmentMode, setDevelopmentMode] = useState(false);
  const [message, setMessage] = useState("");
  const [pending, setPending] = useState<string | null>(null);

  useEffect(() => {
    sessionFetch(apiUrl("/api/v1/auth/providers"))
      .then(async (response) => {
        if (!response.ok) throw new Error("로그인 설정을 불러오지 못했습니다.");
        return response.json();
      })
      .then((data) => {
        setProviders(data.providers ?? []);
        setDevelopmentMode(Boolean(data.development_mode));
      })
      .catch((error: Error) => setMessage(error.message));
  }, []);

  const startLogin = async (provider: ProviderName) => {
    setPending(provider);
    setMessage("");
    try {
      const response = await sessionFetch(apiUrl(`/api/v1/auth/login/${provider}?redirect_path=/workspace`));
      const data = await response.json();
      if (!response.ok || !data.authorization_url) throw new Error(data.detail ?? "로그인을 시작하지 못했습니다.");
      window.location.assign(data.authorization_url);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "로그인을 시작하지 못했습니다.");
      setPending(null);
    }
  };

  const startDevelopmentLogin = async () => {
    setPending("development");
    setMessage("");
    try {
      const response = await sessionFetch(apiUrl("/api/v1/auth/development-login"), { method: "POST" });
      if (!response.ok) throw new Error("개발용 로그인을 시작하지 못했습니다.");
      window.location.assign("/workspace");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "개발용 로그인을 시작하지 못했습니다.");
      setPending(null);
    }
  };

  return (
    <main className="relative flex min-h-screen overflow-hidden bg-[#080b1d] text-slate-950">
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_12%_18%,rgba(16,185,129,0.22),transparent_27%),radial-gradient(circle_at_84%_76%,rgba(124,58,237,0.24),transparent_29%)]" />
      <div className="relative mx-auto flex w-full max-w-6xl items-center justify-center px-5 py-10 lg:grid lg:grid-cols-[1fr_460px] lg:gap-16">
        <section className="mb-10 hidden max-w-lg text-white lg:block">
          <Link href="/" className="inline-flex items-center gap-3 text-xl font-bold">
            <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-emerald-400 text-xl text-slate-950 shadow-lg shadow-emerald-400/20">S</span>
            Sellform
          </Link>
          <p className="mt-16 text-sm font-semibold tracking-[0.2em] text-emerald-300">SELL SMARTER</p>
          <h1 className="mt-4 text-5xl font-bold leading-tight tracking-tight">상품을 고르고,<br />판매 페이지를 완성하세요.</h1>
          <p className="mt-6 max-w-md text-base leading-7 text-slate-300">공급처 자료는 참고로만, 판매용 콘텐츠는 나만의 구성으로. Sellform이 검토 가능한 상세페이지 제작 흐름을 정리합니다.</p>
          <div className="mt-10 grid grid-cols-3 gap-3 text-sm">
            {["소셜 계정 보호", "워크스페이스 분리", "기기별 세션 관리"].map((item, index) => (
              <div key={item} className="rounded-2xl border border-white/10 bg-white/5 p-4 backdrop-blur"><span className="text-emerald-300">0{index + 1}</span><p className="mt-2 text-slate-200">{item}</p></div>
            ))}
          </div>
        </section>

        <section className="w-full max-w-[460px] overflow-hidden rounded-[28px] border border-white/20 bg-white shadow-2xl shadow-black/30">
          <div className="p-7 sm:p-10">
            <Link href="/" className="mx-auto flex w-fit items-center gap-2.5 text-xl font-bold text-slate-900">
              <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-emerald-500 font-bold text-white">S</span>
              Sellform
            </Link>
            <div className="mt-8 text-center">
              <h2 className="text-2xl font-bold tracking-tight text-slate-900">Sellform에 로그인</h2>
              <p className="mt-2 text-sm leading-6 text-slate-500">소셜 계정으로 안전하게 시작하세요.<br />같은 이메일이어도 연결한 계정은 자동으로 합치지 않습니다.</p>
            </div>

            <div className="mt-8 space-y-3">
              {providers.map((provider) => {
                const isPending = pending === provider.provider;
                return (
                  <button key={provider.provider} type="button" disabled={!provider.configured || pending !== null} onClick={() => startLogin(provider.provider)} className="flex w-full items-center gap-3 rounded-xl border border-slate-200 px-4 py-3.5 text-sm font-semibold text-slate-700 shadow-sm transition hover:-translate-y-0.5 hover:border-slate-300 hover:bg-slate-50 disabled:cursor-not-allowed disabled:bg-slate-50 disabled:text-slate-400">
                    <ProviderLogo provider={provider.provider} />
                    <span className="flex-1 text-left">{isPending ? "로그인 페이지로 이동 중…" : providerCopy[provider.provider]}</span>
                    {!provider.configured && <span className="text-[11px] font-medium text-slate-400">준비 중</span>}
                  </button>
                );
              })}
            </div>

            <div className="my-7 flex items-center gap-3 text-xs text-slate-400"><span className="h-px flex-1 bg-slate-200" />간편하고 안전한 로그인<span className="h-px flex-1 bg-slate-200" /></div>
            <p className="text-center text-xs leading-5 text-slate-500">Google · Kakao · NAVER 중 원하는 계정으로 시작할 수 있습니다. 실제 로그인은 각 제공자의 앱 키가 등록된 뒤 활성화됩니다.</p>

            {developmentMode && (
              <div className="mt-7 rounded-2xl border border-amber-200 bg-amber-50 p-4">
                <p className="text-sm font-bold text-amber-950">개발 환경</p>
                <p className="mt-1 text-xs leading-5 text-amber-800">로컬 검증용 계정입니다. 실제 서비스에서는 이 버튼이 표시되지 않습니다.</p>
                <button type="button" disabled={pending !== null} onClick={startDevelopmentLogin} className="mt-3 w-full rounded-xl bg-slate-900 py-3 text-sm font-semibold text-white transition hover:bg-slate-700 disabled:opacity-60">{pending === "development" ? "로그인 중…" : "개발용으로 계속하기"}</button>
              </div>
            )}
            {message && <p role="alert" className="mt-5 rounded-xl bg-red-50 p-3 text-center text-sm text-red-700">{message}</p>}
          </div>
          <footer className="border-t border-slate-100 bg-slate-50 px-7 py-4 text-center text-xs text-slate-500">계속하면 Sellform의 서비스 이용 약관 및 개인정보 처리방침에 동의하게 됩니다.</footer>
        </section>
      </div>
    </main>
  );
}

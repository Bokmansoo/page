"use client";

import * as Sentry from "@sentry/nextjs";
import { useEffect } from "react";
import { initializeClientObservability } from "../components/ObservabilityProvider";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    initializeClientObservability();
    Sentry.captureException(error, {
      tags: { surface: "next_global_error" },
    });
  }, [error]);

  return (
    <html lang="ko">
      <body>
        <main className="mx-auto flex min-h-screen max-w-lg flex-col items-center justify-center gap-4 px-6 text-center text-slate-900">
          <h1 className="text-xl font-bold">페이지를 불러오지 못했습니다.</h1>
          <p className="text-sm text-slate-600">잠시 후 다시 시도해 주세요.</p>
          <button
            type="button"
            className="rounded bg-emerald-600 px-4 py-2 text-sm font-semibold text-white"
            onClick={reset}
          >
            다시 시도
          </button>
        </main>
      </body>
    </html>
  );
}

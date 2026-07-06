import { Suspense } from "react";
import DetailPageRenderClient from "@/app/workspace/projects/[id]/render/DetailPageRenderClient";

export default function ExportRenderPage() {
  return (
    <main data-export-render-shell="true">
      <Suspense
        fallback={
          <main className="flex min-h-screen items-center justify-center p-8 text-sm text-slate-500">
            상세페이지 로딩 중...
          </main>
        }
      >
        <DetailPageRenderClient />
      </Suspense>
    </main>
  );
}

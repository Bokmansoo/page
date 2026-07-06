import { Suspense } from "react";
import DetailPageRenderClient from "./DetailPageRenderClient";

export default function DetailPageRenderRoute() {
  return (
    <Suspense fallback={<main className="p-8 text-sm text-slate-500">Loading final detail page...</main>}>
      <DetailPageRenderClient />
    </Suspense>
  );
}

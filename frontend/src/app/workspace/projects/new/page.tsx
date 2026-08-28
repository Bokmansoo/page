import { Suspense } from "react";
import { UnifiedProductIntakePanel } from "@/components/intake/UnifiedProductIntakePanel";

export default function NewProjectPage() {
  return <Suspense fallback={<main className="mx-auto max-w-4xl px-4 py-8 text-sm text-slate-600">상품 입력 화면을 준비하고 있습니다.</main>}><UnifiedProductIntakePanel /></Suspense>;
}

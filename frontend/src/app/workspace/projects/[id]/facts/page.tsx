import Link from "next/link";
import FactEvidenceBoard from "@/components/FactEvidenceBoard";

export default async function FactEvidencePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <main className="mx-auto max-w-5xl p-6"><div className="mb-5 flex items-center justify-between"><h1 className="text-2xl font-bold">상품 사실·증거 확인</h1><Link className="text-sm font-semibold text-emerald-700" href={`/workspace/projects/${id}/result`}>상세페이지로 돌아가기</Link></div><FactEvidenceBoard projectId={id} /></main>;
}

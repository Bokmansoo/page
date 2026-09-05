"use client";

import { useCallback, useEffect, useState } from "react";
import { apiUrl } from "@/lib/api";

type Ref = { id: string; version: number; hash: string };
type Card = {
  card_id: string;
  role: string;
  order: number;
  status: string;
  selected_variant_ref?: Ref;
  variant_refs?: Ref[];
  preview_url?: string;
  actions: string[];
  copy_ref?: Ref;
  copy_text?: string;
  copy_validation?: string;
};
type KitResponse = { run_id?: string | null; kit: { id: string; version: number; status: string; cards: Card[]; quality?: { verdict?: string; review_required?: boolean }; publishing_profile?: { platform: string; format: string; width: number; height: number; aspect_ratio: string; readiness: string }; platform_quality?: { verdict?: string; card_count?: number; reasons?: string[] } } };

const roleLabels: Record<string, string> = {
  hero: "주요 소개",
  benefit: "핵심 장점",
  feature: "주요 특징",
  usage: "사용 장면",
  cta: "구매 유도",
};

export default function SocialKitPanel({ projectId }: { projectId: string }) {
  const [data, setData] = useState<KitResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [copyText, setCopyText] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const response = await fetch(apiUrl(`/api/v1/projects/${projectId}/social-kit`), { credentials: "include", cache: "no-store" });
      if (!response.ok) throw new Error("소셜 카드 세트를 불러오지 못했습니다.");
      setData(await response.json() as KitResponse);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "소셜 카드 세트를 불러오지 못했습니다.");
    } finally { setLoading(false); }
  }, [projectId]);

  useEffect(() => { void load(); }, [load]);

  const action = async (card: Card, kind: string, extra: Record<string, unknown> = {}) => {
    if (!data?.run_id) return;
    setWorking(`${kind}:${card.card_id}`);
    setMessage(null);
    try {
      const response = await fetch(apiUrl(`/api/v1/projects/${projectId}/social-kit/actions`), {
        method: "POST", credentials: "include", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ run_id: data.run_id, action: kind, parent_social_kit_ref: { id: data.kit.id, version: data.kit.version }, card_id: card.card_id, variant_key: "alternative-1", ...extra }),
      });
      const payload = await response.json().catch(() => null);
      if (!response.ok) throw new Error(payload?.detail?.message || payload?.detail || "카드 작업을 처리하지 못했습니다.");
      setData(payload as KitResponse);
      setMessage("변경 사항을 저장했습니다.");
    } catch (error) { setMessage(error instanceof Error ? error.message : "카드 작업을 처리하지 못했습니다."); }
    finally { setWorking(null); }
  };

  const beginCopyEdit = (card: Card) => {
    setEditing(card.card_id);
    setCopyText(card.copy_text || "");
    setMessage(null);
  };

  if (loading) return <div className="mx-auto max-w-6xl p-6" aria-busy="true">소셜 카드 세트를 불러오는 중입니다…</div>;
  if (!data) return <div className="mx-auto max-w-6xl p-6"><p role="alert">{message || "소셜 카드 세트를 찾을 수 없습니다."}</p></div>;
  const cards = data.kit.cards;
  const move = (index: number, direction: -1 | 1) => {
    const next = [...cards].sort((a, b) => a.order - b.order);
    const target = index + direction;
    if (target < 0 || target >= next.length || !data.run_id) return;
    [next[index], next[target]] = [next[target], next[index]];
    void action(next[index], "reorder", { ordered_card_ids: next.map((card) => card.card_id) });
  };

  return (
    <div className="mx-auto max-w-6xl space-y-6 p-6 text-slate-900 sm:p-8">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div><p className="text-sm font-semibold text-emerald-700">Social Creative Kit</p><h1 id="social-kit-title" className="text-3xl font-black tracking-tight">소셜 카드 세트</h1><p className="mt-2 text-sm text-slate-600">완성된 카드만 미리보고, 필요한 카드만 다시 작업할 수 있습니다.</p></div>
        <div className="flex flex-wrap gap-2"><a className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold" href={apiUrl(`/api/v1/projects/${projectId}/social-kit/export/png`)}>PNG 다운로드</a><a className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold" href={apiUrl(`/api/v1/projects/${projectId}/social-kit/export/jpg`)}>JPG 다운로드</a><a className="rounded-lg bg-slate-900 px-3 py-2 text-sm font-semibold text-white" href={apiUrl(`/api/v1/projects/${projectId}/social-kit/export/zip`)}>ZIP 다운로드</a></div>
      </header>
      {data.kit.publishing_profile && <section className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm" aria-label="Publishing profile"><div className="font-semibold">Instagram Feed · {data.kit.publishing_profile.aspect_ratio} · {data.kit.publishing_profile.width}x{data.kit.publishing_profile.height}</div><div className="text-slate-600">{data.kit.publishing_profile.readiness === "ready" ? "Publishing ready" : "Review required"}</div></section>}
      {message && <p role="status" className="rounded-lg bg-emerald-50 px-4 py-3 text-sm text-emerald-800">{message}</p>}
      <section className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3" aria-label="소셜 카드 목록">
        {cards.slice().sort((a, b) => a.order - b.order).map((card, index) => (
          <article key={card.card_id} className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
            <div className="aspect-video bg-slate-100">{card.preview_url ? <img src={apiUrl(card.preview_url)} alt={`${roleLabels[card.role] || "소셜 카드"} 미리보기`} className="h-full w-full object-cover" /> : <div className="flex h-full items-center justify-center text-sm text-slate-600">미리보기 준비 중</div>}</div>
            <div className="space-y-3 p-4"><div className="flex items-center justify-between"><h2 className="font-bold">{roleLabels[card.role] || "소셜 카드"}</h2><span className="text-xs text-slate-500">{card.status === "rendered" ? "완료" : "준비 중"}</span></div>
              <p className="rounded-md bg-slate-50 p-2 text-sm" data-testid={`social-copy-${card.card_id}`}>{card.copy_text}</p>
              {editing === card.card_id && <div className="space-y-2"><label className="sr-only" htmlFor={`social-copy-input-${card.card_id}`}>카드 문구</label><textarea id={`social-copy-input-${card.card_id}`} value={copyText} onChange={(event) => setCopyText(event.target.value)} maxLength={2000} className="min-h-20 w-full rounded-md border p-2 text-sm" /><div className="flex gap-2"><button type="button" disabled={Boolean(working)} onClick={() => { void action(card, "edit_copy", { copy_reference: card.copy_ref, proposed_text: copyText }); setEditing(null); }} className="rounded-md bg-emerald-700 px-2 py-1 text-xs font-semibold text-white">저장</button><button type="button" onClick={() => setEditing(null)} className="rounded-md border px-2 py-1 text-xs font-semibold">취소</button></div></div>}
              {card.status === "rendered" && <div className="flex gap-2 text-xs"><a className="font-semibold text-emerald-700 underline" href={apiUrl(`/api/v1/projects/${projectId}/social-kit/export/png?card_id=${encodeURIComponent(card.card_id)}`)}>PNG</a><a className="font-semibold text-emerald-700 underline" href={apiUrl(`/api/v1/projects/${projectId}/social-kit/export/jpg?card_id=${encodeURIComponent(card.card_id)}`)}>JPG</a></div>}
              <div className="flex flex-wrap gap-2" role="group" aria-label={`${roleLabels[card.role] || card.role} 작업`}>
                <button type="button" disabled={Boolean(working)} onClick={() => move(index, -1)} className="rounded-md border px-2 py-1 text-xs font-semibold disabled:opacity-40" aria-label={`${roleLabels[card.role] || "카드"} 위로 이동`}>위로</button>
                <button type="button" disabled={Boolean(working)} onClick={() => move(index, 1)} className="rounded-md border px-2 py-1 text-xs font-semibold disabled:opacity-40" aria-label={`${roleLabels[card.role] || "카드"} 아래로 이동`}>아래로</button>
                {card.actions.includes("delete") && <button type="button" disabled={Boolean(working)} onClick={() => void action(card, "delete")} className="rounded-md border border-rose-200 px-2 py-1 text-xs font-semibold text-rose-700 disabled:opacity-40">삭제</button>}
                <button type="button" disabled={Boolean(working)} onClick={() => void action(card, "regenerate")} className="rounded-md bg-emerald-700 px-2 py-1 text-xs font-semibold text-white disabled:opacity-40">다시 만들기</button>
                <button type="button" disabled={Boolean(working)} onClick={() => void action(card, "request_alternative")} className="rounded-md border border-emerald-300 px-2 py-1 text-xs font-semibold text-emerald-800 disabled:opacity-40">대안 요청</button>
                {card.variant_refs?.[0] && <button type="button" disabled={Boolean(working)} onClick={() => void action(card, "select_alternative", { variant_ref: card.variant_refs?.[0] })} className="rounded-md border px-2 py-1 text-xs font-semibold disabled:opacity-40">대안 선택</button>}
                {card.actions.includes("edit_copy") && editing !== card.card_id && <button type="button" disabled={Boolean(working)} onClick={() => beginCopyEdit(card)} className="rounded-md border border-emerald-300 px-2 py-1 text-xs font-semibold text-emerald-800 disabled:opacity-40">문구 수정</button>}
              </div>
            </div>
          </article>
        ))}
      </section>
    </div>
  );
}

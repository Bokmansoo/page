"use client";

import { useCallback, useEffect, useState } from "react";
import { apiUrl, sessionFetch } from "@/lib/api";

type Scene = { scene_id: string; order: number; title: string; role: string; status: string; generation_status: string; text_ready: boolean };
type TextLayer = { id: string; scene_id: string; text_role: string; placement_role: string; text: string | null; validation_status: string };
type Metadata = { id: string; version: number; platform: string; title?: string | null; caption?: string | null; description?: string | null; hashtags: string[]; cta?: string | null; validation_status: string };
type VideoData = { id: string; version: number; scene_count: number; scenes: Scene[]; progress: { completed_count: number; total_count: number; percent: number }; current_stage: string; status: { label: string; quality: string }; assembly: { ready: boolean; duration_seconds?: number | null; quality: string }; download_available: boolean; texts: TextLayer[]; metadata: Metadata[]; actions: string[] };
type Response = { run_id: string; video: VideoData };

const platformLabels: Record<string, string> = { reels: "Instagram Reels", tiktok: "TikTok", youtube_shorts: "YouTube Shorts" };

export default function VideoStudioPanel({ projectId }: { projectId: string }) {
  const [data, setData] = useState<Response | null>(null);
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [textDraft, setTextDraft] = useState("");
  const [textScene, setTextScene] = useState("");
  const [metadata, setMetadata] = useState<Record<string, { title: string; caption: string; description: string; hashtags: string; cta: string }>>({});

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const response = await sessionFetch(apiUrl(`/api/v1/projects/${projectId}/video`), { cache: "no-store" });
      const payload = await response.json().catch(() => null);
      if (!response.ok) throw new Error(payload?.detail?.message || payload?.detail || "영상 상태를 불러오지 못했습니다.");
      setData(payload as Response);
      setMessage(null);
    } catch (error) { setMessage(error instanceof Error ? error.message : "영상 상태를 불러오지 못했습니다."); }
    finally { setLoading(false); }
  }, [projectId]);

  useEffect(() => { void load(); }, [load]);

  const action = async (body: Record<string, unknown>, key: string) => {
    if (!data) return;
    setWorking(key); setMessage(null);
    try {
      const response = await sessionFetch(apiUrl(`/api/v1/projects/${projectId}/video/actions`), { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ run_id: data.run_id, parent_video_project_ref: { id: data.video.id, version: data.video.version }, ...body }) });
      const payload = await response.json().catch(() => null);
      if (!response.ok) throw new Error(payload?.detail?.message || payload?.detail || "영상 작업을 완료하지 못했습니다.");
      setData(payload as Response); setMessage("변경 사항을 저장했습니다.");
    } catch (error) { setMessage(error instanceof Error ? error.message : "영상 작업을 완료하지 못했습니다."); if (String(error).includes("변경")) void load(); }
    finally { setWorking(null); }
  };

  if (loading) return <main className="mx-auto max-w-6xl p-6" aria-busy="true">영상 스튜디오를 준비하고 있습니다.</main>;
  if (!data) return <main className="mx-auto max-w-6xl p-6"><p role="alert">{message || "영상 프로젝트를 찾을 수 없습니다."}</p></main>;
  const video = data.video;
  const sortedScenes = [...video.scenes].sort((a, b) => a.order - b.order);

  const move = (index: number, direction: -1 | 1) => {
    const next = [...sortedScenes];
    [next[index], next[index + direction]] = [next[index + direction], next[index]];
    void action({ action: "reorder", ordered_scene_ids: next.map((item) => item.scene_id) }, `move-${sortedScenes[index].scene_id}`);
  };

  return (
    <main className="mx-auto max-w-6xl space-y-6 p-4 text-slate-900 sm:p-8" aria-labelledby="video-studio-title">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div><p className="text-sm font-semibold text-emerald-700">Video Studio</p><h1 id="video-studio-title" className="text-3xl font-black tracking-tight">공통 영상 스튜디오</h1><p className="mt-2 text-sm text-slate-600">완성된 장면을 확인하고 플랫폼별 게시 정보를 준비하세요.</p></div>
        {video.download_available && <a className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white" href={apiUrl(`/api/v1/projects/${projectId}/video/download`)}>최종 영상 다운로드</a>}
      </header>
      {message && <p role="status" aria-live="polite" className="rounded-lg bg-emerald-50 px-4 py-3 text-sm text-emerald-800">{message}</p>}
      <section className="grid gap-5 lg:grid-cols-[1.2fr_1fr]">
        <div className="space-y-5">
          <article className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
            <div className="aspect-video bg-slate-950">{video.download_available ? <video className="h-full w-full" controls preload="metadata" src={apiUrl(`/api/v1/projects/${projectId}/video/download`)} aria-label="최종 공통 영상" /> : <div className="flex h-full items-center justify-center text-sm text-slate-300">영상이 준비되면 미리 볼 수 있습니다.</div>}</div>
            <div className="space-y-3 p-4"><div className="flex items-center justify-between"><h2 className="font-bold">현재 영상</h2><span className="text-sm text-slate-600">{video.status.label}</span></div><div className="h-2 rounded-full bg-slate-100" aria-label="영상 진행률"><div className="h-2 rounded-full bg-emerald-600" style={{ width: `${video.progress.percent}%` }} /></div><p className="text-sm text-slate-600">{video.progress.completed_count}/{video.progress.total_count} 장면 완료 · {video.current_stage}</p><p className="text-sm">품질 상태: <span className="font-semibold">{video.status.quality}</span></p></div>
          </article>
          <section aria-labelledby="scene-title" className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm"><div className="mb-3 flex items-center justify-between"><h2 id="scene-title" className="font-bold">장면 목록</h2><span className="text-sm text-slate-500">순서 변경은 저장 즉시 반영됩니다.</span></div><ol className="space-y-2">{sortedScenes.map((scene, index) => <li key={scene.scene_id} className="flex flex-wrap items-center gap-3 rounded-lg border border-slate-100 p-3"><span className="w-6 text-sm font-bold text-slate-500">{index + 1}</span><div className="min-w-0 flex-1"><p className="font-semibold">{scene.title}</p><p className="text-xs text-slate-500">{scene.status}{scene.text_ready ? " · 문구 준비됨" : " · 문구 준비 중"}</p></div><div className="flex gap-1"><button type="button" disabled={Boolean(working) || index === 0} onClick={() => move(index, -1)} className="rounded border px-2 py-1 text-xs disabled:opacity-40" aria-label={`${scene.title} 위로 이동`}>위</button><button type="button" disabled={Boolean(working) || index === sortedScenes.length - 1} onClick={() => move(index, 1)} className="rounded border px-2 py-1 text-xs disabled:opacity-40" aria-label={`${scene.title} 아래로 이동`}>아래</button><button type="button" disabled={Boolean(working)} onClick={() => void action({ action: "regenerate", scene_id: scene.scene_id }, `regenerate-${scene.scene_id}`)} className="rounded border border-emerald-300 px-2 py-1 text-xs font-semibold text-emerald-800 disabled:opacity-40">다시 만들기</button></div></li>)}</ol></section>
        </div>
        <div className="space-y-5">
          <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm" aria-labelledby="text-title"><h2 id="text-title" className="font-bold">장면 문구</h2><label className="mt-3 block text-sm font-semibold" htmlFor="video-text-scene">장면 선택</label><select id="video-text-scene" value={textScene} onChange={(event) => { const sceneId = event.target.value; setTextScene(sceneId); setTextDraft(data.video.texts.find((item) => item.scene_id === sceneId)?.text ?? ""); }} className="mt-1 w-full rounded-md border p-2"> <option value="">장면을 선택하세요</option>{sortedScenes.map((scene) => <option key={scene.scene_id} value={scene.scene_id}>{scene.title}</option>)}</select>{textScene && <><label className="mt-3 block text-sm font-semibold" htmlFor="video-text-input">표시 문구</label><textarea id="video-text-input" value={textDraft} onChange={(event) => setTextDraft(event.target.value)} maxLength={2000} className="mt-1 min-h-28 w-full rounded-md border p-2" /><button type="button" disabled={Boolean(working) || !textDraft.trim()} onClick={() => void action({ action: "text_edit", scene_id: textScene, body_text: textDraft }, `text-${textScene}`)} className="mt-3 rounded-md bg-emerald-700 px-3 py-2 text-sm font-semibold text-white disabled:opacity-40">문구 저장</button></>}</section>
          <section className="space-y-3 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm" aria-labelledby="metadata-title"><h2 id="metadata-title" className="font-bold">플랫폼별 게시 정보</h2>{(["reels", "tiktok", "youtube_shorts"] as const).map((platform) => { const existing = video.metadata.find((item) => item.platform === platform); const value = metadata[platform] || { title: existing?.title || "", caption: existing?.caption || "", description: existing?.description || "", hashtags: (existing?.hashtags || []).join(" "), cta: existing?.cta || "" }; return <fieldset key={platform} className="rounded-lg border border-slate-100 p-3"><legend className="px-1 text-sm font-semibold">{platformLabels[platform]}</legend>{platform === "youtube_shorts" && <input aria-label={`${platformLabels[platform]} 제목`} value={value.title} onChange={(event) => setMetadata({ ...metadata, [platform]: { ...value, title: event.target.value } })} placeholder="제목" className="mb-2 w-full rounded border p-2 text-sm" />}{platform !== "youtube_shorts" && <textarea aria-label={`${platformLabels[platform]} 캡션`} value={value.caption} onChange={(event) => setMetadata({ ...metadata, [platform]: { ...value, caption: event.target.value } })} placeholder="캡션" className="mb-2 min-h-20 w-full rounded border p-2 text-sm" />}{platform === "youtube_shorts" && <textarea aria-label={`${platformLabels[platform]} 설명`} value={value.description} onChange={(event) => setMetadata({ ...metadata, [platform]: { ...value, description: event.target.value } })} placeholder="설명" className="mb-2 min-h-20 w-full rounded border p-2 text-sm" />}<input aria-label={`${platformLabels[platform]} 해시태그`} value={value.hashtags} onChange={(event) => setMetadata({ ...metadata, [platform]: { ...value, hashtags: event.target.value } })} placeholder="#제품 #사용법" className="w-full rounded border p-2 text-sm" /><button type="button" disabled={Boolean(working)} onClick={() => void action({ action: "metadata_edit", platform, title: value.title || null, caption: value.caption || null, description: value.description || null, hashtags: value.hashtags.split(/\s+/).filter(Boolean), cta: value.cta || null, parent_metadata_version_id: existing?.id || null }, `metadata-${platform}`)} className="mt-2 rounded-md border border-emerald-300 px-3 py-2 text-sm font-semibold text-emerald-800 disabled:opacity-40">저장</button><p className="mt-2 text-xs text-slate-500">상태: {existing?.validation_status || "아직 작성하지 않음"}</p></fieldset>; })}</section>
        </div>
      </section>
    </main>
  );
}

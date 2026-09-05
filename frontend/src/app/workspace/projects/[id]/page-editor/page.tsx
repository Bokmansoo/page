"use client";

import React, { useEffect, useState } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import AiEditCommandPanel from "@/components/AiEditCommandPanel";
import ReviewEditorLayout from "@/components/ReviewEditorLayout";
import { apiUrl } from "@/lib/api";

interface Section {
  id: string;
  section_type: string;
  title: string;
  body_copy: string;
  associated_fact_ids: string[];
  image_asset_id: string | null;
  sort_order: number;
  is_visible: boolean;
  visual_kind?: "image" | "html_graphic";
  visual_payload?: Record<string, unknown>;
  warnings?: string[];
}

interface PageData {
  id: string;
  project_id: string;
  theme_color: string;
  font_family: string;
  sections: Section[];
}

interface ProjectAsset {
  id: string;
  filename: string;
  file_path: string;
  mime_type: string;
  source_type: string;
}

interface PageVersion {
  id: string;
  name: string;
  style_key: string;
  is_final: boolean;
  created_at: string;
}

interface PageVersionSnapshot extends PageVersion {
  sections_json: {
    theme_color?: string;
    font_family?: string;
    sections?: Array<{ title?: string; section_type?: string; is_visible?: boolean }>;
  };
}

interface ProjectData {
  id: string;
  name: string;
  status: string;
}

const MOCK_HEADERS: Record<string, string> = {};

const BACKEND_URL = "http://localhost:8001/api/v1";

export default function PageEditor() {
  const params = useParams();
  const router = useRouter();
  const searchParams = useSearchParams();
  const projectId = params.id as string;
  const mode = searchParams.get("mode") || "review";

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState<PageData | null>(null);
  const [project, setProject] = useState<ProjectData | null>(null);
  const [assets, setAssets] = useState<ProjectAsset[]>([]);
  const [selectedSectionId, setSelectedSectionId] = useState<string | null>(null);
  const [currentVersionId, setCurrentVersionId] = useState<string | null>(null);
  const [versions, setVersions] = useState<PageVersion[]>([]);
  const [compareVersion, setCompareVersion] = useState<PageVersionSnapshot | null>(null);
  const [saving, setSaving] = useState(false);

  const loadData = async () => {
    try {
      setLoading(true);
      setError(null);
      const [projectRes, pageRes, assetsRes, versionsRes] = await Promise.all([
        fetch(apiUrl(`/api/v1/projects/${projectId}`), { headers: MOCK_HEADERS, credentials: "include" }),
        fetch(apiUrl(`/api/v1/projects/${projectId}/page`), { headers: MOCK_HEADERS, credentials: "include" }),
        fetch(apiUrl(`/api/v1/projects/${projectId}/assets`), { headers: MOCK_HEADERS, credentials: "include" }),
        fetch(apiUrl(`/api/v1/projects/${projectId}/page/versions`), { headers: MOCK_HEADERS, credentials: "include" }),
      ]);

      if (!projectRes.ok) throw new Error("프로젝트 정보를 불러오지 못했습니다.");
      if (!pageRes.ok) throw new Error("생성된 상세페이지 초안을 불러오지 못했습니다.");

      const nextProject = (await projectRes.json()) as ProjectData;
      const nextPage = (await pageRes.json()) as PageData;
      const nextAssets = assetsRes.ok ? ((await assetsRes.json()) as ProjectAsset[]) : [];

      setProject(nextProject);
      setPage(nextPage);
      setAssets(nextAssets.filter((asset) => asset.mime_type?.startsWith("image/")));
      if (versionsRes.ok) {
        const versions = await versionsRes.json();
        setVersions(versions);
        setCurrentVersionId(versions[0]?.id || null);
      }
      setSelectedSectionId((current) => current || nextPage.sections.find((section) => section.is_visible)?.id || null);
    } catch (err) {
      console.error(err);
      setError(err instanceof Error ? err.message : "검수 화면을 불러오는 중 오류가 발생했습니다.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, [projectId]);

  if (loading) {
    return (
      <div className="min-h-screen bg-slate-50 flex items-center justify-center">
        <div className="rounded-3xl bg-white border border-slate-200 p-8 text-center shadow-sm space-y-3">
          <div className="mx-auto h-10 w-10 animate-spin rounded-full border-4 border-emerald-500 border-t-transparent" />
          <p className="text-sm font-bold text-slate-600">상세페이지 검수 화면을 불러오고 있습니다...</p>
        </div>
      </div>
    );
  }

  if (error || !page) {
    return (
      <div className="min-h-screen bg-slate-50 flex items-center justify-center p-8 text-center">
        <div className="max-w-md rounded-3xl bg-white border border-slate-200 p-8 shadow-sm space-y-4">
          <h1 className="text-xl font-extrabold text-slate-900">생성된 상세페이지가 없습니다</h1>
          <p className="text-sm leading-relaxed text-slate-500">{error || "먼저 상품 사진이나 URL을 입력해 AI 상세페이지를 만들어 주세요."}</p>
          <button
            type="button"
            onClick={() => router.push("/workspace")}
            className="rounded-2xl bg-emerald-600 px-5 py-3 text-sm font-extrabold text-white hover:bg-emerald-700"
          >
            AI 상세페이지 만들기
          </button>
        </div>
      </div>
    );
  }

  const selectedSection = page.sections.find((section) => section.id === selectedSectionId) || null;
  const isAdvancedMode = mode === "advanced";
  const modeTitle = isAdvancedMode ? "고급 편집기" : "검수하며 다듬기";
  const modeDescription = isAdvancedMode
    ? "섹션 순서와 레이아웃을 더 세밀하게 조정합니다."
    : "문구와 이미지 후보를 빠르게 확인하고 업로드 전 오류를 줄입니다.";

  const patchPage = async (nextPage: PageData, confirmUnsupportedClaims = false) => {
    setSaving(true);
    const res = await fetch(apiUrl(`/api/v1/projects/${projectId}/page`), {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
        ...MOCK_HEADERS,
      },
      credentials: "include",
      body: JSON.stringify({
        theme_color: nextPage.theme_color,
        font_family: nextPage.font_family,
        expected_version_id: currentVersionId,
        confirm_unsupported_claims: confirmUnsupportedClaims,
        sections: nextPage.sections.map((section) => ({
          id: section.id,
          title: section.title,
          body_copy: section.body_copy,
          image_asset_id: section.image_asset_id,
          visual_kind: section.visual_kind,
          visual_payload: section.visual_payload,
          sort_order: section.sort_order,
          is_visible: section.is_visible,
        })),
      }),
    });

    try {
      if (!res.ok) {
        if (res.status === 409) {
          await loadData();
          throw new Error("다른 수정이 먼저 저장되어 최신 내용으로 새로고침했습니다. 변경 내용을 다시 입력해 주세요.");
        }
        const detail = await res.json().catch(() => null);
        if (detail?.detail?.code === "unsupported_claim_requires_review") {
          const claims = detail.detail.claims.join(", ");
          if (!confirmUnsupportedClaims && window.confirm(`${detail.detail.message}\n문제 표현: ${claims}\n사실 근거를 확인했습니까? 확인을 누르면 다시 저장합니다.`)) {
            await patchPage(nextPage, true);
            return;
          }
          throw new Error(`${detail.detail.message} 문제 표현: ${claims}`);
        }
        throw new Error("상세페이지 수정 내용을 저장하지 못했습니다.");
      }
      const savedPage = (await res.json()) as PageData;
      setPage(savedPage);
      const versionsRes = await fetch(apiUrl(`/api/v1/projects/${projectId}/page/versions`), { headers: MOCK_HEADERS, credentials: "include" });
      if (versionsRes.ok) {
        const nextVersions = await versionsRes.json();
        setVersions(nextVersions);
        setCurrentVersionId(nextVersions[0]?.id || null);
      }
    } finally {
      setSaving(false);
    }
  };

  const updateSelectedSection = (field: "title" | "body_copy", value: string) => {
    if (!selectedSectionId || !page) return null;
    const nextPage = {
      ...page,
      sections: page.sections.map((section) =>
        section.id === selectedSectionId ? { ...section, [field]: value } : section
      ),
    };
    setPage(nextPage);
    return nextPage;
  };

  const updateSectionLayout = (direction: "up" | "down" | "toggle") => {
    if (!selectedSectionId || !page) return;
    const index = page.sections.findIndex((section) => section.id === selectedSectionId);
    if (index < 0) return;
    const next = page.sections.map((section) => ({ ...section }));
    if (direction === "toggle") {
      next[index].is_visible = !next[index].is_visible;
    } else {
      const target = direction === "up" ? index - 1 : index + 1;
      if (target < 0 || target >= next.length) return;
      [next[index].sort_order, next[target].sort_order] = [next[target].sort_order, next[index].sort_order];
    }
    const nextPage = { ...page, sections: next };
    setPage(nextPage);
    patchPage(nextPage).catch((err) => setError(err.message));
  };

  const updateVisual = (imageAssetId: string | null, crop?: { x: number; y: number }) => {
    if (!page || !selectedSectionId) return;
    const nextPage = {
      ...page,
      sections: page.sections.map((section) => section.id === selectedSectionId ? {
        ...section,
        image_asset_id: imageAssetId,
        visual_kind: imageAssetId ? ("image" as const) : ("html_graphic" as const),
        visual_payload: {
          ...(section.visual_payload || {}),
          ...(crop ? { crop } : {}),
          copy_provenance: (section.visual_payload?.copy_provenance as string) || "seller",
        },
      } : section),
    };
    setPage(nextPage);
    patchPage(nextPage).catch((err) => setError(err.message));
  };

  const updatePageStyle = (field: "theme_color" | "font_family", value: string) => {
    if (!page) return;
    const nextPage = { ...page, [field]: value };
    setPage(nextPage);
    patchPage(nextPage).catch((err) => setError(err.message));
  };

  const updateSectionPresentation = (field: "text_align" | "content_spacing", value: string) => {
    if (!page || !selectedSectionId) return;
    const nextPage = {
      ...page,
      sections: page.sections.map((section) => section.id === selectedSectionId ? {
        ...section,
        visual_payload: {
          ...(section.visual_payload || {}),
          presentation: {
            ...((section.visual_payload?.presentation as Record<string, unknown>) || {}),
            [field]: value,
          },
        },
      } : section),
    };
    setPage(nextPage);
    patchPage(nextPage).catch((err) => setError(err.message));
  };

  const showVersionComparison = async (versionId: string) => {
    const res = await fetch(apiUrl(`/api/v1/projects/${projectId}/page/versions/${versionId}`), { headers: MOCK_HEADERS, credentials: "include" });
    if (!res.ok) throw new Error("버전 내용을 불러오지 못했습니다.");
    setCompareVersion(await res.json());
  };

  const restoreVersion = async (versionId: string) => {
    if (!window.confirm("이 버전으로 복원할까요? 현재 내용도 새 버전으로 보존됩니다.")) return;
    const res = await fetch(apiUrl(`/api/v1/projects/${projectId}/page/versions/${versionId}/restore`), {
      method: "POST", headers: MOCK_HEADERS, credentials: "include",
    });
    if (!res.ok) throw new Error("버전을 복원하지 못했습니다.");
    await loadData();
    setCompareVersion(null);
  };

  return (
    <ReviewEditorLayout
      projectId={projectId}
      projectName={project?.name || "상세페이지 초안"}
      modeTitle={modeTitle}
      modeDescription={modeDescription}
      page={page}
      selectedSectionId={selectedSectionId}
      onSelectSection={setSelectedSectionId}
      projectAssets={assets}
      onBack={() => router.push(`/workspace/projects/${projectId}/result`)}
      rightPanel={
        <div className="space-y-5">
          <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
            <p className="text-xs font-bold text-emerald-700">선택한 섹션</p>
            <h3 className="mt-1 text-base font-extrabold text-slate-950">
              {selectedSection?.title || "섹션을 선택해 주세요"}
            </h3>
            <p className="mt-2 text-xs leading-relaxed text-slate-500">
              {isAdvancedMode
                ? "고급 편집 모드입니다. 섹션 구성과 레이아웃 관점으로 더 세밀하게 다듬어 주세요."
                : "초안을 검수하고 필요한 섹션만 AI 수정으로 다듬어 주세요."}
            </p>
          </div>
          {selectedSection ? (
            <div className="rounded-2xl border border-slate-200 bg-white p-4">
              <p className="text-xs font-bold text-emerald-700">직접 수정</p>
              <p className="mt-1 text-xs leading-relaxed text-slate-500">
                입력하는 즉시 가운데 미리보기에 반영됩니다. 입력 칸을 벗어나면 저장됩니다.
              </p>
              <label className="mt-4 block text-xs font-bold text-slate-600" htmlFor="section-title-edit">
                제목
              </label>
              <input
                id="section-title-edit"
                value={selectedSection.title || ""}
                onChange={(event) => updateSelectedSection("title", event.target.value)}
                onBlur={() => page && patchPage(page).catch((err) => setError(err.message))}
                className="mt-2 w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm font-bold text-slate-900 outline-none focus:border-emerald-400"
              />
              <label className="mt-4 block text-xs font-bold text-slate-600" htmlFor="section-body-edit">
                본문
              </label>
              <textarea
                id="section-body-edit"
                value={selectedSection.body_copy || ""}
                onChange={(event) => updateSelectedSection("body_copy", event.target.value)}
                onBlur={() => page && patchPage(page).catch((err) => setError(err.message))}
                className="mt-2 min-h-32 w-full resize-none rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm leading-relaxed text-slate-700 outline-none focus:border-emerald-400"
              />
              {selectedSection.associated_fact_ids?.length ? (
                <p className="mt-2 rounded-lg bg-emerald-50 px-3 py-2 text-[11px] leading-relaxed text-emerald-900">
                  이 문구는 확인된 상품 사실 {selectedSection.associated_fact_ids.length}건과 연결되어 있습니다. 수치·단위·모델 정보는 근거를 확인한 뒤 수정해 주세요.
                </p>
              ) : null}
              <label className="mt-4 block text-xs font-bold text-slate-600" htmlFor="section-image-edit">이미지 교체</label>
              <select
                id="section-image-edit"
                value={selectedSection.image_asset_id || ""}
                onChange={(event) => updateVisual(event.target.value || null)}
                className="mt-2 w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-bold text-slate-700"
              >
                <option value="">이미지 없이 그래픽 블록 사용</option>
                {assets.map((asset) => <option key={asset.id} value={asset.id}>{asset.filename} · {asset.source_type}</option>)}
              </select>
              <div className="mt-3 grid grid-cols-3 gap-2">
                <button type="button" onClick={() => updateVisual(selectedSection.image_asset_id, { x: 0.5, y: 0.25 })} className="rounded-lg border border-slate-200 px-2 py-2 text-[11px] font-bold text-slate-600">상단 크롭</button>
                <button type="button" onClick={() => updateVisual(selectedSection.image_asset_id, { x: 0.5, y: 0.5 })} className="rounded-lg border border-slate-200 px-2 py-2 text-[11px] font-bold text-slate-600">가운데</button>
                <button type="button" onClick={() => updateVisual(selectedSection.image_asset_id, { x: 0.5, y: 0.75 })} className="rounded-lg border border-slate-200 px-2 py-2 text-[11px] font-bold text-slate-600">하단 크롭</button>
              </div>
              <div className="mt-3 grid grid-cols-2 gap-2">
                <label className="text-[11px] font-bold text-slate-600">정렬<select value={((selectedSection.visual_payload?.presentation as Record<string, string>)?.text_align) || "left"} onChange={(event) => updateSectionPresentation("text_align", event.target.value)} className="mt-1 block w-full rounded border border-slate-200 px-2 py-2 text-xs"><option value="left">왼쪽</option><option value="center">가운데</option><option value="right">오른쪽</option></select></label>
                <label className="text-[11px] font-bold text-slate-600">여백<select value={((selectedSection.visual_payload?.presentation as Record<string, string>)?.content_spacing) || "normal"} onChange={(event) => updateSectionPresentation("content_spacing", event.target.value)} className="mt-1 block w-full rounded border border-slate-200 px-2 py-2 text-xs"><option value="compact">좁게</option><option value="normal">기본</option><option value="relaxed">넓게</option></select></label>
              </div>
              <div className="mt-4 grid grid-cols-3 gap-2">
                <button type="button" onClick={() => updateSectionLayout("up")} className="rounded-lg border border-slate-200 px-2 py-2 text-xs font-bold text-slate-600 hover:border-emerald-300">위로</button>
                <button type="button" onClick={() => updateSectionLayout("down")} className="rounded-lg border border-slate-200 px-2 py-2 text-xs font-bold text-slate-600 hover:border-emerald-300">아래로</button>
                <button type="button" onClick={() => updateSectionLayout("toggle")} className="rounded-lg border border-slate-200 px-2 py-2 text-xs font-bold text-slate-600 hover:border-emerald-300">{selectedSection.is_visible ? "숨기기" : "복원"}</button>
              </div>
              <p className="mt-2 text-[11px] leading-relaxed text-slate-500">최종 사양·고지 섹션은 항상 마지막에만 둘 수 있습니다.</p>
            </div>
          ) : null}
          <div className="rounded-2xl border border-slate-200 bg-white p-4">
            <p className="text-xs font-bold text-emerald-700">페이지 스타일</p>
            <div className="mt-3 grid grid-cols-2 gap-2">
              <label className="text-[11px] font-bold text-slate-600">강조색<input type="color" value={page.theme_color || "#0f766e"} onChange={(event) => updatePageStyle("theme_color", event.target.value)} className="mt-1 block h-9 w-full rounded border border-slate-200" /></label>
              <label className="text-[11px] font-bold text-slate-600">글꼴<select value={page.font_family || "sans-serif"} onChange={(event) => updatePageStyle("font_family", event.target.value)} className="mt-1 block w-full rounded border border-slate-200 px-2 py-2 text-xs"><option value="Pretendard">Pretendard</option><option value="sans-serif">기본 산세리프</option><option value="serif">명조</option></select></label>
            </div>
            <p className="mt-2 text-[11px] text-slate-500">색상·글꼴 변경은 자동 저장되어 버전으로 남습니다.</p>
          </div>
          <div className="rounded-2xl border border-slate-200 bg-white p-4">
            <div className="flex items-center justify-between"><p className="text-xs font-bold text-emerald-700">버전·변경 비교</p><span className="text-[10px] text-slate-400">{saving ? "저장 중" : "자동 저장"}</span></div>
            <div className="mt-3 max-h-44 space-y-2 overflow-y-auto">
              {versions.slice(0, 8).map((version) => <div key={version.id} className="rounded-lg bg-slate-50 p-2 text-xs"><p className="font-bold text-slate-700">{version.name}{version.is_final ? " · 최종" : ""}</p><div className="mt-1 flex gap-2"><button type="button" onClick={() => showVersionComparison(version.id).catch((err) => setError(err.message))} className="text-emerald-700">비교</button><button type="button" onClick={() => restoreVersion(version.id).catch((err) => setError(err.message))} className="text-slate-600">복원</button></div></div>)}
            </div>
            {compareVersion ? <div className="mt-3 rounded-lg border border-violet-100 bg-violet-50 p-3 text-[11px] text-violet-900"><p className="font-bold">비교: {compareVersion.name}</p><p className="mt-1">현재 {page.sections.filter((section) => section.is_visible).length}개 섹션 · 선택 버전 {compareVersion.sections_json.sections?.filter((section) => section.is_visible !== false).length ?? 0}개 섹션</p><p>색상 {compareVersion.sections_json.theme_color || "기본"} · 글꼴 {compareVersion.sections_json.font_family || "기본"}</p></div> : null}
            {versions.some((version) => version.name === "AI 생성 상세페이지") ? <button type="button" onClick={() => { const original = versions.find((version) => version.name === "AI 생성 상세페이지"); if (original) restoreVersion(original.id).catch((err) => setError(err.message)); }} className="mt-3 w-full rounded-lg border border-slate-200 px-3 py-2 text-xs font-bold text-slate-700 hover:border-emerald-300">생성 원본으로 되돌리기</button> : null}
          </div>
          <AiEditCommandPanel
            projectId={projectId}
            sectionId={selectedSectionId}
            backendUrl={BACKEND_URL}
            headers={MOCK_HEADERS}
            onUpdateSuccess={loadData}
            onApplyProposal={async (title, bodyCopy) => {
              if (!page || !selectedSectionId) return;
              const nextPage = {
                ...page,
                sections: page.sections.map((section) =>
                  section.id === selectedSectionId
                    ? { ...section, title, body_copy: bodyCopy, visual_payload: { ...(section.visual_payload || {}), copy_provenance: "ai" } }
                    : section
                ),
              };
              setPage(nextPage);
              await patchPage(nextPage);
            }}
          />
        </div>
      }
    />
  );
}

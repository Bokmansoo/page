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

interface ProjectData {
  id: string;
  name: string;
  status: string;
}

const MOCK_HEADERS = {
  "X-Mock-User-Id": "00000000-0000-0000-0000-000000000001",
  "X-Mock-Workspace-Id": "00000000-0000-0000-0000-000000000002",
};

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

  const loadData = async () => {
    try {
      setLoading(true);
      setError(null);
      const [projectRes, pageRes, assetsRes] = await Promise.all([
        fetch(apiUrl(`/api/v1/projects/${projectId}`), { headers: MOCK_HEADERS }),
        fetch(apiUrl(`/api/v1/projects/${projectId}/page`), { headers: MOCK_HEADERS }),
        fetch(apiUrl(`/api/v1/projects/${projectId}/assets`), { headers: MOCK_HEADERS }),
      ]);

      if (!projectRes.ok) throw new Error("프로젝트 정보를 불러오지 못했습니다.");
      if (!pageRes.ok) throw new Error("생성된 상세페이지 초안을 불러오지 못했습니다.");

      const nextProject = (await projectRes.json()) as ProjectData;
      const nextPage = (await pageRes.json()) as PageData;
      const nextAssets = assetsRes.ok ? ((await assetsRes.json()) as ProjectAsset[]) : [];

      setProject(nextProject);
      setPage(nextPage);
      setAssets(nextAssets.filter((asset) => asset.mime_type?.startsWith("image/")));
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

  const patchPage = async (nextPage: PageData) => {
    const res = await fetch(apiUrl(`/api/v1/projects/${projectId}/page`), {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
        ...MOCK_HEADERS,
      },
      body: JSON.stringify({
        theme_color: nextPage.theme_color,
        font_family: nextPage.font_family,
        sections: nextPage.sections.map((section) => ({
          id: section.id,
          title: section.title,
          body_copy: section.body_copy,
          image_asset_id: section.image_asset_id,
          sort_order: section.sort_order,
          is_visible: section.is_visible,
        })),
      }),
    });

    if (!res.ok) throw new Error("상세페이지 수정 내용을 저장하지 못했습니다.");
    const savedPage = (await res.json()) as PageData;
    setPage(savedPage);
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

  return (
    <ReviewEditorLayout
      projectId={projectId}
      projectName={project?.name || (mode === "advanced" ? "고급 편집기" : "상세페이지 검수")}
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
              {mode === "advanced"
                ? "고급 편집 모드입니다. 결과 화면의 보조 버튼으로만 진입할 수 있습니다."
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
            </div>
          ) : null}
          <AiEditCommandPanel
            projectId={projectId}
            sectionId={selectedSectionId}
            backendUrl={BACKEND_URL}
            headers={MOCK_HEADERS}
            onUpdateSuccess={loadData}
          />
        </div>
      }
    />
  );
}

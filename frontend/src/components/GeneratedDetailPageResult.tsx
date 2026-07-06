"use client";

import React, { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { apiUrl } from "@/lib/api";
import DetailPageDocument from "@/components/DetailPageDocument";
import { validateSectionVisual } from "@/components/detail-page/types";
import type { DetailPageSectionVisual } from "@/components/detail-page/types";

type ExportStage = "idle" | "finalizing" | "rendering" | "downloading" | "saving";

interface GeneratedDetailPageResultProps {
  projectId: string;
}

interface ImageCandidate {
  candidate_id: string;
  slot_id: string;
  asset_id: string | null;
  source_type: string;
  label: string;
  is_recommended: boolean;
  needs_identity_review: boolean;
}

interface PageSection {
  id: string;
  section_type: string;
  title: string;
  body_copy: string;
  image_asset_id: string | null;
  sort_order: number;
  is_visible: boolean;
  image_candidates?: ImageCandidate[];
}

interface PageData {
  id: string;
  project_id: string;
  theme_color: string;
  font_family: string;
  sections: PageSection[];
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

interface ExportJob {
  id: string;
  status: "pending" | "processing" | "running" | "completed" | "failed";
  error_message: string | null;
  output_images: string[] | null;
}

interface FinalPageVersion {
  id: string;
}

type ExportImageFormat = "png" | "jpg";

interface WritableSaveFile {
  write(data: Blob): Promise<void>;
  close(): Promise<void>;
}

interface SaveFileHandle {
  createWritable(): Promise<WritableSaveFile>;
}

type SaveFilePicker = (options: {
  suggestedName: string;
  types: Array<{
    description: string;
    accept: Record<string, string[]>;
  }>;
  excludeAcceptAllOption: boolean;
}) => Promise<SaveFileHandle>;

function safeExportFilename(name: string): string {
  const sanitized = name
    .replace(/[<>:"/\\|?*\u0000-\u001f]/g, "_")
    .replace(/[. ]+$/g, "")
    .trim();
  return sanitized || "sellform-detail-page";
}

async function chooseSaveFile(
  filename: string,
  format: ExportImageFormat
): Promise<SaveFileHandle | null> {
  const picker = (
    window as typeof window & { showSaveFilePicker?: SaveFilePicker }
  ).showSaveFilePicker;
  if (!picker) return null;

  const mimeType = format === "jpg" ? "image/jpeg" : "image/png";
  return picker.call(window, {
    suggestedName: filename,
    types: [
      {
        description: `${format.toUpperCase()} 이미지`,
        accept: { [mimeType]: [`.${format}`] },
      },
    ],
    excludeAcceptAllOption: true,
  });
}

const MOCK_HEADERS = {
  "X-Mock-User-Id": "00000000-0000-0000-0000-000000000001",
  "X-Mock-Workspace-Id": "00000000-0000-0000-0000-000000000002",
};

function sourceLabel(sourceType: string): string {
  switch (sourceType) {
    case "uploaded":
      return "직접 업로드";
    case "url-extracted":
    case "url-imported":
      return "URL 추출";
    case "mock-generated":
      return "AI 모의 생성";
    case "real-generated":
      return "AI 생성 이미지";
    case "ai-generated":
      return "AI 생성";
    case "generation-skipped":
      return "생성 생략";
    case "blocked_cost_approval":
      return "이미지 생성 비용 승인 필요";
    case "needs_review":
      return "상품 정체성 검수 필요";
    default:
      return sourceType || "출처 없음";
  }
}

function assetUrl(asset: ProjectAsset | { id: string; file_path?: string }): string {
  if (asset.file_path && asset.file_path.startsWith("http")) {
    return asset.file_path;
  }
  return apiUrl(`/api/v1/files/assets/${asset.id}`);
}

function sectionTheme(sectionType: string, index: number) {
  if (sectionType === "hero") {
    return {
      section: "bg-slate-950 px-8 py-16 text-center text-white sm:px-16 sm:py-20",
      eyebrow: "text-emerald-300",
      title: "text-white sm:text-4xl",
      body: "text-slate-300",
      figure: "bg-slate-900",
    };
  }
  if (sectionType === "detail_1" || sectionType === "guarantee") {
    return {
      section: "bg-slate-900 px-8 py-14 text-center text-white sm:px-14 sm:py-16",
      eyebrow: "text-emerald-300",
      title: "text-white",
      body: "text-slate-300",
      figure: "bg-slate-800",
    };
  }
  if (sectionType === "detail_2") {
    return {
      section: "bg-[#f3efe7] px-8 py-14 text-center sm:px-14 sm:py-16",
      eyebrow: "text-emerald-800",
      title: "text-slate-950",
      body: "text-slate-700",
      figure: "bg-white",
    };
  }
  return {
    section: `${index % 2 === 0 ? "bg-white" : "bg-emerald-50/50"} px-8 py-14 text-center sm:px-14 sm:py-16`,
    eyebrow: "text-emerald-700",
    title: "text-slate-950",
    body: "text-slate-600",
    figure: "bg-white",
  };
}

export default function GeneratedDetailPageResult({ projectId }: GeneratedDetailPageResultProps) {
  const router = useRouter();
  const [loading, setLoading] = useState(true);
  const [project, setProject] = useState<ProjectData | null>(null);
  const [pageData, setPageData] = useState<PageData | null>(null);
  const [assets, setAssets] = useState<ProjectAsset[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);
  const [exportFormat, setExportFormat] = useState<ExportImageFormat>("png");
  const [exportStage, setExportStage] = useState<ExportStage>("idle");

  useEffect(() => {
    const loadData = async () => {
      try {
        setLoading(true);
        const [projectRes, pageRes, assetsRes] = await Promise.all([
          fetch(apiUrl(`/api/v1/projects/${projectId}`), { headers: MOCK_HEADERS }),
          fetch(apiUrl(`/api/v1/projects/${projectId}/page`), { headers: MOCK_HEADERS }),
          fetch(apiUrl(`/api/v1/projects/${projectId}/assets`), { headers: MOCK_HEADERS }),
        ]);

        if (!projectRes.ok) throw new Error("프로젝트 정보를 불러오지 못했습니다.");
        if (!pageRes.ok) throw new Error("생성된 상세페이지를 불러오지 못했습니다.");

        setProject(await projectRes.json());
        setPageData(await pageRes.json());
        setAssets(assetsRes.ok ? await assetsRes.json() : []);
      } catch (err) {
        console.error(err);
        setError(err instanceof Error ? err.message : "상세페이지 초안을 불러오는 중 오류가 발생했습니다.");
      } finally {
        setLoading(false);
      }
    };

    loadData();
  }, [projectId]);

  const handleSelectImageCandidate = async (sectionId: string, candidate: ImageCandidate) => {
    if (!pageData || !candidate.asset_id) return;
    try {
      const updatedSections = pageData.sections.map((sec) => {
        if (sec.id === sectionId) {
          return {
            id: sec.id,
            title: sec.title,
            body_copy: sec.body_copy,
            image_asset_id: candidate.asset_id,
            sort_order: sec.sort_order,
            is_visible: sec.is_visible,
          };
        }
        return {
          id: sec.id,
          title: sec.title,
          body_copy: sec.body_copy,
          image_asset_id: sec.image_asset_id,
          sort_order: sec.sort_order,
          is_visible: sec.is_visible,
        };
      });

      const res = await fetch(apiUrl(`/api/v1/projects/${projectId}/page`), {
        method: "PATCH",
        headers: {
          ...MOCK_HEADERS,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          sections: updatedSections,
        }),
      });

      if (!res.ok) throw new Error("이미지 후보를 적용하지 못했습니다.");

      const updatedPage = await res.json();
      
      const enrichedSections = updatedPage.sections.map((sec: PageSection) => {
        const origSec = pageData.sections.find((o) => o.id === sec.id);
        return {
          ...sec,
          image_candidates: origSec?.image_candidates || [],
        };
      });
      setPageData({
        ...updatedPage,
        sections: enrichedSections,
      });

    } catch (err) {
      console.error(err);
      alert(err instanceof Error ? err.message : "이미지 선택 중 오류가 발생했습니다.");
    }
  };

  const handleDownloadImage = async (format: ExportImageFormat) => {
    const formatLabel = format.toUpperCase();
    setExportError(null);
    setExportStage("idle");
    const fallbackFilename = `${safeExportFilename(
      project?.name || "sellform-detail-page"
    )}.${format}`;
    let saveHandle: SaveFileHandle | null = null;

    try {
      saveHandle = await chooseSaveFile(fallbackFilename, format);
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") return;
      setExportError("저장 위치 선택 창을 열지 못했습니다. 다시 시도해 주세요.");
      return;
    }

    setExporting(true);
    setExportStage("finalizing");
    try {
      const finalRes = await fetch(apiUrl(`/api/v1/projects/${projectId}/page/finalize`), {
        method: "POST",
        headers: MOCK_HEADERS,
      });
      if (!finalRes.ok) {
        const detail = await finalRes.json().catch(() => null);
        throw new Error(
          detail?.detail || "최종 상세페이지를 고정하지 못했습니다. 다시 시도해 주세요."
        );
      }
      const finalVersion = (await finalRes.json()) as FinalPageVersion;

      setExportStage("rendering");
      const createRes = await fetch(apiUrl(`/api/v1/projects/${projectId}/page/export`), {
        method: "POST",
        headers: {
          ...MOCK_HEADERS,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          preset_name: "smartstore",
          use_commerce_cut: true,
          output_format: format,
          export_target: "local_download",
          final_version_id: finalVersion.id,
        }),
      });
      if (!createRes.ok) {
        const detail = await createRes.json().catch(() => null);
        throw new Error(
          detail?.detail?.message ||
            detail?.detail ||
            `${formatLabel} 내보내기를 시작하지 못했습니다.`
        );
      }

      setExportStage("downloading");
      let job = (await createRes.json()) as ExportJob;
      for (let attempt = 0; attempt < 120 && job.status !== "completed"; attempt += 1) {
        if (job.status === "failed") {
          throw new Error(job.error_message || `${formatLabel} 내보내기에 실패했습니다.`);
        }
        await new Promise((resolve) => window.setTimeout(resolve, 500));
        const statusRes = await fetch(
          apiUrl(`/api/v1/projects/${projectId}/page/export/jobs/${job.id}`),
          { headers: MOCK_HEADERS }
        );
        if (!statusRes.ok) {
          throw new Error(`${formatLabel} 내보내기 상태를 확인하지 못했습니다.`);
        }
        job = (await statusRes.json()) as ExportJob;
      }

      const outputPath = job.output_images?.[0];
      if (job.status !== "completed" || !outputPath) {
        throw new Error(
          `${formatLabel} 내보내기 시간이 초과되었습니다. 잠시 후 다시 시도해 주세요.`
        );
      }

      const fileRes = await fetch(apiUrl(outputPath), { headers: MOCK_HEADERS });
      if (!fileRes.ok) {
        throw new Error(`완성된 ${formatLabel} 파일을 내려받지 못했습니다.`);
      }
      const disposition = fileRes.headers.get("content-disposition") || "";
      const encodedFilename = disposition.match(/filename\*=UTF-8''([^;]+)/i)?.[1];
      const quotedFilename = disposition.match(/filename="([^"]+)"/i)?.[1];
      let filename = quotedFilename || fallbackFilename;
      if (encodedFilename) {
        try {
          filename = decodeURIComponent(encodedFilename);
        } catch {
          filename = encodedFilename;
        }
      }
      setExportStage("saving");
      const blob = await fileRes.blob();
      if (saveHandle) {
        const writable = await saveHandle.createWritable();
        await writable.write(blob);
        await writable.close();
      } else {
        const blobUrl = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = blobUrl;
        link.download = filename;
        document.body.appendChild(link);
        link.click();
        link.remove();
        window.setTimeout(() => URL.revokeObjectURL(blobUrl), 1000);
      }
    } catch (err) {
      setExportError(
        err instanceof TypeError && err.message === "Failed to fetch"
          ? "백엔드 서버에 연결할 수 없습니다. 서버 실행 상태를 확인해 주세요."
          : err instanceof Error
          ? err.message
          : `${formatLabel} 저장 중 오류가 발생했습니다.`
      );
    } finally {
      setExporting(false);
      setExportStage("idle");
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-white flex flex-col items-center justify-center space-y-4">
        <div className="w-10 h-10 border-4 border-emerald-500 border-t-transparent rounded-full animate-spin" />
        <p className="text-slate-500 text-sm font-medium">완성된 상세페이지를 불러오고 있습니다...</p>
      </div>
    );
  }

  if (error || !pageData) {
    return (
      <div className="min-h-screen bg-white flex flex-col items-center justify-center p-6 text-center space-y-4">
        <h2 className="text-lg font-bold text-slate-800">상세페이지를 불러오지 못했습니다</h2>
        <p className="text-slate-500 text-sm">{error || "생성된 상세페이지가 없습니다."}</p>
        <button
          type="button"
          onClick={() => router.push("/workspace")}
          className="px-4 py-2 bg-slate-800 text-white rounded-lg text-sm font-semibold hover:bg-slate-700 transition-all"
        >
          워크스페이스로 돌아가기
        </button>
      </div>
    );
  }

  const visibleSections = pageData.sections
    .filter((section) => section.is_visible)
    .sort((a, b) => a.sort_order - b.sort_order);
  const invalidVisualCount = visibleSections.filter(
    (section) => validateSectionVisual(section as unknown as DetailPageSectionVisual).length > 0
  ).length;

  return (
    <div className="min-h-screen bg-white text-slate-800">
      <header className="sticky top-0 z-40 flex items-center justify-between border-b border-slate-200 bg-white px-6 py-4">
        <div className="flex min-w-0 items-center gap-3">
          <span className={`rounded-full border px-3 py-1 text-xs font-bold ${
            invalidVisualCount
              ? "border-amber-200 bg-amber-50 text-amber-700"
              : "border-emerald-200 bg-emerald-50 text-emerald-700"
          }`}>
            {invalidVisualCount ? `시각 요소 ${invalidVisualCount}개 확인 필요` : "생성 완료"}
          </span>
          <h1 className="text-lg font-extrabold text-slate-950">완성된 상세페이지</h1>
          <p className="max-w-[300px] truncate border-l border-slate-200 pl-3 text-xs font-medium text-slate-500">
            {project?.name}
          </p>
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => router.push(`/workspace/projects/${projectId}/page-editor?mode=advanced`)}
            className="rounded-lg border border-slate-200 bg-white px-4 py-2 text-xs font-bold text-slate-700 hover:bg-slate-50"
          >
            고급 편집기로 열기
          </button>
          <button
            type="button"
            onClick={() => router.push(`/workspace/projects/${projectId}/page-editor?mode=review`)}
            className="rounded-lg bg-emerald-600 px-4 py-2 text-xs font-bold text-white hover:bg-emerald-700"
          >
            검수하며 다듬기
          </button>
        </div>
      </header>

      <main className="mx-auto grid w-full max-w-7xl grid-cols-1 items-start gap-8 px-6 py-8 lg:grid-cols-[minmax(0,760px)_380px]">
        <div>
          <div className="mb-5">
            <h2 className="text-xl font-extrabold text-slate-950">판매용 상세페이지</h2>
            <p className="mt-1 text-sm text-slate-500">실제 구매자가 위에서 아래로 읽는 흐름입니다.</p>
          </div>
          <DetailPageDocument page={pageData} assets={assets} />
          {false ? (
          <article
            className="mx-auto w-full max-w-[760px] overflow-hidden border border-slate-200 bg-white shadow-sm"
            style={{ fontFamily: pageData!.font_family }}
          >
            {visibleSections.map((section, index) => {
              const matchedAsset = assets.find((asset) => asset.id === section.image_asset_id);
              const fallbackAssetId = section.image_asset_id;
              const imageSrc = matchedAsset
                ? assetUrl(matchedAsset)
                : fallbackAssetId
                  ? assetUrl({ id: fallbackAssetId })
                  : null;
              const sourceType = matchedAsset?.source_type || "ai-generated";
              const theme = sectionTheme(section.section_type, index);
              return (
                <section key={section.id} className={theme.section}>
                  <p className={`text-[11px] font-extrabold uppercase tracking-[0.2em] ${theme.eyebrow}`}>
                    {section.section_type.replace("_", " ")}
                  </p>
                  <h3 className={`mx-auto mt-3 max-w-2xl text-2xl font-extrabold leading-snug sm:text-3xl ${theme.title}`}>
                    {section.title}
                  </h3>
                  <p className={`mx-auto mt-4 max-w-2xl text-sm leading-7 sm:text-base ${theme.body}`}>
                    {section.body_copy}
                  </p>
                  {section.section_type !== "product_information" ? (
                    imageSrc ? (
                      <figure className={`relative mt-9 overflow-hidden ${theme.figure}`}>
                        <img
                          src={imageSrc}
                          alt={section.title}
                          className="aspect-[4/3] w-full object-cover"
                        />
                        <figcaption className="absolute right-3 top-3 rounded-full bg-emerald-700 px-3 py-1 text-[10px] font-bold text-white">
                          {sourceLabel(sourceType)}
                        </figcaption>
                      </figure>
                    ) : (
                      <div className="mt-8 flex aspect-[4/3] items-center justify-center border border-amber-200 bg-amber-50 text-sm font-bold text-amber-700">
                        이 섹션은 이미지 재생성이 필요합니다
                      </div>
                    )
                  ) : null}
                </section>
              );
            })}
          </article>
          ) : null}
        </div>

        <aside className="sticky top-24 rounded-lg border border-slate-200 bg-white p-5">
          <div className="mb-5">
            <h2 className="text-base font-extrabold text-slate-950">섹션별 이미지 후보</h2>
            <p className="mt-1 text-xs leading-5 text-slate-500">각 상황에 맞는 이미지를 확인하고 교체하세요.</p>
          </div>
          <div className="max-h-[calc(100vh-190px)] space-y-6 overflow-y-auto pr-2">
            {visibleSections
              .filter((section) => section.section_type !== "product_information")
              .map((section) => {
                const cands = section.image_candidates || [];
                return (
                  <div key={section.id} className="space-y-3 border-b border-slate-100 pb-5 last:border-0">
                    <div className="flex items-center justify-between">
                      <span className="text-[10px] font-extrabold uppercase tracking-wider text-emerald-700">{section.section_type}</span>
                      <span className="max-w-[220px] truncate text-[11px] font-bold text-slate-700">{section.title}</span>
                    </div>
                    {cands.length === 0 ? (
                      <p className="rounded-lg bg-amber-50 px-3 py-2 text-[11px] font-semibold text-amber-700">
                        생성된 후보가 없습니다. 이미지 생성 상태를 확인해 주세요.
                      </p>
                    ) : (
                      <div className="grid grid-cols-2 gap-2">
                        {cands.map((cand) => {
                          const isSelected = Boolean(cand.asset_id) && section.image_asset_id === cand.asset_id;
                          const candThumbnail = cand.asset_id ? assetUrl({ id: cand.asset_id }) : null;
                          return (
                            <div
                              key={cand.candidate_id}
                              className={`rounded-lg border p-2 ${
                                isSelected
                                  ? "border-emerald-500 bg-emerald-50"
                                  : "border-slate-200 bg-white"
                              }`}
                            >
                              <div className="relative aspect-[4/3] overflow-hidden rounded bg-slate-50">
                                {candThumbnail ? (
                                  <img src={candThumbnail} alt={cand.label} className="h-full w-full object-cover" />
                                ) : (
                                  <span className="flex h-full items-center justify-center text-[10px] font-bold text-amber-600">
                                    재생성 필요
                                  </span>
                                )}
                                <span className="absolute right-1.5 top-1.5 rounded-full bg-slate-900/80 px-1.5 py-0.5 text-[8px] font-bold text-white">
                                  {sourceLabel(cand.source_type)}
                                </span>
                              </div>
                              <p className="mt-2 truncate text-[10px] font-bold text-slate-700">{cand.label}</p>
                              <button
                                type="button"
                                disabled={isSelected || !cand.asset_id}
                                onClick={() => handleSelectImageCandidate(section.id, cand)}
                                className={`mt-2 w-full rounded py-1.5 text-[10px] font-bold ${
                                  isSelected
                                    ? "bg-emerald-600 text-white"
                                    : "bg-slate-900 text-white disabled:bg-slate-200 disabled:text-slate-400"
                                }`}
                              >
                                {isSelected ? "적용됨" : "이 이미지 사용"}
                              </button>
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </div>
                );
              })}
          </div>
        </aside>
      </main>

      <footer className="sticky bottom-0 flex items-center justify-center gap-4 border-t border-slate-200 bg-white px-6 py-4">
        <label className="flex items-center gap-2 text-sm font-semibold text-slate-600">
          저장 형식
          <select
            aria-label="저장 형식"
            value={exportFormat}
            disabled={exporting}
            onChange={(event) =>
              setExportFormat(event.target.value as ExportImageFormat)
            }
            className="h-11 rounded-lg border border-slate-200 bg-white px-3 text-sm font-bold text-slate-800"
          >
            <option value="png">PNG</option>
            <option value="jpg">JPG</option>
          </select>
        </label>
        <button
          type="button"
          onClick={() => handleDownloadImage(exportFormat)}
          disabled={exporting || invalidVisualCount > 0}
          className="rounded-lg border border-slate-200 bg-white px-6 py-3 text-sm font-bold text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:bg-slate-100 disabled:text-slate-400"
        >
          {exporting
            ? `${exportFormat.toUpperCase()} ${exportStage === "finalizing" ? "최종본 준비 중..." : exportStage === "rendering" ? "이미지 생성 중..." : exportStage === "downloading" ? "다운로드 중..." : exportStage === "saving" ? "저장 중..." : "처리 중..."}`
            : `${exportFormat.toUpperCase()}로 저장하기`}
        </button>
        <button
          type="button"
          onClick={() => router.push(`/workspace/projects/${projectId}/page-editor?mode=review`)}
          className="rounded-lg bg-emerald-600 px-6 py-3 text-sm font-bold text-white hover:bg-emerald-700"
        >
          검수하며 다듬기
        </button>
        {exportError ? <p className="absolute bottom-full mb-2 rounded-lg bg-rose-50 px-4 py-2 text-xs font-bold text-rose-700">{exportError}</p> : null}
      </footer>
    </div>
  );
}

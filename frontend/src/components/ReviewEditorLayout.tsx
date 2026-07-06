"use client";

import React, { useEffect, useState } from "react";
import GeneratedPageOutline, { OutlineSection } from "./GeneratedPageOutline";
import FigmaExportDialog from "./figma/FigmaExportDialog";
import { apiUrl } from "@/lib/api";

interface PageData {
  id: string;
  project_id: string;
  theme_color: string;
  font_family: string;
  sections: OutlineSection[];
}

interface ProjectAsset {
  id: string;
  filename: string;
  file_path: string;
  mime_type: string;
  source_type: string;
}

interface ReviewEditorLayoutProps {
  projectId: string;
  projectName?: string;
  page: PageData;
  selectedSectionId: string | null;
  onSelectSection: (id: string | null) => void;
  projectAssets: ProjectAsset[];
  rightPanel: React.ReactNode;
  onBack: () => void;
  isFinalVersion?: boolean;
  modeTitle?: string;
  modeDescription?: string;
}

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

function resolveAssetUrl(asset: ProjectAsset): string {
  if (asset.file_path.startsWith("http")) return asset.file_path;
  return apiUrl(`/api/v1/files/assets/${asset.id}`);
}

const MOCK_HEADERS = {
  "X-Mock-User-Id": "00000000-0000-0000-0000-000000000001",
  "X-Mock-Workspace-Id": "00000000-0000-0000-0000-000000000002",
};

export default function ReviewEditorLayout({
  projectId,
  projectName,
  page,
  selectedSectionId,
  onSelectSection,
  projectAssets,
  rightPanel,
  onBack,
  isFinalVersion = false,
  modeTitle = "검수하며 다듬기",
  modeDescription = "문구와 이미지 후보를 빠르게 확인하고 업로드 전 오류를 줄입니다.",
}: ReviewEditorLayoutProps) {
  const visibleSections = page.sections.filter((section) => section.is_visible);
  
  const [canExport, setCanExport] = useState(true);
  const [isFigmaOpen, setIsFigmaOpen] = useState(false);
  const [, setComplianceIssues] = useState<unknown[]>([]);

  useEffect(() => {
    const fetchCompliance = async () => {
      try {
        const res = await fetch(apiUrl(`/api/v1/projects/${projectId}/page/compliance`), {
          headers: MOCK_HEADERS
        });
        if (res.ok) {
          const data = await res.json();
          setCanExport(data.can_export ?? true);
          setComplianceIssues(data.issues ?? []);
        }
      } catch (err) {
        console.error("Compliance fetch failed", err);
      }
    };
    fetchCompliance();
  }, [projectId]);

  return (
    <div className="min-h-screen bg-slate-50 text-slate-800" data-project-id={projectId}>
      <header className="sticky top-0 z-30 border-b border-slate-200 bg-white/95 backdrop-blur px-8 py-4">
        <div className="mx-auto flex max-w-7xl items-center justify-between gap-4">
          <div className="flex items-center gap-4">
            <button
              type="button"
              onClick={onBack}
              className="rounded-full border border-slate-200 bg-white px-4 py-2 text-sm font-bold text-slate-600 hover:border-emerald-200 hover:text-emerald-700"
            >
              결과 화면으로
            </button>
            <div>
              <p className="text-xs font-bold text-emerald-700">{modeTitle}</p>
              <h1 className="text-xl font-extrabold text-slate-950">{modeTitle}</h1>
              <p className="mt-1 text-xs font-medium text-slate-500">{modeDescription}</p>
              {projectName ? (
                <p className="mt-1 text-xs font-semibold text-slate-400">{projectName}</p>
              ) : null}
            </div>
          </div>
          
          <div className="flex items-center gap-4">
            <span className="rounded-full bg-emerald-50 px-3 py-1 text-xs font-extrabold text-emerald-700 border border-emerald-100">
              {isFinalVersion ? "최종본 지정됨" : "초안 검수 중"}
            </span>
            <button
              type="button"
              disabled={!canExport}
              onClick={() => setIsFigmaOpen(true)}
              className={`px-5 py-2.5 rounded-xl text-xs font-extrabold transition-all shadow-md ${
                canExport 
                  ? "bg-emerald-600 hover:bg-emerald-700 text-white shadow-emerald-600/10 cursor-pointer"
                  : "bg-slate-200 text-slate-400 cursor-not-allowed shadow-none"
              }`}
            >
              Figma로 내보내기
            </button>
          </div>
        </div>
      </header>

      <main className="mx-auto grid max-w-7xl grid-cols-[320px_minmax(360px,1fr)_360px] gap-6 px-8 py-8">
        <GeneratedPageOutline
          sections={page.sections}
          selectedSectionId={selectedSectionId}
          onSelectSection={onSelectSection}
          isFinalVersion={isFinalVersion}
        />

        <section className="flex flex-col items-center gap-5">
          <div className="text-center">
            <p className="text-xs font-bold text-emerald-700">구매자 화면 미리보기</p>
            <h2 className="text-lg font-extrabold text-slate-900">실제 상세페이지 흐름</h2>
          </div>

          {!canExport && (
            <div className="w-full max-w-[390px] bg-rose-50 border border-rose-200 rounded-2xl p-4 flex flex-col space-y-1">
              <h4 className="text-xs font-extrabold text-rose-800">⚠️ 출력 전 확인이 필요합니다</h4>
              <p className="text-[11px] font-semibold text-rose-600 leading-relaxed">
                상품 이미지 검수 또는 누락된 이미지를 확인해 주세요.
              </p>
            </div>
          )}

          <div className="w-[390px] max-w-full overflow-hidden rounded-[38px] border-[10px] border-white bg-white shadow-2xl ring-1 ring-slate-200">
            <div className="flex h-7 items-center justify-between bg-white px-7 text-[10px] font-bold text-slate-400 border-b border-slate-100">
              <span>10:30</span>
              <span className="h-3 w-20 rounded-full bg-slate-200" />
              <span>LTE</span>
            </div>
            <div className="max-h-[700px] overflow-y-auto bg-white">
              {visibleSections.map((section) => {
                const asset = projectAssets.find((item) => item.id === section.image_asset_id);
                const isSelected = selectedSectionId === section.id;

                return (
                  <button
                    key={section.id}
                    type="button"
                    onClick={() => onSelectSection(section.id)}
                    className={`block w-full border-b border-slate-100 p-6 text-left transition-all ${
                      isSelected ? "bg-emerald-50/70" : "bg-white hover:bg-slate-50"
                    }`}
                  >
                    <span className="text-[10px] font-extrabold uppercase tracking-[0.2em] text-emerald-700">
                      {section.section_type.replace(/_/g, " ")}
                    </span>
                    <h3 className="mt-2 text-base font-extrabold leading-snug text-slate-950">{section.title}</h3>
                    <p className="mt-2 text-sm leading-relaxed text-slate-600">{section.body_copy}</p>
                    <div className="mt-4 overflow-hidden rounded-2xl border border-slate-100 bg-slate-50 aspect-video flex items-center justify-center">
                      {asset ? (
                        <div className="relative h-full w-full">
                          <img src={resolveAssetUrl(asset)} alt={section.title} className="h-full w-full object-cover" />
                          <span className="absolute right-3 top-3 rounded-full bg-emerald-600 px-2 py-1 text-[10px] font-extrabold text-white">
                            출처: {sourceLabel(asset.source_type)}
                          </span>
                        </div>
                      ) : section.image_asset_id && (
                        section.image_asset_id.startsWith("mock-") ||
                        section.image_asset_id.startsWith("candidate-") ||
                        section.image_asset_id === "asset-selected" ||
                        section.image_asset_id === "asset-default"
                      ) ? (
                        <div className="relative h-full w-full">
                          <img src={apiUrl(`/api/v1/files/assets/${section.image_asset_id}`)} alt={section.title} className="h-full w-full object-cover" />
                          <span className="absolute right-3 top-3 rounded-full bg-emerald-600 px-2 py-1 text-[10px] font-extrabold text-white">
                            출처: {sourceLabel(section.image_asset_id.includes("uploaded") ? "uploaded" : "mock-generated")}
                          </span>
                        </div>
                      ) : (
                        <span className="text-xs font-bold text-amber-600">이미지 누락</span>
                      )}
                    </div>

                  </button>
                );
              })}
            </div>
          </div>
        </section>

        <aside className="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm">
          {rightPanel}
        </aside>
      </main>

      <FigmaExportDialog
        isOpen={isFigmaOpen}
        onClose={() => setIsFigmaOpen(false)}
        projectId={projectId}
        backendUrl="http://localhost:8001/api/v1"
        headers={MOCK_HEADERS}
      />
    </div>
  );
}

"use client";

import React, { useEffect } from "react";
import { apiUrl } from "@/lib/api";

export interface DetailPageImageCandidate {
  candidate_id: string;
  slot_id: string;
  asset_id: string | null;
  source_type: string;
  label: string;
  is_recommended: boolean;
  needs_identity_review: boolean;
}

export interface DetailPageSection {
  id?: string;
  section_type: string;
  title?: string | null;
  body?: string | null;
  body_copy?: string | null;
  image_asset_id?: string | null;
  sort_order: number;
  is_visible?: boolean;
  image_candidates?: DetailPageImageCandidate[];
}

export interface DetailPageData {
  id?: string;
  project_id: string;
  theme_color: string;
  font_family: string;
  sections: DetailPageSection[];
}

export interface DetailPageAsset {
  id: string;
  filename: string;
  file_path?: string;
  mime_type: string;
  source_type: string;
}

interface DetailPageDocumentProps {
  page: DetailPageData;
  assets: DetailPageAsset[];
  exportMode?: boolean;
}

function sourceLabel(sourceType: string): string {
  switch (sourceType) {
    case "uploaded":
      return "직접 업로드";
    case "url-extracted":
    case "url-imported":
      return "URL 추출";
    case "real-generated":
    case "ai-generated":
      return "AI 생성";
    case "generation-skipped":
      return "생성 생략";
    case "blocked_cost_approval":
      return "승인 필요";
    default:
      return sourceType || "출처 없음";
  }
}

export function detailAssetUrl(asset: DetailPageAsset | { id: string; file_path?: string }): string {
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

export default function DetailPageDocument({ page, assets, exportMode = false }: DetailPageDocumentProps) {
  const visibleSections = page.sections
    .filter((section) => section.is_visible !== false)
    .sort((a, b) => a.sort_order - b.sort_order);

  useEffect(() => {
    if (!exportMode) return;

    let cancelled = false;
    const markReady = async () => {
      await document.fonts.ready;
      const images = Array.from(document.images);
      await Promise.all(
        images.map((image) => {
          if (image.complete) return Promise.resolve();
          return new Promise<void>((resolve) => {
            image.addEventListener("load", () => resolve(), { once: true });
            image.addEventListener("error", () => resolve(), { once: true });
          });
        })
      );
      if (!cancelled) {
        document.documentElement.dataset.exportReady = "true";
      }
    };

    markReady();
    return () => {
      cancelled = true;
      delete document.documentElement.dataset.exportReady;
    };
  }, [exportMode]);

  return (
    <article
      className="mx-auto w-full max-w-[760px] overflow-hidden border border-slate-200 bg-white shadow-sm"
      style={{ fontFamily: page.font_family }}
      data-detail-page-document="true"
    >
      {visibleSections.map((section, index) => {
        const matchedAsset = assets.find((asset) => asset.id === section.image_asset_id);
        const imageSrc = matchedAsset
          ? detailAssetUrl(matchedAsset)
          : section.image_asset_id
            ? detailAssetUrl({ id: section.image_asset_id })
            : null;
        const title = section.title || "";
        const body = section.body_copy || section.body || "";
        const theme = sectionTheme(section.section_type, index);

        return (
          <section
            key={section.id || `${section.section_type}-${index}`}
            className={theme.section}
            data-detail-page-section="true"
          >
            <p className={`text-[11px] font-extrabold uppercase ${theme.eyebrow}`}>
              {section.section_type.replace("_", " ")}
            </p>
            <h3 className={`mx-auto mt-3 max-w-2xl text-2xl font-extrabold leading-snug sm:text-3xl ${theme.title}`}>
              {title}
            </h3>
            <p className={`mx-auto mt-4 max-w-2xl text-sm leading-7 sm:text-base ${theme.body}`}>
              {body}
            </p>
            {section.section_type !== "product_information" ? (
              imageSrc ? (
                <figure className={`relative mt-9 overflow-hidden ${theme.figure}`}>
                  <img src={imageSrc} alt={title} className="aspect-[4/3] w-full object-cover" />
                  {!exportMode ? (
                    <figcaption className="absolute right-3 top-3 rounded-full bg-emerald-700 px-3 py-1 text-[10px] font-bold text-white">
                      {sourceLabel(matchedAsset?.source_type || "ai-generated")}
                    </figcaption>
                  ) : null}
                </figure>
              ) : (
                <div className="mt-8 flex aspect-[4/3] items-center justify-center border border-amber-200 bg-amber-50 text-sm font-bold text-amber-700">
                  이 섹션은 이미지 확인이 필요합니다.
                </div>
              )
            ) : null}
          </section>
        );
      })}
    </article>
  );
}

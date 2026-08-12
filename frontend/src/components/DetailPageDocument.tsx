"use client";

import React, { useEffect, useState } from "react";
import { apiUrl } from "@/lib/api";
import { waitForExportAssets } from "@/lib/exportReadiness";
import ImageSectionVisual from "@/components/detail-page/ImageSectionVisual";
import HtmlGraphicVisual from "@/components/detail-page/HtmlGraphicVisual";
import ComposedProductVisual from "@/components/detail-page/ComposedProductVisual";
import { validateSectionVisual } from "@/components/detail-page/types";
import type { VisualKind, DetailPageSectionVisual } from "@/components/detail-page/types";

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
  image_asset_content_hash?: string | null;
  visual_kind?: VisualKind | null;
  visual_payload?: Record<string, unknown> | null;
  sort_order: number;
  is_visible?: boolean;
  image_candidates?: DetailPageImageCandidate[];
  associated_fact_ids?: string[];
  associated_fact_texts?: string[];
}

export interface DetailPageData {
  id?: string;
  project_id: string;
  theme_color: string;
  font_family: string;
  brand_assets?: {
    logo?: DetailPageBrandAsset | null;
    watermark?: DetailPageBrandAsset | null;
  };
  sections: DetailPageSection[];
}

export interface DetailPageBrandAsset {
  asset_id: string;
  asset_content_hash: string;
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
  editingSectionId?: string | null;
  inlineDraft?: { title: string; body_copy: string } | null;
  inlineSaving?: boolean;
  onStartInlineEdit?: (section: DetailPageSection) => void;
  onInlineDraftChange?: (field: "title" | "body_copy", value: string) => void;
  onSaveInlineEdit?: () => void;
  onCancelInlineEdit?: () => void;
}

function sourceLabel(sourceType: string): string {
  switch (sourceType) {
    case "uploaded":
    case "sourced":
    case "self_shot":
      return "직접 업로드";
    case "url-extracted":
    case "url-imported":
      return "URL 추출";
    case "real-generated":
    case "ai-generated":
      return "AI 생성";
    case "local_upscaled":
      return "로컬 고화질 보정";
    case "generation-skipped":
      return "생성 생략";
    case "blocked_cost_approval":
      return "승인 필요";
    default:
      return sourceType || "출처 없음";
  }
}

export function detailAssetUrl(
  asset: DetailPageAsset | { id: string; file_path?: string },
  expectedContentHash?: string | null,
): string {
  if (!expectedContentHash && asset.file_path && asset.file_path.startsWith("http")) {
    return asset.file_path;
  }
  const url = apiUrl(`/api/v1/files/assets/${asset.id}`);
  return expectedContentHash
    ? `${url}?expected_content_hash=${encodeURIComponent(expectedContentHash)}`
    : url;
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

function parseBodyBlock(block: string): { type: "list"; items: string[] } | { type: "paragraph"; lines: string[] } {
  const lines = block
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
  const bulletItems = lines
    .map((line) => line.match(/^[-*•]\s+(.+)$/) || line.match(/^\d+[.)]\s+(.+)$/))
    .filter((match): match is RegExpMatchArray => Boolean(match))
    .map((match) => match[1].trim());

  if (lines.length > 0 && bulletItems.length === lines.length) {
    return { type: "list", items: bulletItems };
  }
  return { type: "paragraph", lines };
}

function FormattedBodyCopy({ body, className }: { body: string; className: string }) {
  const blocks = body
    .replace(/\r\n/g, "\n")
    .replace(/\r/g, "\n")
    .split(/\n\s*\n/)
    .map((block) => block.trim())
    .filter(Boolean)
    .map(parseBodyBlock);

  if (blocks.length === 0) return null;

  return (
    <div className={`mx-auto mt-4 max-w-2xl space-y-4 text-sm leading-7 sm:text-base ${className}`}>
      {blocks.map((block, index) => {
        if (block.type === "list") {
          return (
            <ul
              key={`list-${index}`}
              className="mx-auto max-w-xl list-disc space-y-2 pl-5 text-left marker:text-emerald-600"
            >
              {block.items.map((item, itemIndex) => (
                <li key={`${index}-${itemIndex}`}>{item}</li>
              ))}
            </ul>
          );
        }

        return (
          <p key={`paragraph-${index}`} className="whitespace-pre-line">
            {block.lines.join("\n")}
          </p>
        );
      })}
    </div>
  );
}

export default function DetailPageDocument({
  page, assets, exportMode = false, editingSectionId, inlineDraft, inlineSaving = false,
  onStartInlineEdit, onInlineDraftChange, onSaveInlineEdit, onCancelInlineEdit,
}: DetailPageDocumentProps) {
  const [exportErrors, setExportErrors] = useState<string[]>([]);
  const visibleSections = page.sections
    .filter((section) => section.is_visible !== false)
    .filter((section) => {
      if (section.section_type !== "pre_purchase") return true;
      const payload = (section.visual_payload || {}) as Record<string, unknown>;
      const items = Array.isArray(payload.items) ? payload.items : [];
      return !items.some((item) => {
        if (!item || typeof item !== "object") return false;
        const record = item as Record<string, unknown>;
        return record.kind === "seller_action" || record.verification_status === "action_required";
      });
    })
    .sort((a, b) => a.sort_order - b.sort_order);
  const logo = page.brand_assets?.logo;
  const watermark = page.brand_assets?.watermark;

  useEffect(() => {
    if (!exportMode) return;

    let cancelled = false;
    const markReady = async () => {
      const result = await waitForExportAssets();
      if (!cancelled) {
        document.documentElement.dataset.exportReady = result.ok ? "true" : "error";
        document.documentElement.dataset.exportErrors = JSON.stringify(result.errors);
        setExportErrors(result.ok ? [] : result.errors);
      }
    };

    markReady();
    return () => {
      cancelled = true;
      setExportErrors([]);
      delete document.documentElement.dataset.exportReady;
      delete document.documentElement.dataset.exportErrors;
    };
  }, [exportMode]);

  return (
    <article
      className="relative mx-auto w-full max-w-[760px] overflow-hidden border border-slate-200 bg-white shadow-sm"
      style={{ fontFamily: page.font_family }}
      data-detail-page-document="true"
    >
      {logo ? (
        <header className="flex items-center bg-white px-6 py-4" data-detail-page-brand-logo="true">
          <img
            src={detailAssetUrl({ id: logo.asset_id }, logo.asset_content_hash)}
            alt="브랜드 로고"
            className="max-h-14 max-w-[180px] object-contain"
            data-asset-id={logo.asset_id}
            data-asset-content-hash={logo.asset_content_hash}
          />
        </header>
      ) : null}
      {exportMode && exportErrors.length > 0 ? (
        <div
          role="alert"
          className="border-b border-rose-200 bg-rose-50 px-6 py-4 text-sm font-bold text-rose-700"
        >
          필수 이미지를 불러오지 못했습니다. 이미지를 확인한 뒤 다시 다운로드해 주세요.
        </div>
      ) : null}
      {visibleSections.map((section, index) => {
        const matchedAsset = assets.find((asset) => asset.id === section.image_asset_id);
        const isLegacyMockVisual =
          matchedAsset?.source_type === "mock-generated" ||
          Boolean(section.image_asset_id?.startsWith("mock-"));
        const imageSrc = isLegacyMockVisual
          ? null
          : matchedAsset
          ? detailAssetUrl(matchedAsset, section.image_asset_content_hash)
          : section.image_asset_id
            ? detailAssetUrl({ id: section.image_asset_id }, section.image_asset_content_hash)
            : null;
        const title = section.title || "";
        const body = section.body_copy || section.body || "";
        const theme = sectionTheme(section.section_type, index);

        const visualKind = section.visual_kind;
        const isHtmlGraphic = visualKind === "html_graphic";
        const isImage = visualKind === "image";
        const isComposedProduct = visualKind === "composed_product";
        const visualIssues = validateSectionVisual(section as unknown as DetailPageSectionVisual);
        const payload = (section.visual_payload || {}) as Record<string, unknown>;
        const layoutVariant = payload.layout_variant as string | undefined;
        const isStructuredHtmlGraphic =
          isHtmlGraphic &&
          new Set([
            "comparison_cards",
            "benefit_cards",
            "numeric_highlights",
            "spec_table",
            "steps",
            "checklist",
          ]).has(layoutVariant || "");
        const isInlineEditing = !exportMode && section.id === editingSectionId && inlineDraft;

        return (
          <section
            key={section.id || `${section.section_type}-${index}`}
            id={section.id ? `section-${section.id}` : undefined}
            className={theme.section}
            data-detail-page-section="true"
          >
            {!exportMode && onStartInlineEdit ? (
              <div className="mb-3 flex justify-end">
                <button
                  type="button"
                  onClick={() => onStartInlineEdit(section)}
                  className="rounded-md border border-current/20 bg-white/80 px-2.5 py-1 text-[11px] font-bold text-emerald-800 shadow-sm"
                >
                  문구 수정
                </button>
              </div>
            ) : null}
            {!isComposedProduct ? (
              <>
                <p className={`text-[11px] font-extrabold uppercase ${theme.eyebrow}`}>
                  {section.section_type.replace("_", " ")}
                </p>
                {isInlineEditing ? (
                  <div className="mx-auto mt-3 max-w-2xl rounded-xl border border-emerald-300 bg-white p-4 text-left shadow-lg">
                    <label className="block text-xs font-bold text-slate-700">제목<input value={inlineDraft.title} onChange={(event) => onInlineDraftChange?.("title", event.target.value)} className="mt-1 w-full rounded border border-slate-300 px-3 py-2 text-base font-bold text-slate-900" /></label>
                    <label className="mt-3 block text-xs font-bold text-slate-700">본문<textarea value={inlineDraft.body_copy} onChange={(event) => onInlineDraftChange?.("body_copy", event.target.value)} className="mt-1 min-h-24 w-full rounded border border-slate-300 px-3 py-2 text-sm leading-6 text-slate-800" /></label>
                    {section.associated_fact_texts?.length ? <div className="mt-3 rounded bg-emerald-50 p-2 text-[11px] leading-5 text-emerald-950">연결된 사실: {section.associated_fact_texts.join(" · ")}</div> : <p className="mt-3 text-[11px] text-slate-500">이 문구에는 연결된 수치 사실이 없습니다.</p>}
                    <div className="mt-3 flex justify-end gap-2"><button type="button" onClick={onCancelInlineEdit} className="rounded border border-slate-300 px-3 py-2 text-xs font-bold text-slate-700">취소</button><button type="button" disabled={inlineSaving} onClick={onSaveInlineEdit} className="rounded bg-emerald-600 px-3 py-2 text-xs font-bold text-white disabled:bg-slate-300">{inlineSaving ? "저장 중…" : "저장"}</button></div>
                  </div>
                ) : (
                  <h3 className={`mx-auto mt-3 max-w-2xl text-2xl font-extrabold leading-snug sm:text-3xl ${theme.title}`}>
                    {title}
                  </h3>
                )}
                {!isInlineEditing && !isStructuredHtmlGraphic ? (
                  <FormattedBodyCopy body={body} className={theme.body} />
                ) : null}
              </>
            ) : null}
            {isComposedProduct ? (
                <ComposedProductVisual
                  section={section as unknown as DetailPageSectionVisual}
                  imageSrc={imageSrc}
                  matchedAssetLabel={matchedAsset ? sourceLabel(matchedAsset.source_type) : undefined}
                  exportMode={exportMode}
                />
              ) : isHtmlGraphic ? (
                <HtmlGraphicVisual section={section as unknown as DetailPageSectionVisual} />
              ) : isImage || imageSrc || isLegacyMockVisual ? (
                <ImageSectionVisual
                  section={section as unknown as DetailPageSectionVisual}
                  imageSrc={imageSrc}
                  matchedAssetLabel={
                    matchedAsset
                      ? sourceLabel(matchedAsset.source_type)
                      : undefined
                  }
                  exportMode={exportMode}
                />
              ) : visualIssues.length > 0 ? (
                <div
                  className="mt-8 flex aspect-[4/3] items-center justify-center border border-amber-200 bg-amber-50 text-sm font-bold text-amber-700"
                  data-section-visual="image"
                >
                  이미지 확인이 필요합니다
                </div>
              ) : null}
          </section>
        );
      })}
      {watermark ? (
        <aside
          className="pointer-events-none absolute bottom-4 right-4 z-10 opacity-20"
          data-detail-page-brand-watermark="true"
        >
          <img
            src={detailAssetUrl({ id: watermark.asset_id }, watermark.asset_content_hash)}
            alt="브랜드 워터마크"
            className="max-h-16 max-w-[132px] object-contain"
            data-asset-id={watermark.asset_id}
            data-asset-content-hash={watermark.asset_content_hash}
          />
        </aside>
      ) : null}
    </article>
  );
}

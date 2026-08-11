"use client";

import React, { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { apiUrl } from "@/lib/api";
import DetailPageDocument from "@/components/DetailPageDocument";
import ExportReadinessWarning from "@/components/ExportReadinessWarningV2";
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
  status?: string | null;
  error_code?: string | null;
  warnings?: string[] | null;
  quality_warnings?: string[] | null;
  provider?: string | null;
  model?: string | null;
  source_asset_id?: string | null;
  cutout_status?: string | null;
  background_removed?: boolean | null;
  product_identity_preserved?: boolean | null;
  usage_status?: "reference_only" | "seller_owned" | "ai_generated" | "derived_graphic" | "blocked";
  eligible?: boolean;
  block_reason?: string | null;
  asset_role?: string | null;
  recommendation_reason?: string | null;
}

interface PageSection {
  id: string;
  section_type: string;
  title: string;
  body_copy: string;
  image_asset_id: string | null;
  visual_kind?: "image" | "html_graphic" | "composed_product" | null;
  visual_payload?: Record<string, unknown> | null;
  sort_order: number;
  is_visible: boolean;
  associated_fact_ids?: string[];
  associated_fact_texts?: string[];
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
  usage_status?: "reference_only" | "seller_owned" | "ai_generated" | "derived_graphic" | "blocked";
  source_asset_id?: string | null;
  cutout_status?: string | null;
  background_removed?: boolean | null;
  product_identity_preserved?: boolean | null;
  asset_role?: string;
  role_confidence?: number;
  role_source?: string;
  quality_status?: "usable" | "warning" | "rejected";
  identity_status?: "confirmed" | "needs_review";
  width?: number | null;
  height?: number | null;
  image_format?: string | null;
  quality_warnings?: string[];
  ocr_text?: string | null;
  safe_crop_status?: "safe" | "needs_review" | "not_recommended";
  is_representative?: boolean;
  representative_source?: "auto" | "manual";
  classification_version?: number;
}

interface AssetInspection {
  id: string;
  asset_id: string;
  analysis_version: number;
  status: "pending" | "completed" | "failed";
  analyzer_version: string;
  asset_role?: string | null;
  rights_status?: string | null;
  final_output_eligible: boolean;
  duplicate_asset_ids: string[];
  warnings: string[];
  ocr_blocks: Array<{
    text: string;
    language: string;
    source?: string;
    confidence?: number | null;
    bbox?: { x: number; y: number; width: number; height: number; precision?: string } | null;
  }>;
  translation_blocks: Array<{
    source_text: string;
    translated_text: string;
    translation_status: string;
    translation_provider?: string;
    bbox?: { x: number; y: number; width: number; height: number; precision?: string } | null;
    preserved_numeric_values: string[];
  }>;
  numeric_evidence: string[];
  analysis_metadata?: {
    text_density?: number;
    text_density_status?: string;
    ai_scene_reference_suitability?: string;
    identity_status?: string;
    role_source?: string;
  };
  created_at?: string;
  completed_at?: string | null;
}

interface AssetUnderstandingReadiness {
  ready: boolean;
  blockers: Array<{ asset_id: string; code: string; message: string }>;
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

interface ChannelPreset {
  key: "coupang" | "smartstore";
  label: string;
  version: string;
  width: number;
  max_segment_height: number;
  default_format: ExportImageFormat;
}

interface FinalPageVersion {
  id: string;
}

interface ContentQualityIssue {
  section_id: string;
  code: string;
  severity: "blocker" | "review" | "recommendation";
  message: string;
  resolution: string;
  asset_id?: string | null;
}

interface ContentQualityReport {
  ready_for_sale: boolean;
  seller_confirmed_usage?: boolean;
  seller_confirmed_usage_count?: number;
  product_name: string;
  export_slug: string;
  blockers: ContentQualityIssue[];
  reviews: ContentQualityIssue[];
  recommendations: ContentQualityIssue[];
  section_copy_quality_codes?: Record<string, string[]>;
}

type ExportImageFormat = "png" | "jpg";

function slugify(text: string): string {
  return text
    .toString()
    .toLowerCase()
    .replace(/\s+/g, "-")
    .replace(/[^\wㄱ-ㅎㅏ-ㅣ가-힣\-]+/g, "")
    .replace(/\-\-+/g, "-")
    .replace(/^-+/, "")
    .replace(/-+$/, "");
}

function downloadBlob(blob: Blob, filename: string) {
  const blobUrl = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = blobUrl;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(blobUrl), 1000);
}

interface UpscaleComparison {
  source: ProjectAsset;
  enhanced: ProjectAsset;
}

const MOCK_HEADERS: Record<string, string> = {};

// eslint-disable-next-line @typescript-eslint/no-unused-vars
function sourceLabel(sourceType: string): string {
  switch (sourceType) {
    case "uploaded":
    case "sourced":
    case "self_shot":
      return "직접 업로드";
    case "url-extracted":
    case "url-imported":
      return "URL 추출";
    case "missing-image":
      return "사진 필요";
    case "mock-generated":
      return "AI 모의 생성";
    case "real-generated":
      return "AI 생성 이미지";
    case "ai-generated":
    case "ai_generated":
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

function readableSourceLabel(sourceType: string): string {
  switch (sourceType) {
    case "self_shot":
    case "uploaded":
    case "sourced":
      return "직접 업로드";
    case "url-extracted":
    case "url-imported":
      return "URL 추출";
    case "missing-image":
      return "사진 필요";
    case "ai_corrected":
      return "실제 상품 누끼 사용";
    case "local_upscaled":
      return "로컬 고화질 보정";
    case "mock-generated":
      return "AI 모의 생성";
    case "real-generated":
      return "AI 생성 이미지";
    case "ai-generated":
    case "ai_generated":
      return "AI 생성";
    case "generation-skipped":
      return "HTML 그래픽";
    case "blocked_cost_approval":
      return "이미지 생성 승인 필요";
    case "needs_review":
      return "상품 정체성 검수 필요";
    default:
      return sourceType || "출처 없음";
  }
}

function assetSourceLabel(asset?: ProjectAsset | null): string {
  if (!asset) return "사진 필요";
  if (asset.source_type === "local_upscaled") {
    return "자동 고화질 보정본";
  }
  if (asset.background_removed || asset.cutout_status === "completed" || asset.source_type === "ai_corrected") {
    return "실제 상품 누끼 사용";
  }
  if (asset.source_asset_id) {
    return "AI 배경 합성";
  }
  if (asset.product_identity_preserved === false) {
    return "AI 보정 후보 - 검수 필요";
  }
  return readableSourceLabel(asset.source_type);
}

function candidateSourceLabel(candidate: ImageCandidate, linkedAsset?: ProjectAsset | null): string {
  if (linkedAsset) {
    return assetSourceLabel(linkedAsset);
  }
  if (candidate.background_removed || candidate.cutout_status === "completed" || candidate.source_type === "ai_corrected") {
    return "실제 상품 누끼 사용";
  }
  if (candidate.source_asset_id) {
    return "AI 배경 합성";
  }
  if (candidate.needs_identity_review || candidate.product_identity_preserved === false) {
    return "AI 보정 후보 - 검수 필요";
  }
  return readableSourceLabel(candidate.source_type);
}

function usageStatusLabel(status?: ImageCandidate["usage_status"]): string {
  if (status === "seller_owned") return "판매자 보유·사용 가능";
  if (status === "reference_only") return "참고 전용·권한 확인 필요";
  if (status === "blocked") return "최종 사용 차단";
  if (status === "ai_generated") return "AI 생성";
  if (status === "derived_graphic") return "가공 그래픽";
  return "권한 상태 확인 필요";
}

function candidateWarningLabel(candidate: ImageCandidate): string | null {
  if (candidate.error_code === "LOW_QUALITY_HERO_SOURCE") {
    return "저화질 이미지라 HERO 자동 적용에서 제외되었습니다.";
  }
  if (candidate.status === "failed") {
    return candidate.error_code
      ? `\uc774\ubbf8\uc9c0 \uc0dd\uc131 \uc2e4\ud328: ${candidate.error_code}`
      : "\uc774\ubbf8\uc9c0 \uc0dd\uc131 \uc2e4\ud328";
  }
  if (candidate.needs_identity_review || candidate.product_identity_preserved === false) {
    return "상품 형태 변경 가능성 있음";
  }
  return null;
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
  const [assetInspections, setAssetInspections] = useState<AssetInspection[]>([]);
  const [assetReadiness, setAssetReadiness] = useState<AssetUnderstandingReadiness | null>(null);
  const [contentQuality, setContentQuality] = useState<ContentQualityReport | null>(null);
  const [acknowledgingQuality, setAcknowledgingQuality] = useState<string | null>(null);
  const [inspectingAssets, setInspectingAssets] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);
  const [exportFormat, setExportFormat] = useState<ExportImageFormat>("png");
  const [exportPreset, setExportPreset] = useState<"coupang" | "smartstore">("smartstore");
  const [channelPresets, setChannelPresets] = useState<ChannelPreset[]>([]);
  const [downloadPackage, setDownloadPackage] = useState(true);
  const [exportStage, setExportStage] = useState<ExportStage>("idle");
  const [exportBlockers, setExportBlockers] = useState<Array<{ section_id: string; code: string; message: string }>>([]);
  const [imageActionError, setImageActionError] = useState<string | null>(null);
  const [regeneratingCandidateId, setRegeneratingCandidateId] = useState<string | null>(null);
  const [upscalingAssetId, setUpscalingAssetId] = useState<string | null>(null);
  const [applyingUpscale, setApplyingUpscale] = useState(false);
  const [upscaleComparison, setUpscaleComparison] = useState<UpscaleComparison | null>(null);
  const [inlineEditingSectionId, setInlineEditingSectionId] = useState<string | null>(null);
  const [inlineDraft, setInlineDraft] = useState<{ title: string; body_copy: string } | null>(null);
  const [inlineSaving, setInlineSaving] = useState(false);

  useEffect(() => {
    const loadData = async () => {
      try {
        setLoading(true);
        const [projectRes, pageRes, assetsRes, inspectionsRes, readinessRes, qualityRes] = await Promise.all([
          fetch(apiUrl(`/api/v1/projects/${projectId}`), { headers: MOCK_HEADERS, credentials: "include" }),
          fetch(apiUrl(`/api/v1/projects/${projectId}/page`), { headers: MOCK_HEADERS, credentials: "include" }),
          fetch(apiUrl(`/api/v1/projects/${projectId}/assets`), { headers: MOCK_HEADERS, credentials: "include" }),
          fetch(apiUrl(`/api/v1/projects/${projectId}/asset-inspections`), { headers: MOCK_HEADERS, credentials: "include" }),
          fetch(apiUrl(`/api/v1/projects/${projectId}/asset-understanding-readiness`), { headers: MOCK_HEADERS, credentials: "include" }),
          fetch(apiUrl(`/api/v1/projects/${projectId}/page/content-quality`), { headers: MOCK_HEADERS, credentials: "include" }),
        ]);

        if (!projectRes.ok) throw new Error("프로젝트 정보를 불러오지 못했습니다.");
        if (!pageRes.ok) throw new Error("생성된 상세페이지를 불러오지 못했습니다.");

        setProject(await projectRes.json());
        setPageData(await pageRes.json());
        setAssets(assetsRes.ok ? await assetsRes.json() : []);
        setAssetInspections(inspectionsRes.ok ? await inspectionsRes.json() : []);
        setAssetReadiness(readinessRes.ok ? await readinessRes.json() : null);
        setContentQuality(qualityRes.ok ? await qualityRes.json() : null);
      } catch (err) {
        console.error(err);
        setError(err instanceof Error ? err.message : "상세페이지 초안을 불러오는 중 오류가 발생했습니다.");
      } finally {
        setLoading(false);
      }
    };

    loadData();
  }, [projectId]);

  const refreshPageAndAssets = useCallback(async () => {
    const [pageRes, assetsRes, inspectionsRes, readinessRes, qualityRes] = await Promise.all([
      fetch(apiUrl(`/api/v1/projects/${projectId}/page`), { headers: MOCK_HEADERS, credentials: "include" }),
      fetch(apiUrl(`/api/v1/projects/${projectId}/assets`), { headers: MOCK_HEADERS, credentials: "include" }),
      fetch(apiUrl(`/api/v1/projects/${projectId}/asset-inspections`), { headers: MOCK_HEADERS, credentials: "include" }),
      fetch(apiUrl(`/api/v1/projects/${projectId}/asset-understanding-readiness`), { headers: MOCK_HEADERS, credentials: "include" }),
      fetch(apiUrl(`/api/v1/projects/${projectId}/page/content-quality`), { headers: MOCK_HEADERS, credentials: "include" }),
    ]);
    if (!pageRes.ok) {
      throw new Error("\uc774\ubbf8\uc9c0 \uc0dd\uc131 \ud6c4 \uc0c1\uc138\ud398\uc774\uc9c0\ub97c \ub2e4\uc2dc \ubd88\ub7ec\uc624\uc9c0 \ubabb\ud588\uc2b5\ub2c8\ub2e4.");
    }
    setPageData(await pageRes.json());
    setAssets(assetsRes.ok ? await assetsRes.json() : []);
    setAssetInspections(inspectionsRes.ok ? await inspectionsRes.json() : []);
    setAssetReadiness(readinessRes.ok ? await readinessRes.json() : null);
    setContentQuality(qualityRes.ok ? await qualityRes.json() : null);
  }, [projectId]);

  const acknowledgeContentQuality = async (issue: ContentQualityIssue) => {
    if (!window.confirm(`${issue.message}\n\n${issue.resolution}\n그래도 이 사진/항목을 사용하겠습니까?`)) return;
    setAcknowledgingQuality(`${issue.section_id}:${issue.code}`);
    try {
      const response = await fetch(apiUrl(`/api/v1/projects/${projectId}/page/content-quality/acknowledge`), {
        method: "POST", headers: { ...MOCK_HEADERS, "Content-Type": "application/json" }, credentials: "include",
        body: JSON.stringify({ section_id: issue.section_id, code: issue.code, asset_id: issue.asset_id || null }),
      });
      if (!response.ok) throw new Error("품질 확인 상태를 저장하지 못했습니다.");
      setContentQuality(await response.json());
    } catch (err) {
      setImageActionError(err instanceof Error ? err.message : "품질 확인 상태를 저장하지 못했습니다.");
    } finally { setAcknowledgingQuality(null); }
  };

  const startInlineEdit = (section: { id?: string; title?: string | null; body_copy?: string | null }) => {
    if (!section.id) return;
    setInlineEditingSectionId(section.id);
    setInlineDraft({ title: section.title || "", body_copy: section.body_copy || "" });
    setError(null);
  };

  const saveInlineEdit = async (confirmUnsupportedClaims = false) => {
    if (!pageData || !inlineEditingSectionId || !inlineDraft) return;
    const nextSections = pageData.sections.map((section) => section.id === inlineEditingSectionId
      ? { ...section, title: inlineDraft.title, body_copy: inlineDraft.body_copy }
      : section);
    setInlineSaving(true);
    try {
      const response = await fetch(apiUrl(`/api/v1/projects/${projectId}/page`), {
        method: "PATCH",
        headers: { ...MOCK_HEADERS, "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({
          theme_color: pageData.theme_color,
          font_family: pageData.font_family,
          confirm_unsupported_claims: confirmUnsupportedClaims,
          sections: nextSections.map((section) => ({
            id: section.id, title: section.title, body_copy: section.body_copy,
            image_asset_id: section.image_asset_id, visual_kind: section.visual_kind,
            visual_payload: section.visual_payload, sort_order: section.sort_order, is_visible: section.is_visible,
          })),
        }),
      });
      if (!response.ok) {
        const detail = await response.json().catch(() => null);
        if (detail?.detail?.code === "unsupported_claim_requires_review" && !confirmUnsupportedClaims) {
          const claims = (detail.detail.claims || []).join(", ");
          const approved = window.confirm(`근거가 확인되지 않은 표현이 있습니다: ${claims}\n사실 근거를 확인했습니까? 확인 후 저장하려면 확인을 누르세요.`);
          if (approved) {
            await saveInlineEdit(true);
            return;
          }
          return;
        }
        throw new Error(detail?.detail?.message || "문구를 저장하지 못했습니다.");
      }
      setPageData(await response.json());
      setInlineEditingSectionId(null);
      setInlineDraft(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "문구를 저장하지 못했습니다.");
    } finally {
      setInlineSaving(false);
    }
  };

  useEffect(() => {
    fetch(apiUrl("/api/v1/export/channel-presets"), { headers: MOCK_HEADERS })
      .then((response) => response.ok ? response.json() : { items: [] })
      .then((data) => setChannelPresets(Array.isArray(data.items) ? data.items : []))
      .catch(() => setChannelPresets([]));
  }, []);

  const handleRunAssetInspection = async () => {
    setInspectingAssets(true);
    setImageActionError(null);
    try {
      const response = await fetch(apiUrl(`/api/v1/projects/${projectId}/asset-inspections`), {
        method: "POST",
        headers: { ...MOCK_HEADERS, "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({}),
      });
      if (!response.ok) throw new Error("상품 이미지 분석을 완료하지 못했습니다.");
      setAssetInspections(await response.json());
      await refreshPageAndAssets();
    } catch (err) {
      setImageActionError(err instanceof Error ? err.message : "상품 이미지 분석 중 오류가 발생했습니다.");
    } finally {
      setInspectingAssets(false);
    }
  };

  const handleRetryAssetInspection = async (assetId: string) => {
    setInspectingAssets(true);
    setImageActionError(null);
    try {
      const response = await fetch(
        apiUrl(`/api/v1/projects/${projectId}/assets/${assetId}/asset-inspections/retry`),
        { method: "POST", headers: MOCK_HEADERS, credentials: "include" }
      );
      if (!response.ok) throw new Error("이 이미지의 분석을 다시 실행하지 못했습니다.");
      await refreshPageAndAssets();
    } catch (err) {
      setImageActionError(err instanceof Error ? err.message : "이미지 재분석 중 오류가 발생했습니다.");
    } finally {
      setInspectingAssets(false);
    }
  };

  const handleReviewTranslation = async (
    assetId: string,
    inspection: AssetInspection,
    blockIndex: number,
    currentText: string
  ) => {
    const translatedText = window.prompt("원문을 확인하고 한국어 번역을 수정해 주세요.", currentText);
    if (translatedText === null) return;
    setImageActionError(null);
    try {
      const response = await fetch(
        apiUrl(`/api/v1/projects/${projectId}/assets/${assetId}/asset-inspections/${inspection.id}/review`),
        {
          method: "PATCH",
          headers: { ...MOCK_HEADERS, "Content-Type": "application/json" },
          credentials: "include",
          body: JSON.stringify({ translated_text_by_index: { [blockIndex]: translatedText } }),
        }
      );
      if (!response.ok) throw new Error("OCR 번역 검토 내용을 저장하지 못했습니다.");
      await refreshPageAndAssets();
    } catch (err) {
      setImageActionError(err instanceof Error ? err.message : "OCR 번역 저장 중 오류가 발생했습니다.");
    }
  };

  const handleRegenerateImageCandidate = async (candidate: ImageCandidate) => {
    setImageActionError(null);
    setRegeneratingCandidateId(candidate.candidate_id);
    try {
      const regenerateRes = await fetch(
        apiUrl(`/api/v1/projects/${projectId}/visual-jobs/${candidate.candidate_id}/regenerate`),
        {
          method: "POST",
          headers: {
            ...MOCK_HEADERS,
            "Content-Type": "application/json",
          },
          credentials: "include",
          body: JSON.stringify({}),
        }
      );
      if (!regenerateRes.ok) {
        throw new Error("\uc774\ubbf8\uc9c0 \uc7ac\uc0dd\uc131 \uc900\ube44\uc5d0 \uc2e4\ud328\ud588\uc2b5\ub2c8\ub2e4.");
      }

      const generateRes = await fetch(
        apiUrl(`/api/v1/projects/${projectId}/visual-jobs/${candidate.candidate_id}/generate`),
        {
          method: "POST",
          headers: {
            ...MOCK_HEADERS,
            "Content-Type": "application/json",
          },
          credentials: "include",
          body: JSON.stringify({ cost_approved: true }),
        }
      );
      if (!generateRes.ok) {
        throw new Error("\uc774\ubbf8\uc9c0 \uc7ac\uc0dd\uc131 \uc694\uccad\uc5d0 \uc2e4\ud328\ud588\uc2b5\ub2c8\ub2e4.");
      }
      await refreshPageAndAssets();
    } catch (err) {
      console.error(err);
      setImageActionError(err instanceof Error ? err.message : "\uc774\ubbf8\uc9c0 \uc7ac\uc0dd\uc131 \uc911 \uc624\ub958\uac00 \ubc1c\uc0dd\ud588\uc2b5\ub2c8\ub2e4.");
    } finally {
      setRegeneratingCandidateId(null);
    }
  };

  const saveVisualSections = async (nextSections: PageSection[]) => {
    if (!pageData) return false;
    const response = await fetch(apiUrl(`/api/v1/projects/${projectId}/page`), {
      method: "PATCH",
      headers: { ...MOCK_HEADERS, "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({
        theme_color: pageData.theme_color,
        font_family: pageData.font_family,
        sections: nextSections.map((section) => ({
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
    if (!response.ok) throw new Error(await responseErrorMessage(response, "사진 배치를 저장하지 못했습니다."));
    setPageData(await response.json());
    return true;
  };

  const handleConfirmAssetUsage = async (candidate: ImageCandidate) => {
    if (!candidate.asset_id) return;
    if (!window.confirm("이 사진의 최종 상세페이지 사용 권한을 확인했습니까? 확인한 사진만 판매 페이지에 사용할 수 있습니다.")) return;
    try {
      const response = await fetch(apiUrl(`/api/v1/files/assets/${candidate.asset_id}/usage-status`), {
        method: "PATCH",
        headers: { ...MOCK_HEADERS, "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ usage_status: "seller_owned" }),
      });
      if (!response.ok) throw new Error(await responseErrorMessage(response, "사진 사용 권한을 확인하지 못했습니다."));
      await refreshPageAndAssets();
    } catch (err) {
      setImageActionError(err instanceof Error ? err.message : "사진 사용 권한을 확인하지 못했습니다.");
    }
  };

  const handleToggleSectionVisibility = async (sectionId: string) => {
    if (!pageData) return;
    try {
      await saveVisualSections(pageData.sections.map((section) => (
        section.id === sectionId ? { ...section, is_visible: !section.is_visible } : section
      )));
    } catch (err) {
      setImageActionError(err instanceof Error ? err.message : "섹션 표시 상태를 저장하지 못했습니다.");
    }
  };

  const handleUseTextLayout = async (sectionId: string) => {
    if (!pageData) return;
    try {
      await saveVisualSections(pageData.sections.map((section) => (
        section.id === sectionId
          ? {
              ...section,
              image_asset_id: null,
              visual_kind: "html_graphic" as const,
              visual_payload: { ...(section.visual_payload || {}), layout_variant: "image_text" },
              is_visible: true,
            }
          : section
      )));
    } catch (err) {
      setImageActionError(err instanceof Error ? err.message : "텍스트 레이아웃으로 전환하지 못했습니다.");
    }
  };

  const handleSetImageFit = async (sectionId: string, imageFit: "contain" | "cover") => {
    if (!pageData) return;
    try {
      await saveVisualSections(pageData.sections.map((section) => (
        section.id === sectionId
          ? { ...section, visual_payload: { ...(section.visual_payload || {}), image_fit: imageFit } }
          : section
      )));
    } catch (err) {
      setImageActionError(err instanceof Error ? err.message : "사진 표시 방식을 저장하지 못했습니다.");
    }
  };

  const handleMoveSection = async (sectionId: string, direction: -1 | 1) => {
    if (!pageData) return;
    const ordered = [...pageData.sections].sort((a, b) => a.sort_order - b.sort_order);
    const index = ordered.findIndex((section) => section.id === sectionId);
    const targetIndex = index + direction;
    if (index < 0 || targetIndex < 0 || targetIndex >= ordered.length) return;
    if (ordered[index].section_type === "product_information" || ordered[targetIndex].section_type === "product_information") return;
    const next = ordered.map((section) => ({ ...section }));
    [next[index].sort_order, next[targetIndex].sort_order] = [next[targetIndex].sort_order, next[index].sort_order];
    try {
      await saveVisualSections(next);
    } catch (err) {
      setImageActionError(err instanceof Error ? err.message : "섹션 순서를 저장하지 못했습니다.");
    }
  };

  const handleSelectImageCandidate = async (sectionId: string, candidate: ImageCandidate) => {
    if (!pageData || !candidate.asset_id) return;
    setImageActionError(null);
    if (candidate.eligible === false) {
      setImageActionError(candidate.block_reason || "최종 사용 권한을 확인한 사진만 선택할 수 있습니다.");
      return;
    }
    try {
      const targetSection = pageData.sections.find((section) => section.id === sectionId);
      const targetAsset = assets.find((asset) => asset.id === candidate.asset_id);
      const duplicateSection = pageData.sections.find(
        (section) => section.id !== sectionId && section.is_visible && section.image_asset_id === candidate.asset_id
      );
      if (duplicateSection && !window.confirm(`이 사진은 이미 ${duplicateSection.section_type} 섹션에서 사용 중입니다. 같은 사진을 두 곳에 사용하면 판매용 품질 확인이 필요합니다. 그래도 선택할까요?`)) {
        return;
      }
      if (targetAsset?.ocr_text && /[\u4e00-\u9fff]/.test(targetAsset.ocr_text) && !window.confirm("이 사진에서 외국어 문구가 감지되었습니다. 적용 후 다른 사진으로 교체하거나 사용 확인을 완료해야 판매용 최종본을 만들 수 있습니다. 계속할까요?")) {
        return;
      }
      const heroQualityWarnings = new Set([
        "LOW_RESOLUTION",
        "EXTREME_ASPECT_RATIO",
        "DUPLICATE_FILE",
        "IMAGE_INTEGRITY_WARNING",
        "SAFE_CROP_REVIEW_REQUIRED",
      ]);
      const requiresHeroQualityConfirmation =
        targetSection?.section_type === "hero" &&
        Boolean(targetAsset?.quality_warnings?.some((warning) => heroQualityWarnings.has(warning)));
      const requiresSafeCropReview = Boolean(
        targetAsset?.quality_warnings?.includes("SAFE_CROP_REVIEW_REQUIRED")
      );
      if (
        requiresHeroQualityConfirmation &&
        !window.confirm(
          requiresSafeCropReview
            ? "이 이미지는 HERO 영역에서 가장자리가 잘릴 수 있습니다. 미리보기를 확인했으며 그래도 사용하시겠습니까?"
            : "이 이미지는 해상도·비율 등 품질 경고가 있습니다. 그래도 HERO 이미지로 사용할까요?"
        )
      ) {
        return;
      }
      const updatedSections = pageData.sections.map((sec) => {
        if (sec.id === sectionId) {
          return {
            ...sec,
            image_asset_id: candidate.asset_id,
            // A spec/text section can intentionally become a photo section.
            // Without this, its html_graphic renderer would hide the chosen
            // seller photo.
            visual_kind: "image" as const,
          };
        }
        return { ...sec };
      });

      const res = await fetch(apiUrl(`/api/v1/projects/${projectId}/page`), {
        method: "PATCH",
        headers: {
          ...MOCK_HEADERS,
          "Content-Type": "application/json",
        },
        credentials: "include",
        body: JSON.stringify({
          // One photo choice changes one section. Sending every section caused
          // an unchanged, reviewed HERO to be revalidated while editing body
          // sections such as PAIN_POINT.
          sections: updatedSections.filter((section) => section.id === sectionId),
          confirm_low_quality_hero: requiresHeroQualityConfirmation,
        }),
      });

      if (!res.ok) {
        throw new Error(await responseErrorMessage(res, "이미지 후보를 적용하지 못했습니다."));
      }

      // The response contains fresh candidate lists, including newly
      // permission-approved seller photos. Do not restore a stale list.
      setPageData(await res.json());

    } catch (err) {
      console.error(err);
      setImageActionError(err instanceof Error ? err.message : "이미지 선택 중 오류가 발생했습니다.");
    }
  };

  const handleDownloadImage = async (format: ExportImageFormat) => {
    const formatLabel = format.toUpperCase();
    setExportError(null);
    setExportBlockers([]);
    setExportStage("idle");
    if (visualBlockers.length > 0) {
      setExportBlockers(visualBlockers);
      setExportError("다운로드 전에 이미지 후보를 확인해 주세요.");
      return;
    }
    const nameSlug = slugify(project?.name || "sellform-detail-page");
    const fallbackFilename = `${nameSlug}-상세페이지.${format}`;

    setExporting(true);
    setExportStage("finalizing");
    try {
      const finalRes = await fetch(apiUrl(`/api/v1/projects/${projectId}/page/finalize`), {
        method: "POST",
        headers: MOCK_HEADERS,
        credentials: "include",
      });
      if (!finalRes.ok) {
        throw new Error(await responseErrorMessage(finalRes, "최종 상세페이지를 고정하지 못했습니다. 다시 시도해 주세요."));
      }
      const finalVersion = (await finalRes.json()) as FinalPageVersion;

      setExportStage("rendering");
      const createRes = await fetch(apiUrl(`/api/v1/projects/${projectId}/page/export`), {
        method: "POST",
        headers: {
          ...MOCK_HEADERS,
          "Content-Type": "application/json",
        },
        credentials: "include",
        body: JSON.stringify({
          preset_name: exportPreset,
          use_commerce_cut: true,
          output_format: format,
          export_target: "local_download",
          final_version_id: finalVersion.id,
          render_base_url: window.location.origin,
        }),
      });
      if (!createRes.ok) {
        const detail = await createRes.json().catch(() => null);
        const detailMsg = detail?.detail;
        // Check for blockers from readiness service
        if (detailMsg && detailMsg.blockers) {
          setExportBlockers(detailMsg.blockers);
          throw new Error(detailMsg.message || "다운로드 전 확인이 필요합니다.");
        }
        const message =
          (typeof detailMsg?.message === "string" && detailMsg.message) ||
          (typeof detailMsg === "string" && detailMsg) ||
          (typeof detail?.message === "string" && detail.message) ||
          `${formatLabel} 내보내기를 시작하지 못했습니다.`;
        throw new Error(message);
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
          { headers: MOCK_HEADERS, credentials: "include" }
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

      const fileRes = await fetch(apiUrl(outputPath), { headers: MOCK_HEADERS, credentials: "include" });
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
      downloadBlob(blob, filename);
      if (downloadPackage && job.output_images?.[1]) {
        const packageRes = await fetch(apiUrl(job.output_images[1]), { headers: MOCK_HEADERS, credentials: "include" });
        if (!packageRes.ok) throw new Error("자동 분할 묶음 파일을 준비하지 못했습니다.");
        const packageDisposition = packageRes.headers.get("content-disposition") || "";
        const packageEncoded = packageDisposition.match(/filename\*=UTF-8''([^;]+)/i)?.[1];
        const packageQuoted = packageDisposition.match(/filename="([^"]+)"/i)?.[1];
        const packageFilename = packageEncoded ? decodeURIComponent(packageEncoded) : packageQuoted || `${nameSlug}-${exportPreset}-분할묶음.zip`;
        downloadBlob(await packageRes.blob(), packageFilename);
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

  const updateAssetClassification = async (
    assetId: string,
    payload: { asset_role?: string; is_representative?: boolean }
  ) => {
    try {
      const response = await fetch(
        apiUrl(`/api/v1/projects/${projectId}/assets/${assetId}/classification`),
        {
          method: "PATCH",
          headers: { ...MOCK_HEADERS, "Content-Type": "application/json" },
          credentials: "include",
          body: JSON.stringify(payload),
        }
      );
      if (!response.ok) throw new Error("이미지 역할을 저장하지 못했습니다.");
      const updatedAsset = await response.json();
      void updatedAsset;
      await refreshPageAndAssets();
    } catch (err) {
      setImageActionError(err instanceof Error ? err.message : "이미지 역할 변경 중 오류가 발생했습니다.");
    }
  };

  const handleAssetRoleChange = async (assetId: string, assetRole: string) => {
    await updateAssetClassification(assetId, { asset_role: assetRole });
  };

  const responseErrorMessage = async (response: Response, fallback: string) => {
    try {
      const payload = await response.json();
      if (typeof payload.detail === "string") return payload.detail;
      if (typeof payload.detail?.message === "string") return payload.detail.message;
      if (typeof payload.message === "string") return payload.message;
      return fallback;
    } catch {
      return fallback;
    }
  };

  const handleCreateUpscale = async (source: ProjectAsset) => {
    setImageActionError(null);
    setUpscalingAssetId(source.id);
    try {
      const response = await fetch(apiUrl(`/api/v1/files/assets/${source.id}/upscale`), {
        method: "POST",
        headers: MOCK_HEADERS,
        credentials: "include",
      });
      if (!response.ok) {
        throw new Error(await responseErrorMessage(response, "고화질 보정본을 만들지 못했습니다."));
      }
      const enhanced = (await response.json()) as ProjectAsset;
      setUpscaleComparison({ source, enhanced });
    } catch (err) {
      setImageActionError(err instanceof Error ? err.message : "고화질 보정 중 오류가 발생했습니다.");
    } finally {
      setUpscalingAssetId(null);
    }
  };

  const handleApplyUpscale = async () => {
    if (!upscaleComparison) return;
    setApplyingUpscale(true);
    setImageActionError(null);
    try {
      const response = await fetch(
        apiUrl(`/api/v1/files/assets/${upscaleComparison.enhanced.id}/upscale/apply`),
        { method: "POST", headers: MOCK_HEADERS, credentials: "include" }
      );
      if (!response.ok) {
        throw new Error(await responseErrorMessage(response, "고화질 보정본을 적용하지 못했습니다."));
      }
      await refreshPageAndAssets();
      setExportBlockers([]);
      setUpscaleComparison(null);
    } catch (err) {
      setImageActionError(err instanceof Error ? err.message : "고화질 보정본 적용 중 오류가 발생했습니다.");
    } finally {
      setApplyingUpscale(false);
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
  const photoEditableSections = [...pageData.sections]
    .sort((a, b) => a.sort_order - b.sort_order);
  const failedImageCandidates = visibleSections.flatMap((section) =>
    (section.image_candidates || []).filter((candidate) => candidate.status === "failed")
  );
  const hasBillingLimitImageFailure = failedImageCandidates.some((candidate) => {
    const text = `${candidate.error_code || ""} ${(candidate.warnings || []).join(" ")}`.toLowerCase();
    return (
      text.includes("billing_hard_limit_reached") ||
      text.includes("billing hard limit") ||
      text.includes("billing_limit_user_error")
    );
  });
  const invalidVisualCount = visibleSections.filter(
    (section) => validateSectionVisual(section as unknown as DetailPageSectionVisual).length > 0
  ).length;
  const visualBlockers = visibleSections.flatMap((section) =>
    validateSectionVisual(section as unknown as DetailPageSectionVisual).map((message) => ({
      section_id: section.id,
      code: "visual_image_asset_required",
      message,
    }))
  );
  const readyForSale = Boolean(contentQuality?.ready_for_sale) && visualBlockers.length === 0;
  const worklistHref = "/workspace/projects";
  const planningHref = `/workspace/projects/${projectId}/planning`;
  const reviewHref = `/workspace/projects/${projectId}/page-editor?mode=review`;
  const advancedHref = `/workspace/projects/${projectId}/page-editor?mode=advanced`;
  const handleHistoryBack = () => {
    if (typeof window !== "undefined" && window.history.length > 1) {
      router.back();
      return;
    }
    router.push(worklistHref);
  };
  const handleHistoryForward = () => {
    if (typeof window !== "undefined") {
      window.history.forward();
    }
  };

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

        <div className="flex flex-wrap items-center justify-end gap-2">
          <div aria-label="page history navigation" className="flex items-center gap-1">
            <button
              type="button"
              onClick={handleHistoryBack}
              className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs font-bold text-slate-600 hover:bg-slate-50"
            >
              ← 이전
            </button>
            <button
              type="button"
              onClick={handleHistoryForward}
              className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs font-bold text-slate-600 hover:bg-slate-50"
            >
              다음 →
            </button>
          </div>
          <Link
            href={worklistHref}
            className="rounded-lg border border-slate-200 bg-white px-4 py-2 text-xs font-bold text-slate-600 hover:bg-slate-50"
          >
            작업 목록
          </Link>
          <Link
            href={`/workspace/projects/${projectId}/facts`}
            className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-2 text-xs font-bold text-emerald-800 hover:bg-emerald-100"
          >
            사실·증거 확인
          </Link>
          <Link
            href={planningHref}
            className="rounded-lg border border-slate-200 bg-white px-4 py-2 text-xs font-bold text-slate-700 hover:bg-slate-50"
          >
            ← 이전 단계
          </Link>
          <Link
            href={reviewHref}
            className="rounded-lg bg-emerald-600 px-4 py-2 text-xs font-bold text-white hover:bg-emerald-700"
          >
            다음: 검수하며 다듬기 →
          </Link>
          <Link
            href={advancedHref}
            className="rounded-lg border border-slate-200 bg-white px-4 py-2 text-xs font-bold text-slate-700 hover:bg-slate-50"
          >
            고급 편집기로 열기
          </Link>
        </div>
      </header>

      {failedImageCandidates.length > 0 ? (
        <section className="border-b border-amber-200 bg-amber-50 px-6 py-4">
          <div className="mx-auto flex w-full max-w-7xl flex-col gap-2 text-sm text-amber-900 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <p className="font-extrabold">
                {hasBillingLimitImageFailure
                  ? "\uc774\ubbf8\uc9c0 \uc0dd\uc131\uc774 \uacb0\uc81c \ud55c\ub3c4 \ub54c\ubb38\uc5d0 \uc911\ub2e8\ub410\uc2b5\ub2c8\ub2e4"
                  : "\uc77c\ubd80 \uc774\ubbf8\uc9c0 \uc0dd\uc131\uc774 \uc644\ub8cc\ub418\uc9c0 \uc54a\uc558\uc2b5\ub2c8\ub2e4"}
              </p>
              <p className="mt-1 text-xs leading-5 text-amber-800">
                {hasBillingLimitImageFailure
                  ? "OpenAI \uacc4\uc815\uc758 \uacb0\uc81c \ud55c\ub3c4\ub97c \ud574\uacb0\ud55c \ub4a4 \uc624\ub978\ucabd \ud6c4\ubcf4\uc5d0\uc11c \uc774\ubbf8\uc9c0\ub9cc \ub2e4\uc2dc \uc0dd\uc131\ud560 \uc218 \uc788\uc2b5\ub2c8\ub2e4."
                  : "\ud14d\uc2a4\ud2b8 \uc0c1\uc138\ud398\uc774\uc9c0\ub294 \uc720\uc9c0\ud558\uace0, \uc2e4\ud328\ud55c \uc774\ubbf8\uc9c0 job\ub9cc \ub2e4\uc2dc \uc2e4\ud589\ud560 \uc218 \uc788\uc2b5\ub2c8\ub2e4."}
              </p>
              {imageActionError ? (
                <p className="mt-2 rounded bg-white/70 px-3 py-2 text-xs font-bold text-rose-700">
                  {imageActionError}
                </p>
              ) : null}
            </div>
            <span className="shrink-0 rounded-full bg-white px-3 py-1 text-xs font-extrabold text-amber-800">
              {failedImageCandidates.length}\uac1c \uc7ac\uc2dc\ub3c4 \ud544\uc694
            </span>
          </div>
        </section>
      ) : null}

      {imageActionError && failedImageCandidates.length === 0 ? (
        <section role="alert" className="border-b border-rose-200 bg-rose-50 px-6 py-3">
          <div className="mx-auto flex w-full max-w-7xl items-center justify-between gap-4 text-sm text-rose-800">
            <p className="font-bold">{imageActionError}</p>
            <button
              type="button"
              onClick={() => setImageActionError(null)}
              className="shrink-0 rounded border border-rose-200 bg-white px-3 py-1 text-xs font-bold"
            >
              닫기
            </button>
          </div>
        </section>
      ) : null}

      <main className="mx-auto grid w-full max-w-7xl grid-cols-1 items-start gap-8 px-6 py-8 lg:grid-cols-[minmax(0,760px)_380px]">
        <div>
          <div className="mb-5">
            <h2 className="text-xl font-extrabold text-slate-950">판매용 상세페이지</h2>
            <p className="mt-1 text-sm text-slate-500">실제 구매자가 위에서 아래로 읽는 흐름입니다.</p>
          </div>
          <section aria-label="다음 작업" className="mb-6 grid gap-3 rounded-2xl border border-slate-200 bg-slate-50 p-4 sm:grid-cols-2">
            <Link
              href={`/workspace/projects/${projectId}/page-editor?mode=review`}
              className="rounded-xl border border-emerald-200 bg-white p-4 hover:bg-emerald-50"
            >
              <p className="text-sm font-extrabold text-emerald-700">검수하며 다듬기</p>
              <p className="mt-1 text-xs leading-relaxed text-slate-500">
                문구와 이미지를 빠르게 확인하고 누락·오류를 줄입니다.
              </p>
            </Link>
            <Link
              href={`/workspace/projects/${projectId}/page-editor?mode=advanced`}
              className="rounded-xl border border-slate-200 bg-white p-4 hover:bg-slate-100"
            >
              <p className="text-sm font-extrabold text-slate-800">고급 편집기로 열기</p>
              <p className="mt-1 text-xs leading-relaxed text-slate-500">
                레이아웃과 섹션을 더 세밀하게 수정합니다.
              </p>
            </Link>
            <Link
              href="/workspace/projects"
              className="rounded-xl border border-slate-200 bg-white p-4 text-sm font-bold text-slate-700 hover:bg-slate-100"
            >
              작업 목록
            </Link>
            <Link
              href="/workspace/exports"
              className="rounded-xl border border-slate-200 bg-white p-4 text-sm font-bold text-slate-700 hover:bg-slate-100"
            >
              출력 이력
            </Link>
          </section>
          {contentQuality ? (
            <section className={`mx-auto w-full max-w-[760px] rounded-2xl border p-5 ${readyForSale ? "border-emerald-200 bg-emerald-50" : "border-amber-200 bg-amber-50"}`}>
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <h2 className="font-extrabold text-slate-950">판매용 품질 확인</h2>
                  <p className="mt-1 text-xs text-slate-600">기술적 다운로드 가능 여부와 별도로 문구·사진·외국어 노출을 검수합니다.</p>
                </div>
                <span className={`rounded-full px-3 py-1 text-xs font-extrabold ${readyForSale ? "bg-emerald-600 text-white" : "bg-amber-600 text-white"}`}>
                  {readyForSale
                    ? (contentQuality.seller_confirmed_usage ? "판매자 확인 후 사용" : "판매용 초안 준비됨")
                    : "확인 필요"}
                </span>
              </div>
              <p className="mt-3 text-xs text-slate-600">기술 렌더링: {visualBlockers.length ? `수정 필요 ${visualBlockers.length}개` : "준비됨"} · 판매용 콘텐츠: {contentQuality.ready_for_sale ? "통과" : "확인 필요"}</p>
              {contentQuality.seller_confirmed_usage ? (
                <p className="mt-2 text-xs font-semibold text-amber-700">
                  판매자 확인: 위험 요소가 있는 이미지 {contentQuality.seller_confirmed_usage_count || 1}건을 확인 후 사용 중입니다.
                </p>
              ) : null}
              <p className="mt-3 text-xs font-semibold text-slate-700">다운로드 파일명: {contentQuality.export_slug}-{exportPreset}-detail</p>
              {[...contentQuality.blockers, ...contentQuality.reviews, ...contentQuality.recommendations].length ? (
                <ul className="mt-4 space-y-2">
                  {[...contentQuality.blockers, ...contentQuality.reviews, ...contentQuality.recommendations].map((issue, index) => (
                    <li key={`${issue.section_id}-${issue.code}-${index}`} className="rounded-lg bg-white/80 p-3 text-xs">
                      <p className="font-extrabold text-slate-800">{issue.message}</p>
                      <p className="mt-1 text-slate-600">{issue.resolution}</p>
                      <div className="mt-2 flex gap-2">
                        {issue.section_id !== "page" ? <button type="button" onClick={() => document.getElementById(`section-${issue.section_id}`)?.scrollIntoView({ behavior: "smooth", block: "center" })} className="rounded border border-slate-300 px-2 py-1 font-bold text-slate-700">섹션 보기</button> : null}
                        {issue.asset_id && issue.section_id !== "page" ? <button type="button" onClick={() => document.getElementById(`quality-candidates-${issue.section_id}`)?.scrollIntoView({ behavior: "smooth", block: "center" })} className="rounded border border-slate-300 px-2 py-1 font-bold text-slate-700">다른 사진 선택</button> : null}
                        {issue.asset_id && issue.section_id !== "page" ? <button type="button" onClick={() => void handleUseTextLayout(issue.section_id)} className="rounded border border-slate-300 px-2 py-1 font-bold text-slate-700">정보형 전환</button> : null}
                        {issue.code === "foreign_text_exposed" && issue.section_id !== "page" ? <button type="button" onClick={() => void handleSetImageFit(issue.section_id, "contain")} className="rounded border border-slate-300 px-2 py-1 font-bold text-slate-700">안전 여백 표시</button> : null}
                        {issue.severity === "review" && ["duplicate_asset", "duplicate_asset_group", "foreign_text_exposed", "phone_number_exposed", "price_exposed", "qr_code_review", "market_or_competitor_text", "supplier_text_exposed"].includes(issue.code) ? <button type="button" disabled={acknowledgingQuality === `${issue.section_id}:${issue.code}`} onClick={() => void acknowledgeContentQuality(issue)} className="rounded bg-amber-600 px-2 py-1 font-bold text-white disabled:bg-slate-300">사용 확인</button> : null}
                      </div>
                    </li>
                  ))}
                </ul>
              ) : <p className="mt-4 text-sm font-bold text-emerald-700">반복 문구·중복 사진·외국어 노출 확인 항목이 없습니다.</p>}
            </section>
          ) : null}
          <DetailPageDocument
            page={pageData}
            assets={assets}
            editingSectionId={inlineEditingSectionId}
            inlineDraft={inlineDraft}
            inlineSaving={inlineSaving}
            onStartInlineEdit={startInlineEdit}
            onInlineDraftChange={(field, value) => setInlineDraft((current) => current ? { ...current, [field]: value } : current)}
            onSaveInlineEdit={() => { void saveInlineEdit(); }}
            onCancelInlineEdit={() => { setInlineEditingSectionId(null); setInlineDraft(null); }}
          />
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
                          {assetSourceLabel(matchedAsset)}
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
          <details className="mb-5 rounded-lg border border-slate-200 bg-slate-50 p-3">
            <summary className="cursor-pointer text-xs font-extrabold text-slate-800">상품 이미지 분류 · 품질 확인</summary>
            <div className="mt-3 space-y-3">
              <div className="rounded border border-emerald-100 bg-emerald-50 p-2">
                <button
                  type="button"
                  onClick={handleRunAssetInspection}
                  disabled={inspectingAssets}
                  className="w-full rounded bg-emerald-700 px-2 py-2 text-[10px] font-bold text-white disabled:bg-slate-300"
                >
                  {inspectingAssets ? "이미지 분석 중…" : "이미지 역할·OCR·권리 상태 분석"}
                </button>
                <p className="mt-2 text-[10px] leading-4 text-emerald-800">
                  공급처 이미지는 분석·AI 참고용으로만 보관되며 원본 그대로 최종 출력에 사용되지 않습니다.
                </p>
              </div>
              {assetReadiness ? (
                <div className={`rounded border p-2 text-[10px] leading-4 ${assetReadiness.ready ? "border-emerald-200 bg-emerald-50 text-emerald-800" : "border-amber-200 bg-amber-50 text-amber-800"}`}>
                  <p className="font-extrabold">
                    {assetReadiness.ready ? "Sprint 3 사실 추출 준비 완료" : `확인할 항목 ${assetReadiness.blockers.length}개`}
                  </p>
                  {!assetReadiness.ready ? (
                    <ul className="mt-1 list-disc pl-4">
                      {assetReadiness.blockers.map((blocker, index) => (
                        <li key={`${blocker.asset_id}-${blocker.code}-${index}`}>{blocker.message}</li>
                      ))}
                    </ul>
                  ) : null}
                </div>
              ) : null}
              {assets.filter((asset) => asset.mime_type.startsWith("image/")).map((asset) => (
                <div key={asset.id} className="rounded border border-slate-200 bg-white p-2">
                  <div className="flex gap-2">
                    <img
                      src={assetUrl(asset)}
                      alt={asset.filename}
                      className="h-14 w-14 shrink-0 rounded border border-slate-100 bg-slate-50 object-cover"
                    />
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-[11px] font-bold text-slate-700">{asset.filename}</p>
                      <p className="mt-1 text-[10px] text-slate-500">
                        {asset.width && asset.height ? `${asset.width} × ${asset.height}` : "크기 확인 필요"}
                        {asset.quality_status === "warning" ? " · 품질 확인 필요" : " · 사용 가능"}
                      </p>
                      <p className="mt-1 text-[10px] text-slate-500">
                        역할: {asset.asset_role || "unknown"} · 신뢰도 {Math.round((asset.role_confidence || 0) * 100)}%
                      </p>
                      <p className="mt-1 text-[10px] text-slate-500">권리 상태: {asset.usage_status || "확인 필요"}</p>
                      <p className="mt-1 text-[10px] text-slate-500">
                        안전 크롭: {asset.safe_crop_status === "safe" ? "가능" : "검수 필요"}
                      </p>
                    </div>
                  </div>
                  {asset.is_representative ? (
                    <p className="mt-2 rounded bg-emerald-50 px-2 py-1 text-[10px] font-bold text-emerald-700">
                      현재 대표 이미지 {asset.representative_source === "manual" ? "(직접 선택)" : "(자동 추천)"}
                    </p>
                  ) : null}
                  {asset.quality_warnings?.length ? (
                    <p className="mt-1 text-[10px] font-semibold text-amber-700">{asset.quality_warnings.join(", ")}</p>
                  ) : null}
                  <p className="mt-1 text-[10px] text-slate-500">
                    사용 섹션: {pageData.sections
                      .filter((section) => section.image_asset_id === asset.id)
                      .map((section) => section.section_type)
                      .join(", ") || "아직 없음"}
                  </p>
                  {(() => {
                    const inspection = assetInspections.find((item) => item.asset_id === asset.id);
                    if (!inspection) {
                      return <p className="mt-1 text-[10px] text-slate-500">분석 이력 없음</p>;
                    }
                    return (
                      <div className="mt-2 rounded bg-slate-50 p-2 text-[10px] leading-4 text-slate-600">
                        <p className="font-bold text-slate-700">
                          분석 v{inspection.analysis_version} · {inspection.status} · {inspection.analyzer_version}
                        </p>
                        {inspection.created_at ? (
                          <p>처리: {new Date(inspection.created_at).toLocaleString("ko-KR")}{inspection.completed_at ? ` → ${new Date(inspection.completed_at).toLocaleTimeString("ko-KR")}` : ""}</p>
                        ) : null}
                        <p>권리: {inspection.rights_status || "확인 필요"} · 최종 출력 {inspection.final_output_eligible ? "가능" : "불가"}</p>
                        {inspection.analysis_metadata ? (
                          <p>
                            AI 장면 기준: {inspection.analysis_metadata.ai_scene_reference_suitability || "확인 필요"}
                            {typeof inspection.analysis_metadata.text_density === "number" ? ` · 텍스트 점유 ${(inspection.analysis_metadata.text_density * 100).toFixed(1)}%` : ""}
                          </p>
                        ) : null}
                        {inspection.duplicate_asset_ids.length ? <p className="text-amber-700">중복 그룹: {inspection.duplicate_asset_ids.map((id) => id.slice(0, 8)).join(", ")}</p> : null}
                        {inspection.numeric_evidence.length ? <p>OCR 수치: {inspection.numeric_evidence.join(", ")}</p> : null}
                        {inspection.translation_blocks.map((block, index) => (
                          <div key={`${asset.id}-translation-${index}`} className="mt-2 rounded border border-slate-200 bg-white p-2">
                            <p className="font-semibold text-slate-700">원문: {block.source_text}</p>
                            <p>번역: {block.translated_text}</p>
                            <p className="text-slate-400">
                              위치: {block.bbox ? `${block.bbox.x},${block.bbox.y} ${block.bbox.width}×${block.bbox.height} (${block.bbox.precision || "pixel"})` : "확인 필요"}
                              {` · ${block.translation_status}`}
                            </p>
                            <button
                              type="button"
                              onClick={() => handleReviewTranslation(asset.id, inspection, index, block.translated_text)}
                              className="mt-1 rounded bg-slate-700 px-2 py-1 font-bold text-white"
                            >
                              번역 확인·수정
                            </button>
                          </div>
                        ))}
                        {inspection.warnings.length ? <p className="text-amber-700">{inspection.warnings.join(", ")}</p> : null}
                        <button
                          type="button"
                          disabled={inspectingAssets}
                          onClick={() => handleRetryAssetInspection(asset.id)}
                          className="mt-2 w-full rounded border border-slate-300 bg-white px-2 py-1 font-bold text-slate-700 disabled:text-slate-300"
                        >
                          이 이미지 재분석
                        </button>
                      </div>
                    );
                  })()}
                  <div className="mt-2 grid grid-cols-2 gap-2">
                    <select
                      aria-label={`${asset.filename} 이미지 역할`}
                      value={asset.asset_role || "unknown"}
                      onChange={(event) => handleAssetRoleChange(asset.id, event.target.value)}
                      className="rounded border border-slate-200 bg-white px-2 py-1 text-[10px] font-semibold text-slate-700"
                    >
                      <option value="unknown">역할 미확인</option>
                      <option value="product_main">대표 상품</option>
                      <option value="product_detail">상품 디테일</option>
                      <option value="feature">기능컷</option>
                      <option value="usage_scene">사용 장면</option>
                      <option value="components">구성품</option>
                      <option value="material_detail">소재·디테일</option>
                      <option value="package">패키지</option>
                      <option value="shipping_info">포장·배송 정보</option>
                      <option value="spec_reference">스펙 참고</option>
                      <option value="supplier_banner">공급처 배너·로고</option>
                      <option value="decorative">배너·장식 이미지</option>
                      <option value="unidentifiable_reference">식별 불가 참고 이미지</option>
                    </select>
                    <button
                      type="button"
                      disabled={asset.is_representative}
                      onClick={() => updateAssetClassification(asset.id, { is_representative: true })}
                      className="rounded bg-slate-900 px-2 py-1 text-[10px] font-bold text-white disabled:bg-emerald-600"
                    >
                      {asset.is_representative ? "대표 선택됨" : "대표로 선택"}
                    </button>
                    {asset.quality_warnings?.includes("LOW_RESOLUTION") && asset.source_type !== "local_upscaled" ? (
                      <button
                        type="button"
                        disabled={upscalingAssetId === asset.id}
                        onClick={() => handleCreateUpscale(asset)}
                        className="col-span-2 rounded bg-amber-600 px-2 py-2 text-[10px] font-bold text-white hover:bg-amber-700 disabled:bg-slate-300"
                      >
                        {upscalingAssetId === asset.id ? "고화질 보정본 만드는 중..." : "고화질 보정본 만들기"}
                      </button>
                    ) : null}
                  </div>
                </div>
              ))}
            </div>
          </details>
          <div className="max-h-[calc(100vh-190px)] space-y-6 overflow-y-auto pr-2">
            {photoEditableSections.map((section) => {
                const cands = (section.image_candidates || []).filter(
                  (candidate) => {
                    const linkedAsset = assets.find((asset) => asset.id === candidate.asset_id);
                    return (linkedAsset?.source_type || candidate.source_type) !== "mock-generated";
                  }
                );
                return (
                  <div id={`quality-candidates-${section.id}`} key={section.id} className="space-y-3 border-b border-slate-100 pb-5 last:border-0">
                    <div className="flex items-center justify-between gap-2">
                      <div className="min-w-0">
                        <span className="text-[10px] font-extrabold uppercase tracking-wider text-emerald-700">{section.section_type}</span>
                        <span className="ml-2 max-w-[170px] truncate text-[11px] font-bold text-slate-700">{section.title}</span>
                      </div>
                      {section.section_type !== "product_information" ? <div className="flex shrink-0 gap-1">
                        <button type="button" onClick={() => handleMoveSection(section.id, -1)} className="rounded border border-slate-200 px-1.5 py-1 text-[10px] font-bold text-slate-600" aria-label={`${section.title} 위로 이동`}>↑</button>
                        <button type="button" onClick={() => handleMoveSection(section.id, 1)} className="rounded border border-slate-200 px-1.5 py-1 text-[10px] font-bold text-slate-600" aria-label={`${section.title} 아래로 이동`}>↓</button>
                        <button type="button" data-testid={`ux2c-visibility-${section.id}`} onClick={() => handleToggleSectionVisibility(section.id)} className="rounded border border-slate-200 px-1.5 py-1 text-[10px] font-bold text-slate-600">
                          {section.is_visible ? "숨김" : "표시"}
                        </button>
                        <button type="button" onClick={() => handleUseTextLayout(section.id)} className="rounded border border-slate-200 px-1.5 py-1 text-[10px] font-bold text-slate-600">
                          텍스트
                        </button>
                        <button type="button" onClick={() => handleSetImageFit(section.id, "contain")} className="rounded border border-slate-200 px-1.5 py-1 text-[10px] font-bold text-slate-600">
                          맞춤
                        </button>
                        <button type="button" onClick={() => handleSetImageFit(section.id, "cover")} className="rounded border border-slate-200 px-1.5 py-1 text-[10px] font-bold text-slate-600">
                          채움
                        </button>
                      </div> : null}
                    </div>
                    <div className="rounded-lg border border-slate-100 bg-slate-50 px-3 py-2 text-[10px] leading-4 text-slate-600">
                      <p className="font-extrabold text-slate-700">이 섹션에 연결된 확인 사실</p>
                      {section.associated_fact_texts?.length ? (
                        <ul className="mt-1 list-disc pl-4">
                          {section.associated_fact_texts.map((fact, index) => (
                            <li key={`${section.id}-fact-${index}`}>{fact}</li>
                          ))}
                        </ul>
                      ) : (
                        <p className="mt-1 text-slate-500">연결된 사실이 없습니다. 문구는 판매자 입력 정보만 사용합니다.</p>
                      )}
                    </div>
                    {cands.length === 0 ? (
                      <p className="rounded-lg bg-amber-50 px-3 py-2 text-[11px] font-semibold text-amber-700">
                        상품 사진을 추가해 주세요.
                      </p>
                    ) : (
                      <div className="grid grid-cols-2 gap-2">
                        {cands.map((cand) => {
                          const isSelected = Boolean(cand.asset_id) && section.image_asset_id === cand.asset_id;
                          const candAsset = assets.find((asset) => asset.id === cand.asset_id);
                          const effectiveSourceType = candAsset?.source_type || cand.source_type;
                          const requiresUrlApproval = ["url-extracted", "url-imported"].includes(effectiveSourceType);
                          const isEligible = cand.eligible !== false;
                          const canConfirmUsage = cand.usage_status === "reference_only";
                          const candThumbnail = cand.asset_id
                            ? assetUrl(candAsset || { id: cand.asset_id })
                            : null;
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
                                    {cand.source_type === "missing-image" ? "상품 사진 필요" : "재생성 필요"}
                                  </span>
                                )}
                                <span className="absolute right-1.5 top-1.5 rounded-full bg-slate-900/80 px-1.5 py-0.5 text-[8px] font-bold text-white">
                                  {candidateSourceLabel(cand, candAsset)}
                                </span>
                              </div>
                              <p className="mt-2 truncate text-[10px] font-bold text-slate-700">{cand.label}</p>
                              {cand.is_recommended ? <p className="mt-1 text-[10px] font-bold text-emerald-700">섹션 추천 사진</p> : null}
                              <p className="mt-1 text-[10px] leading-4 text-slate-500">
                                권한: {usageStatusLabel(cand.usage_status || candAsset?.usage_status)}
                                {cand.asset_role ? ` · 역할: ${cand.asset_role}` : ""}
                              </p>
                              {cand.recommendation_reason ? (
                                <p className="mt-1 text-[10px] leading-4 text-emerald-700">추천 근거: {cand.recommendation_reason}</p>
                              ) : null}
                              {!isEligible && cand.block_reason ? (
                                <p className="mt-1 text-[10px] leading-4 text-amber-700">{cand.block_reason}</p>
                              ) : null}
                              {requiresUrlApproval && !isSelected ? (
                                <p className="mt-1 text-[10px] font-bold text-amber-700">선택 후 적용</p>
                              ) : null}
                              {candidateWarningLabel(cand) ? (
                                <p className="mt-1 text-[10px] font-bold text-amber-700">
                                  {candidateWarningLabel(cand)}
                                </p>
                              ) : null}
                              {candAsset?.quality_warnings?.length ? (
                                <p className="mt-1 text-[10px] font-bold text-amber-700">
                                  {candAsset.quality_warnings.join(", ")}
                                </p>
                              ) : null}
                              {cand.error_code === "LOW_QUALITY_HERO_SOURCE" ? (
                                <p className="mt-1 text-[10px] leading-4 text-slate-500">
                                  고화질로 보정하거나, 위의 이미지 분류에서 다른 사진을 선택해 주세요.
                                </p>
                              ) : null}
                              {candAsset?.quality_warnings?.includes("LOW_RESOLUTION") && candAsset.source_type !== "local_upscaled" ? (
                                <button
                                  type="button"
                                  disabled={upscalingAssetId === candAsset.id}
                                  onClick={() => handleCreateUpscale(candAsset)}
                                  className="mt-2 w-full rounded bg-amber-600 py-1.5 text-[10px] font-bold text-white hover:bg-amber-700 disabled:bg-slate-300"
                                >
                                  {upscalingAssetId === candAsset.id ? "고화질 보정본 만드는 중..." : "고화질 보정본 만들기"}
                                </button>
                              ) : null}
                              {candAsset?.source_type === "local_upscaled" ? (
                                <p className="mt-1 text-[10px] font-semibold leading-4 text-emerald-700">
                                  저화질 원본에서 자동으로 준비한 보정본입니다. 확인 후 이 이미지를 선택하세요.
                                </p>
                              ) : null}
                              {cand.status === "failed" && cand.warnings?.length ? (
                                <p className="mt-1 break-words rounded bg-rose-50 px-2 py-1 text-[9px] font-semibold leading-4 text-rose-700">
                                  {cand.warnings[0]}
                                </p>
                              ) : null}
                              {cand.status === "failed" ? (
                                <button
                                  type="button"
                                  disabled={regeneratingCandidateId === cand.candidate_id}
                                  onClick={() => handleRegenerateImageCandidate(cand)}
                                  className="mt-2 w-full rounded bg-amber-600 py-1.5 text-[10px] font-bold text-white hover:bg-amber-700 disabled:bg-slate-200 disabled:text-slate-400"
                                >
                                  {regeneratingCandidateId === cand.candidate_id
                                    ? "\uc7ac\uc0dd\uc131 \uc911..."
                                    : "\uc774\ubbf8\uc9c0 \ub2e4\uc2dc \uc0dd\uc131"}
                                </button>
                              ) : null}
                              {canConfirmUsage ? (
                                <button
                                  type="button"
                                  data-testid={`ux2c-confirm-${section.id}-${cand.asset_id}`}
                                  onClick={() => handleConfirmAssetUsage(cand)}
                                  className="mt-2 w-full rounded bg-amber-600 py-1.5 text-[10px] font-bold text-white hover:bg-amber-700"
                                >
                                  최종 사용 권한 확인
                                </button>
                              ) : null}
                              <button
                                type="button"
                                data-testid={`ux2c-use-${section.id}-${cand.asset_id}`}
                                disabled={isSelected || !cand.asset_id || !isEligible}
                                onClick={() => handleSelectImageCandidate(section.id, cand)}
                                className={`mt-2 w-full rounded py-1.5 text-[10px] font-bold ${
                                  isSelected
                                    ? "bg-emerald-600 text-white"
                                    : "bg-slate-900 text-white disabled:bg-slate-200 disabled:text-slate-400"
                                }`}
                              >
                                {isSelected ? "적용됨" : requiresUrlApproval ? "이 URL 이미지 승인" : "이 이미지 사용"}
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

      {upscaleComparison ? (
        <div className="fixed inset-0 z-[70] flex items-center justify-center bg-slate-950/70 p-4" role="dialog" aria-modal="true" aria-label="고화질 보정 전후 비교">
          <div className="w-full max-w-3xl rounded-2xl bg-white p-5 shadow-2xl sm:p-7">
            <div className="flex items-start justify-between gap-4">
              <div>
                <h2 className="text-lg font-extrabold text-slate-950">고화질 보정 전후 비교</h2>
                <p className="mt-1 text-xs leading-5 text-slate-500">제품 모양과 현재 섹션 레이아웃은 유지하고, 이미지 파일만 확대·선명도 보정합니다.</p>
              </div>
              <button
                type="button"
                disabled={applyingUpscale}
                onClick={() => setUpscaleComparison(null)}
                className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-bold text-slate-600"
              >
                닫기
              </button>
            </div>
            <div className="mt-5 grid gap-4 sm:grid-cols-2">
              <figure className="rounded-xl border border-slate-200 bg-slate-50 p-3">
                <div className="aspect-square overflow-hidden rounded-lg bg-white">
                  <img src={assetUrl(upscaleComparison.source)} alt="보정 전 원본" className="h-full w-full object-contain" />
                </div>
                <figcaption className="mt-3 text-xs font-bold text-slate-700">
                  보정 전 · {upscaleComparison.source.width} × {upscaleComparison.source.height}
                </figcaption>
              </figure>
              <figure className="rounded-xl border-2 border-emerald-500 bg-emerald-50 p-3">
                <div className="aspect-square overflow-hidden rounded-lg bg-white">
                  <img src={assetUrl(upscaleComparison.enhanced)} alt="보정 후 고화질 이미지" className="h-full w-full object-contain" />
                </div>
                <figcaption className="mt-3 text-xs font-extrabold text-emerald-800">
                  보정 후 · {upscaleComparison.enhanced.width} × {upscaleComparison.enhanced.height}
                </figcaption>
              </figure>
            </div>
            <div className="mt-5 flex justify-end gap-3">
              <button
                type="button"
                disabled={applyingUpscale}
                onClick={() => setUpscaleComparison(null)}
                className="rounded-lg border border-slate-200 px-5 py-3 text-sm font-bold text-slate-700"
              >
                원본 유지
              </button>
              <button
                type="button"
                disabled={applyingUpscale}
                onClick={handleApplyUpscale}
                className="rounded-lg bg-emerald-600 px-5 py-3 text-sm font-bold text-white hover:bg-emerald-700 disabled:bg-slate-300"
              >
                {applyingUpscale ? "교체 중..." : "이 보정본으로 교체"}
              </button>
            </div>
          </div>
        </div>
      ) : null}

      <footer className="sticky bottom-0 border-t border-slate-200 bg-white px-6 py-4">
        <ExportReadinessWarning blockers={exportBlockers} projectId={projectId} />
        <div className="flex items-center justify-center gap-4">
        <label className="flex items-center gap-2 text-sm font-semibold text-slate-600">
          채널
          <select
            aria-label="출력 채널"
            value={exportPreset}
            disabled={exporting}
            onChange={(event) => {
              const nextPreset = event.target.value as "coupang" | "smartstore";
              setExportPreset(nextPreset);
              const matched = channelPresets.find((preset) => preset.key === nextPreset);
              if (matched?.default_format) setExportFormat(matched.default_format);
            }}
            className="h-11 rounded-lg border border-slate-200 bg-white px-3 text-sm font-bold text-slate-800"
          >
            {(channelPresets.length ? channelPresets : [
              { key: "smartstore", label: "네이버 스마트스토어" },
              { key: "coupang", label: "쿠팡" },
            ]).map((preset) => (
              <option key={preset.key} value={preset.key}>{preset.label}</option>
            ))}
          </select>
        </label>
        <label className="hidden items-center gap-2 text-xs font-semibold text-slate-600 sm:flex">
          <input
            type="checkbox"
            checked={downloadPackage}
            disabled={exporting}
            onChange={(event) => setDownloadPackage(event.target.checked)}
            className="h-4 w-4 accent-emerald-600"
          />
          자동 분할 묶음 함께 저장
        </label>
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
          disabled={exporting}
          className="rounded-lg border border-slate-200 bg-white px-6 py-3 text-sm font-bold text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:bg-slate-100 disabled:text-slate-400"
        >
          {exporting
            ? `${exportFormat.toUpperCase()} ${exportStage === "finalizing" ? "최종본 준비 중..." : exportStage === "rendering" ? "이미지 생성 중..." : exportStage === "downloading" ? "다운로드 중..." : exportStage === "saving" ? "저장 중..." : "처리 중..."}`
            : `${exportFormat.toUpperCase()}로 다운로드`}
        </button>
        <button
          type="button"
          onClick={() => router.push(`/workspace/projects/${projectId}/page-editor?mode=review`)}
          className="rounded-lg bg-emerald-600 px-6 py-3 text-sm font-bold text-white hover:bg-emerald-700"
        >
          검수하며 다듬기
        </button>
        {exportError ? <p className="absolute bottom-full mb-2 rounded-lg bg-rose-50 px-4 py-2 text-xs font-bold text-rose-700">{exportError}</p> : null}
        </div>
      </footer>
    </div>
  );
}

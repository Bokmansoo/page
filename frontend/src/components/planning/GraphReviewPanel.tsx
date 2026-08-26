"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { apiUrl } from "@/lib/api";

type SellerGuidance = {
  cause_ko: string;
  action_ko: string;
  action_type: string;
  retryable: boolean;
  review_required: boolean;
};

type DelayContext = {
  current_stage: string;
  current_stage_ko: string;
  current_scene_id?: string;
  delay_cause: string;
  delay_cause_ko: string;
  eta_status: "estimated" | "overdue" | "insufficient_sample" | "paused_for_review";
  eta_range_seconds?: { min: number; max: number } | null;
  updated_at: string;
  seller_guidance: SellerGuidance;
};

export type GraphView = {
  run_id: string;
  thread_id: string;
  status: string;
  current_stage: string;
  checkpoint_id?: string | null;
  values: {
    review?: { pending?: ReviewRequest | null };
    generation?: {
      jobs?: Array<{
        job_id: string;
        scene_id?: string;
        section_id?: string;
        role?: string;
        status: string;
        output_asset_id?: string | null;
        error_code?: string | null;
        seller_guidance?: SellerGuidance;
        warnings?: string[];
        source_asset_ids?: string[];
        validation?: {
          schema_version?: string;
          status?: string;
          checks?: Record<string, string>;
          warnings?: string[];
          risk_codes?: string[];
          ocr_text?: string;
        };
        estimated_cost?: number | null;
        actual_cost?: number | null;
        generation_attempt?: number;
        outbox_status?: string | null;
        required_for_completion?: boolean;
      }>;
      estimated_cost?: number;
      actual_cost?: number;
      pending_count?: number;
      review_count?: number;
      failed_job_ids?: string[];
      required_scene_count?: number;
      approved_count?: number;
      remaining_required_scene_ids?: string[];
      all_required_scenes_approved?: boolean;
      cost_plan?: {
        cost_plan_hash: string;
        provider: string;
        model: string;
        scene_count: number;
        scenes: Array<{ scene_id: string; title: string; role: string; model: string; output_size: string; estimated_cost: number }>;
        total_estimated_cost: number;
        currency: string;
        status: string;
      };
    };
    rendering?: {
      detail_page_version?: { id?: string };
    };
    edit?: {
      version_restore?: { detail_page_version_id?: string };
    };
    quality?: {
      quality_bar_verdict?: "PASS" | "FAIL" | "NEEDS_REVIEW";
      routing_code?: string;
      seller_review_required?: boolean;
      rework_targets?: Array<Record<string, unknown>>;
    };
    intake?: {
      input_mode?: string;
      requested_generation_mode?: string;
      target_channels?: string[];
      envelope?: {
        input_mode?: string;
        requested_generation_mode?: string;
        target_channels?: string[];
      };
      creative_brief?: {
        brief_version?: { id?: string; version?: number; canonical_hash?: string };
      };
      commerce_creative_master?: {
        master_version?: { id?: string; version?: number; canonical_hash?: string };
      };
    };
    canvas?: {
      canonical_page_assembly_input?: { sections?: Array<{ section_id: string; canvas?: { is_visible?: boolean; height_px?: number | null }; canvas_elements?: Array<{ element_id: string; kind: string; x: number; y: number; width: number; height: number; z_index: number; locked: boolean; group_id?: string | null; deleted?: boolean; asset_id?: string; asset_content_hash?: string }> }> };
      element_groups?: Array<{ group_id: string; section_id: string; child_element_ids: string[]; locked: boolean }>;
      revision?: number;
    };
    execution?: {
      recoverable?: boolean;
      last_error?: GraphExecutionError | null;
      errors?: GraphExecutionError[];
      delay_context?: DelayContext | null;
      progress_preview?: {
        completed_sections: Array<{ section_id: string; summary?: string }>;
        pending_sections: Array<{ section_id: string }>;
        completed_count: number;
        total_sections: number;
        progress_percent: number;
        current_section?: string | null;
      } | null;
    };
  };
  next_nodes: string[];
};

type GraphExecutionError = {
  stage?: string;
  code?: string;
  message?: string;
  user_message?: string;
  recovery_action?: string;
  recoverable?: boolean;
  seller_guidance?: SellerGuidance;
};

type ReviewRequest = {
  schema_version: "lg4-v1" | "lg5-v1" | "lg11-v1" | "lg12i-v1";
  review_stage: "input_review" | "evidence_review" | "planning_review" | "generation_pending" | "provider_wait" | "image_review" | "edit_confirmation" | "canvas_edit" | "seller_confirmation" | "quality_review";
  title: string;
  description: string;
  allowed_decisions: string[];
  seller_guidance?: SellerGuidance;
  seller_choice?: { choice_required: boolean; available_actions: Array<"fallback" | "wait">; automatic_attempts: number };
};

type UploadAsset = {
  id: string;
  filename: string;
  source_type: string;
  usage_status: string;
  mime_type?: string;
  content_hash?: string | null;
};

type StandaloneExport = {
  copyable_html: string;
  html_download_url: string;
  zip_download_url: string;
};

type FrozenCanvasElement = {
  element_id: string;
  kind: string;
};

type FrozenCanvasSection = {
  section_id: string;
  canvas_elements?: FrozenCanvasElement[];
  copy_ref?: { fields?: string[]; fact_ids?: string[] };
  approved_assets?: Array<{ scene_id?: string; asset_id?: string; asset_content_hash?: string }>;
};

type FrozenVersionSnapshot = {
  sections_json?: {
    lg10?: {
      canonical_page_assembly_input?: {
        sections?: FrozenCanvasSection[];
        approved_asset_manifest?: { assets?: Array<{ scene_id?: string; section_id?: string; asset_id?: string; asset_content_hash?: string }> };
      };
    };
  };
};

type EditIntentPreview = {
  edit_intent: Record<string, unknown>;
  impact_preview: {
    affected_artifacts?: {
      section_ids?: string[];
      scene_ids?: string[];
      assets?: Array<{ asset_id?: string; asset_content_hash?: string }>;
      copy_artifacts?: Array<{ artifact_key?: string; artifact_hash?: string }>;
      brand_kit?: Record<string, unknown>;
      facts?: Array<{ fact_id?: string; evidence_ids?: string[] }>;
      style_layout_tokens?: Array<{ section_id?: string; layout_token?: string }>;
    };
    expected_provider_cost?: Record<string, unknown>;
    requires_cost_approval?: boolean;
    requires_evidence_review?: boolean;
    requires_explicit_confirmation?: boolean;
    execution_blocked?: boolean;
  };
};

type FrozenVersionOption = { id: string; name: string; is_final: boolean; lg11_frozen?: boolean };
type BrandKitVersionOption = { id: string; version?: number; status?: string };
type QualityStatus = {
  status: "pass" | "ready_to_promote" | "needs_attention" | "not_available";
  quality_verdict?: "PASS" | "FAIL" | "NEEDS_REVIEW";
  score?: number;
  promotion_status?: "promoted" | "ready" | "blocked" | "not_required";
  export_readiness?: Record<string, boolean>;
  review_required?: boolean;
  message?: string;
  attempt_summary?: { automatic_rework_count?: number };
};

type Props = {
  projectId: string;
  runId?: string | null;
  hidePlanningAction?: boolean;
  onStateChange?: (view: GraphView | null) => void;
};

const validationStatusLabel: Record<string, string> = {
  passed: "통과",
  needs_review: "판매자 확인 필요",
  blocked: "차단",
};

const validationCheckLabel: Record<string, string> = {
  identity: "상품 정체성",
  ocr: "문구/OCR",
  crop: "잘림 안전성",
  resolution: "해상도",
  safety: "안전성",
  rights: "사용 권리",
};

const validationCheckStatusLabel: Record<string, string> = {
  passed: "통과",
  needs_review: "확인 필요",
  blocked: "차단",
  not_run: "실행 전 중단",
};

export default function GraphReviewPanel({ projectId, runId, hidePlanningAction = false, onStateChange }: Props) {
  const [view, setView] = useState<GraphView | null>(null);
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [loadIssue, setLoadIssue] = useState<string | null>(null);
  const [recoveryNotice, setRecoveryNotice] = useState<string | null>(null);
  const [uploadAssets, setUploadAssets] = useState<UploadAsset[]>([]);
  const [uploadByJob, setUploadByJob] = useState<Record<string, string>>({});
  const [standaloneExport, setStandaloneExport] = useState<StandaloneExport | null>(null);
  const [standaloneExporting, setStandaloneExporting] = useState(false);
  const [canvasHeights, setCanvasHeights] = useState<Record<string, string>>({});
  const [selectedCanvasElements, setSelectedCanvasElements] = useState<string[]>([]);
  const [canvasAssetReplacements, setCanvasAssetReplacements] = useState<Record<string, string>>({});
  const [previewChannel, setPreviewChannel] = useState<"smartstore" | "coupang">("smartstore");
  const [frozenCanvasSections, setFrozenCanvasSections] = useState<FrozenCanvasSection[]>([]);
  const [selectedEditSectionId, setSelectedEditSectionId] = useState("");
  const [selectedEditElementId, setSelectedEditElementId] = useState("");
  const [selectedEditCopyField, setSelectedEditCopyField] = useState("");
  const [conversationalInstruction, setConversationalInstruction] = useState("");
  const [conversationalCopy, setConversationalCopy] = useState("");
  const [conversationalMode, setConversationalMode] = useState<"canvas" | "copy" | "fact" | "style" | "scene_regenerate" | "asset_replace" | "restore">("canvas");
  const [selectedEditSceneId, setSelectedEditSceneId] = useState("");
  const [selectedReplacementAssetId, setSelectedReplacementAssetId] = useState("");
  const [selectedDesignDirection, setSelectedDesignDirection] = useState("balanced_sale");
  const [selectedBrandKitVersionId, setSelectedBrandKitVersionId] = useState("");
  const [selectedRestoreVersionId, setSelectedRestoreVersionId] = useState("");
  const [frozenVersionOptions, setFrozenVersionOptions] = useState<FrozenVersionOption[]>([]);
  const [brandKitVersionOptions, setBrandKitVersionOptions] = useState<BrandKitVersionOption[]>([]);
  const [qualityStatus, setQualityStatus] = useState<QualityStatus | null>(null);
  const [conversationalPreview, setConversationalPreview] = useState<EditIntentPreview | null>(null);
  const [confirmedEditPayload, setConfirmedEditPayload] = useState<Record<string, unknown> | null>(null);
  const [autoRefreshingGeneration, setAutoRefreshingGeneration] = useState(false);
  const [slo08Attested, setSlo08Attested] = useState(false);
  const inFlightRef = useRef(false);
  const copyableHtmlRef = useRef<HTMLTextAreaElement | null>(null);
  const resolvedRunIdRef = useRef<string | null>(runId ?? null);

  const recoveryStorageKey = useCallback(
    (resolvedRunId: string) => `sellform:graph-review-recovered:${projectId}:${resolvedRunId}`,
    [projectId],
  );

  useEffect(() => {
    resolvedRunIdRef.current = runId ?? null;
  }, [runId]);

  const load = useCallback(async (showLoading = true) => {
    if (showLoading) setLoading(true);
    try {
      setLoadIssue(null);
      const requestedRunId = resolvedRunIdRef.current;
      const requestOptions = { credentials: "include" as const, cache: "no-store" as const };
      const assetPromise = fetch(apiUrl(`/api/v1/projects/${projectId}/assets`), requestOptions);
      let response = await fetch(apiUrl(requestedRunId
        ? `/api/v1/graph-runs/${requestedRunId}`
        : `/api/v1/graph-runs/projects/${projectId}/review`), requestOptions);
      let recoveredFromStaleRun = false;

      if (requestedRunId && response.status === 404) {
        response = await fetch(apiUrl(`/api/v1/graph-runs/projects/${projectId}/review`), requestOptions);
        recoveredFromStaleRun = response.ok;
      }

      const assetResponse = await assetPromise;
    if (response.status === 404) {
      setView(null);
      onStateChange?.(null);
      setRecoveryNotice(null);
        if (requestedRunId) {
          setLoadIssue("이 주소의 작업 실행을 찾을 수 없습니다. 실행이 만료되었거나 새 실행으로 교체되었습니다. 작업 목록에서 현재 실행을 다시 열거나 새 프로젝트 실행을 시작해 주세요.");
        }
        return;
      }
      if (!response.ok) throw new Error("승인 대기 상태를 불러오지 못했습니다.");
      const next = await response.json() as GraphView;
      resolvedRunIdRef.current = next.run_id;
      setView(next);
      onStateChange?.(next);
      if (recoveredFromStaleRun && next.run_id !== requestedRunId) {
        const notice = "만료된 실행 주소를 이 프로젝트의 현재 승인 대기 실행으로 복구했습니다.";
        window.sessionStorage.setItem(recoveryStorageKey(next.run_id), notice);
        const url = new URL(window.location.href);
        url.searchParams.set("runId", next.run_id);
        window.history.replaceState({}, "", `${url.pathname}${url.search}${url.hash}`);
        setRecoveryNotice(notice);
      } else {
        setRecoveryNotice(window.sessionStorage.getItem(recoveryStorageKey(next.run_id)));
      }
      if (assetResponse.ok) {
        const assets = await assetResponse.json() as UploadAsset[];
        setUploadAssets(assets.filter((asset) =>
          ["uploaded", "self_shot"].includes(asset.source_type)
          && ["seller_owned", "rights_confirmed"].includes(asset.usage_status)
          && (!asset.mime_type || asset.mime_type.startsWith("image/")),
        ));
      }
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "승인 대기 상태를 불러오지 못했습니다.");
    } finally {
      if (showLoading) setLoading(false);
    }
  }, [projectId, onStateChange, recoveryStorageKey]);

  useEffect(() => { void load(); }, [load]);

  useEffect(() => {
    setConversationalPreview(null);
    setConfirmedEditPayload(null);
  }, [selectedEditSectionId, selectedEditElementId, selectedEditCopyField, conversationalInstruction, conversationalCopy, conversationalMode, selectedEditSceneId, selectedReplacementAssetId, selectedDesignDirection, selectedBrandKitVersionId, selectedRestoreVersionId]);

  const completedDetailPageVersionId = view?.values.rendering?.detail_page_version?.id
    || view?.values.edit?.version_restore?.detail_page_version_id;
  useEffect(() => {
    if (view?.current_stage !== "quality_promotion_ready" || !completedDetailPageVersionId) {
      setQualityStatus(null);
      return;
    }
    let active = true;
    void fetch(apiUrl(`/api/v1/projects/${projectId}/quality-status`), {
      credentials: "include", cache: "no-store",
    }).then(async (response) => {
      if (!response.ok) throw new Error("품질 상태를 불러오지 못했습니다.");
      return response.json() as Promise<QualityStatus>;
    }).then((status) => { if (active) setQualityStatus(status); })
      .catch((error) => { if (active) setMessage(error instanceof Error ? error.message : "품질 상태를 불러오지 못했습니다."); });
    return () => { active = false; };
  }, [completedDetailPageVersionId, projectId, view?.current_stage]);

  const promoteQualityPage = async () => {
    if (!completedDetailPageVersionId || inFlightRef.current) return;
    inFlightRef.current = true;
    setWorking(true); setMessage(null);
    try {
      const response = await fetch(apiUrl(`/api/v1/projects/${projectId}/page/promotion`), {
        method: "POST", headers: { "Content-Type": "application/json" }, credentials: "include",
        body: JSON.stringify({ detail_page_version_id: completedDetailPageVersionId }),
      });
      const payload = await response.json().catch(() => null);
      if (!response.ok) throw new Error(payload?.detail?.message || "최종 사용 가능 상태로 전환하지 못했습니다.");
      const statusResponse = await fetch(apiUrl(`/api/v1/projects/${projectId}/quality-status`), { credentials: "include", cache: "no-store" });
      if (statusResponse.ok) setQualityStatus(await statusResponse.json() as QualityStatus);
      setMessage("품질 검토를 통과했습니다. 선택한 채널로 내보낼 수 있습니다.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "최종 사용 가능 상태로 전환하지 못했습니다.");
    } finally {
      inFlightRef.current = false; setWorking(false);
    }
  };
  useEffect(() => {
    if (!completedDetailPageVersionId) {
      setFrozenCanvasSections([]);
      setSelectedEditSectionId("");
      setSelectedEditElementId("");
      setSelectedEditCopyField("");
      return;
    }
    let active = true;
    void fetch(
      apiUrl(`/api/v1/projects/${projectId}/page/versions/${completedDetailPageVersionId}`),
      { credentials: "include", cache: "no-store" },
    ).then(async (response) => {
      if (!response.ok) throw new Error("Frozen version을 불러오지 못했습니다.");
      return response.json() as Promise<FrozenVersionSnapshot>;
    }).then((snapshot) => {
      if (!active) return;
      const sections = snapshot.sections_json?.lg10?.canonical_page_assembly_input?.sections || [];
      setFrozenCanvasSections(sections);
      setSelectedEditSectionId((current) => current || sections[0]?.section_id || "");
    }).catch((error) => {
      if (active) setMessage(error instanceof Error ? error.message : "Frozen version을 불러오지 못했습니다.");
    });
    return () => { active = false; };
  }, [completedDetailPageVersionId, projectId]);

  useEffect(() => {
    if (!completedDetailPageVersionId) return;
    let active = true;
    const options = { credentials: "include" as const, cache: "no-store" as const };
    void Promise.all([
      fetch(apiUrl(`/api/v1/projects/${projectId}/page/versions`), options),
      fetch(apiUrl("/api/v1/brand-kits"), options),
    ]).then(async ([versionsResponse, brandKitsResponse]) => {
      if (!active) return;
      if (versionsResponse.ok) setFrozenVersionOptions(await versionsResponse.json() as FrozenVersionOption[]);
      if (brandKitsResponse.ok) {
        const data = await brandKitsResponse.json() as { versions?: BrandKitVersionOption[] };
        setBrandKitVersionOptions(data.versions || []);
      }
    }).catch(() => {
      // These are optional selectors. The frozen version itself stays the
      // only source of truth for every edit request.
    });
    return () => { active = false; };
  }, [completedDetailPageVersionId, projectId]);

  useEffect(() => {
    const stage = view?.current_stage;
    const isWorkerWait = stage === "provider_wait";
    // `generation_pending` normally waits for a seller's cost approval. It
    // becomes safe to poll only after this panel has submitted that approval:
    // some workers persist the queued state before publishing provider_wait.
    const isQueuedAfterApproval = stage === "generation_pending" && autoRefreshingGeneration;
    if (!isWorkerWait && !isQueuedAfterApproval) {
      if (autoRefreshingGeneration && stage !== "generation_pending") {
        setAutoRefreshingGeneration(false);
      }
      return;
    }
    // Keep the current review card mounted during background polling. A
    // queued/provider wait may last several seconds; replacing the whole
    // panel with a loading placeholder on every poll makes images vanish.
    const timer = window.setInterval(() => { void load(false); }, 1500);
    return () => window.clearInterval(timer);
  }, [view?.current_stage, autoRefreshingGeneration, load]);

  const resume = async (
    decision: "approve" | "reject" | "defer" | "refresh" | "regenerate" | "upload" | "apply" | "undo" | "redo" | "commit" | "fallback" | "wait",
    options: { jobId?: string; assetId?: string; canvasOperation?: Record<string, unknown>; sellerAttested?: boolean } = {},
  ) => {
    if (!view || inFlightRef.current) return;
    const pending = view.values.review?.pending;
    if (!pending) return;
    const startsImageGeneration = decision === "approve" && pending.review_stage === "generation_pending";
    inFlightRef.current = true;
    setWorking(true); setMessage(null);
    if (startsImageGeneration) setAutoRefreshingGeneration(true);
    try {
      const response = await fetch(apiUrl(`/api/v1/graph-runs/${view.run_id}/resume`), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({
          thread_id: view.thread_id,
          response: {
            schema_version: pending.schema_version,
            review_stage: pending.review_stage,
            decision,
            ...(view.values.generation?.cost_plan?.cost_plan_hash
              ? { cost_plan_hash: view.values.generation.cost_plan.cost_plan_hash }
              : {}),
            ...(options.jobId ? { job_id: options.jobId } : {}),
            ...(decision === "upload" ? { asset_id: options.assetId, seller_attested: true } : {}),
            ...(decision === "fallback" ? { seller_attested: options.sellerAttested === true } : {}),
            ...(options.canvasOperation ? { canvas_operation: options.canvasOperation } : {}),
          },
        }),
      });
      const payload = await response.json().catch(() => null);
      if (!response.ok) {
        if (startsImageGeneration) setAutoRefreshingGeneration(false);
        const errorMessage = typeof payload?.detail === "string" ? payload.detail : "승인 요청을 처리하지 못했습니다.";
        await load();
        setMessage(errorMessage);
        return;
      }
      setView(payload);
      onStateChange?.(payload);
      // A seller can add or reclassify a rights-owned image while the graph is
      // paused at a review gate. Refresh both the graph and project assets
      // after every successful resume so the per-scene upload selector does
      // not keep the asset list captured when this panel first mounted.
      await load();
      setMessage(decision === "approve" ? "승인을 저장하고 다음 그래프 단계로 진행했습니다." : "현재 실행 상태를 갱신했습니다.");
      // Planning artifacts are persisted while the graph advances from
      // evidence_review to planning_review. Reload once so the editor reads
      // that durable draft instead of manufacturing a legacy fallback.
      if (payload.current_stage === "planning_review") window.setTimeout(() => window.location.reload(), 150);
      if (["completed", "cancelled"].includes(payload.status)) window.setTimeout(() => window.location.reload(), 150);
    } catch (error) {
      if (startsImageGeneration) setAutoRefreshingGeneration(false);
      await load();
      setMessage(error instanceof Error ? error.message : "승인 요청을 처리하지 못했습니다.");
    } finally {
      inFlightRef.current = false;
      setWorking(false);
    }
  };

  const retryFailedRun = async () => {
    if (!view || inFlightRef.current) return;
    inFlightRef.current = true;
    setWorking(true); setMessage(null);
    try {
      const response = await fetch(apiUrl(`/api/v1/graph-runs/${view.run_id}/resume`), {
        method: "POST",
        credentials: "include",
      });
      const payload = await response.json().catch(() => null);
      if (!response.ok) {
        const errorMessage = payload?.detail || "같은 실행을 재개하지 못했습니다.";
        await load();
        setMessage(errorMessage);
        return;
      }
      setView(payload);
      onStateChange?.(payload);
      setMessage("같은 작업 실행을 재개했습니다.");
      if (payload.current_stage === "planning_review") window.setTimeout(() => window.location.reload(), 150);
    } catch (error) {
      await load();
      setMessage(error instanceof Error ? error.message : "같은 실행을 재개하지 못했습니다.");
    } finally {
      inFlightRef.current = false;
      setWorking(false);
    }
  };

  const createStandaloneExport = async (
    detailPageVersionId: string,
    channel: "smartstore" | "coupang" = previewChannel,
  ) => {
    setStandaloneExporting(true);
    setMessage(null);
    try {
      const response = await fetch(apiUrl(`/api/v1/projects/${projectId}/page/export/standalone`), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
          body: JSON.stringify({ final_version_id: detailPageVersionId, channel }),
      });
      const payload = await response.json().catch(() => null);
      if (!response.ok) {
        throw new Error(typeof payload?.detail === "string" ? payload.detail : "HTML/ZIP 내보내기를 준비하지 못했습니다.");
      }
      setStandaloneExport(payload as StandaloneExport);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "HTML/ZIP 내보내기를 준비하지 못했습니다.");
    } finally {
      setStandaloneExporting(false);
    }
  };

  const copyLg10Html = async () => {
    const html = standaloneExport?.copyable_html;
    if (!html) return;
    try {
      await navigator.clipboard.writeText(html);
      setMessage("쇼핑몰 HTML 편집기에 붙여넣을 코드를 복사했습니다.");
    } catch {
      const textarea = copyableHtmlRef.current;
      if (!textarea) {
        setMessage("HTML 코드를 선택해 직접 복사해 주세요.");
        return;
      }
      textarea.focus();
      textarea.select();
      const copied = document.execCommand("copy");
      setMessage(copied ? "쇼핑몰 HTML 편집기에 붙여넣을 코드를 복사했습니다." : "HTML 코드를 선택해 직접 복사해 주세요.");
    }
  };

  const buildSelectedLg11EditPayload = (): Record<string, unknown> | null => {
    if (!completedDetailPageVersionId || !conversationalInstruction.trim()) return null;
    const selectedSection = frozenCanvasSections.find((section) => section.section_id === selectedEditSectionId);
    const selectedContext = selectedEditSectionId
      ? { selected_section_id: selectedEditSectionId, ...(selectedEditElementId ? { selected_element_id: selectedEditElementId } : {}) }
      : {};
    const copyField = selectedEditCopyField || selectedSection?.copy_ref?.fields?.[0] || "";
    if (conversationalMode === "restore") {
      if (!selectedRestoreVersionId) return null;
      return { scope: "page", target_ids: [selectedRestoreVersionId], operation: "restore", instruction: conversationalInstruction.trim() };
    }
    if (conversationalMode === "style") {
      return {
        scope: "style", target_ids: [completedDetailPageVersionId], operation: "restyle",
        instruction: conversationalInstruction.trim(), design_direction: selectedDesignDirection,
        ...(selectedBrandKitVersionId ? { brand_kit_version_id: selectedBrandKitVersionId } : {}), ...selectedContext,
      };
    }
    if (conversationalMode === "scene_regenerate" || conversationalMode === "asset_replace") {
      if (!selectedEditSceneId) return null;
      if (conversationalMode === "asset_replace" && !selectedReplacementAssetId) return null;
      return {
        scope: "scene", target_ids: [selectedEditSceneId], operation: conversationalMode === "scene_regenerate" ? "regenerate" : "replace",
        instruction: conversationalInstruction.trim(), ...selectedContext,
        ...(conversationalMode === "asset_replace" ? { replacement_asset_id: selectedReplacementAssetId, seller_attested: true } : {}),
      };
    }
    if (!selectedEditSectionId) return null;
    if (conversationalMode === "fact") {
      const factId = selectedSection?.copy_ref?.fact_ids?.[0] || "";
      if (!factId) return null;
      return { scope: "fact", target_ids: [factId], operation: "rewrite", instruction: conversationalInstruction.trim(), ...selectedContext };
    }
    if (conversationalMode === "copy") {
      if (!conversationalCopy.trim() || !copyField) return null;
      return {
        scope: "copy", target_ids: [selectedEditSectionId], operation: "rewrite", instruction: conversationalInstruction.trim(),
        copy_changes: { [selectedEditSectionId]: { [copyField]: conversationalCopy.trim() } }, ...selectedContext,
      };
    }
    return {
      scope: "page", target_ids: [completedDetailPageVersionId], operation: "canvas_draft",
      instruction: conversationalInstruction.trim(), ...selectedContext,
    };
  };

  const previewSelectedLg11Edit = async () => {
    const payload = buildSelectedLg11EditPayload();
    if (!payload || !completedDetailPageVersionId) {
      setMessage("선택한 대상과 편집에 필요한 값을 확인해 주세요.");
      return;
    }
    const sourceVersionId = conversationalMode === "restore" ? selectedRestoreVersionId : completedDetailPageVersionId;
    if (!sourceVersionId) return;
    setWorking(true); setMessage(null); setConversationalPreview(null); setConfirmedEditPayload(null);
    try {
      const response = await fetch(
        apiUrl(`/api/v1/projects/${projectId}/page/versions/${sourceVersionId}/edit-intents/preview`),
        { method: "POST", headers: { "Content-Type": "application/json" }, credentials: "include", body: JSON.stringify(payload) },
      );
      const result = await response.json().catch(() => null);
      if (!response.ok || !result?.edit_intent) throw new Error(typeof result?.detail === "string" ? result.detail : "영향 미리보기를 만들지 못했습니다.");
      setConversationalPreview(result as EditIntentPreview);
      setConfirmedEditPayload(payload);
    } catch (error) {
      setMessage(error instanceof globalThis.Error ? error.message : "영향 미리보기를 만들지 못했습니다.");
    } finally { setWorking(false); }
  };

  const startConfirmedLg11Edit = async () => {
    if (!completedDetailPageVersionId || !confirmedEditPayload || !conversationalPreview) return;
    const sourceVersionId = conversationalMode === "restore" ? selectedRestoreVersionId : completedDetailPageVersionId;
    if (!sourceVersionId) return;
    setWorking(true); setMessage(null);
    try {
      const response = await fetch(
        apiUrl(`/api/v1/projects/${projectId}/page/versions/${sourceVersionId}/edit-runs`),
        { method: "POST", headers: { "Content-Type": "application/json" }, credentials: "include", body: JSON.stringify(confirmedEditPayload) },
      );
      const result = await response.json().catch(() => null);
      if (!response.ok || !result?.run_id) throw new Error(typeof result?.detail === "string" ? result.detail : "LG-11 편집 실행을 시작하지 못했습니다.");
      resolvedRunIdRef.current = result.run_id;
      const url = new URL(window.location.href); url.searchParams.set("runId", result.run_id);
      window.history.replaceState({}, "", `${url.pathname}${url.search}${url.hash}`);
      setConversationalPreview(null); setConfirmedEditPayload(null);
      await load(false);
    } catch (error) {
      setMessage(error instanceof globalThis.Error ? error.message : "LG-11 편집 실행을 시작하지 못했습니다.");
    } finally { setWorking(false); }
  };

  const startSelectedLg11Edit = async () => {
    // Kept as the existing UI callback: it is now strictly read-only.  The
    // graph run can only be created by the explicit confirmation control.
    await previewSelectedLg11Edit();
    return;
    /*
    if (!completedDetailPageVersionId || !selectedEditSectionId || !conversationalInstruction.trim()) {
      setMessage("수정할 frozen 섹션과 요청 내용을 선택해 주세요.");
      return;
    }
    const selectedSection = frozenCanvasSections.find((section) => section.section_id === selectedEditSectionId);
    const copyField = selectedEditCopyField || selectedSection?.copy_ref?.fields?.[0] || "";
    if (conversationalMode === "copy" && (!conversationalCopy.trim() || !copyField)) {
      setMessage("카피 수정에는 새 문구가 필요합니다.");
      return;
    }
    setWorking(true);
    setMessage(null);
    try {
      const payload = conversationalMode === "copy"
        ? {
          scope: "copy",
          target_ids: [selectedEditSectionId],
          operation: "rewrite",
          instruction: conversationalInstruction.trim(),
          copy_changes: { [selectedEditSectionId]: { [copyField]: conversationalCopy.trim() } },
          selected_section_id: selectedEditSectionId,
          ...(selectedEditElementId ? { selected_element_id: selectedEditElementId } : {}),
        }
        : {
          scope: "page",
          target_ids: [completedDetailPageVersionId],
          operation: "canvas_draft",
          instruction: conversationalInstruction.trim(),
          selected_section_id: selectedEditSectionId,
          ...(selectedEditElementId ? { selected_element_id: selectedEditElementId } : {}),
        };
      const response = await fetch(
        apiUrl(`/api/v1/projects/${projectId}/page/versions/${completedDetailPageVersionId}/edit-runs`),
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "include",
          body: JSON.stringify(payload),
        },
      );
      const result = await response.json().catch(() => null);
      if (!response.ok || !result?.run_id) {
        throw new Error(typeof result?.detail === "string" ? result.detail : "LG-11 편집 실행을 시작하지 못했습니다.");
      }
      resolvedRunIdRef.current = result.run_id;
      const url = new URL(window.location.href);
      url.searchParams.set("runId", result.run_id);
      window.history.replaceState({}, "", `${url.pathname}${url.search}${url.hash}`);
      setConversationalInstruction("");
      setConversationalCopy("");
      await load(false);
    } catch (caught: unknown) {
      const detail = String((caught as { message?: unknown } | null)?.message || "");
      const error = new globalThis.Error(detail);
      setMessage(error instanceof Error ? error.message : "LG-11 편집 실행을 시작하지 못했습니다.");
    } finally {
      setWorking(false);
    }
    */
  };

  if (loading) return <section className="mx-auto mb-5 max-w-4xl rounded-xl border border-slate-200 bg-white p-4 text-sm text-slate-500">승인 상태를 확인하는 중...</section>;
  const quality = view?.values.quality;
  const qualityReworkActive = quality?.quality_bar_verdict === "FAIL"
    && ["quality_selective_rework", "quality_copy_rework", "quality_image_rework", "quality_visual_rework"].includes(view?.current_stage || "");
  if (view?.status === "failed" && !qualityReworkActive) {
    const failure = view.values.execution?.last_error;
    const guidance = failure?.seller_guidance;
    return <section role="alert" className="mx-auto mb-5 max-w-4xl rounded-xl border border-rose-300 bg-rose-50 p-5 text-sm text-rose-950">
      <p className="text-xs font-bold text-rose-700">작업 확인 필요</p>
      <h2 className="mt-1 font-black">{guidance?.cause_ko || "다음 단계로 진행하지 못했습니다"}</h2>
      <p className="mt-2 leading-6">{guidance?.action_ko || "원인을 해결한 뒤 같은 작업을 다시 시도해 주세요."}</p>
      <div className="mt-4 flex flex-wrap gap-2">
        <button type="button" onClick={() => void load()} disabled={working} className="rounded-lg border border-rose-300 bg-white px-3 py-2 text-xs font-bold text-rose-800 disabled:opacity-50">상태 새로고침</button>
        <button type="button" onClick={() => void retryFailedRun()} disabled={working || failure?.recoverable === false} className="rounded-lg bg-rose-700 px-3 py-2 text-xs font-bold text-white disabled:opacity-50">{working ? "재개 중..." : "원인 해결 후 같은 실행 재시도"}</button>
      </div>
      {message ? <p role="status" className="mt-3 text-xs font-semibold text-rose-800">{message}</p> : null}
    </section>;
  }
  if (!view && loadIssue) {
    return <section role="alert" className="mx-auto mb-5 max-w-4xl rounded-xl border border-amber-300 bg-amber-50 p-5 text-sm text-amber-950">
      <p className="text-xs font-bold text-amber-700">작업 실행 주소 확인 필요</p>
      <h2 className="mt-1 font-black">승인할 실행을 찾지 못했습니다</h2>
      <p className="mt-2 leading-6">{loadIssue}</p>
      <button type="button" onClick={() => void load()} className="mt-4 rounded-lg border border-amber-300 bg-white px-3 py-2 text-xs font-bold text-amber-900">현재 실행 다시 찾기</button>
    </section>;
  }
  const pending = view?.values.review?.pending;
  if (!view) return null;
  const delayContext = view.values.execution?.delay_context;
  const etaText = delayContext?.eta_status === "estimated" && delayContext.eta_range_seconds
    ? `예상 남은 시간 ${delayContext.eta_range_seconds.min}~${delayContext.eta_range_seconds.max}초`
    : delayContext?.eta_status === "paused_for_review" ? "확인 전까지 예상 시간은 멈춥니다."
    : delayContext?.eta_status === "overdue" ? "예상 시간보다 오래 걸리고 있어 상태를 계속 확인합니다."
    : "예상 시간을 계산할 표본이 아직 충분하지 않습니다.";
  const delayNotice = delayContext ? <div className="mt-3 rounded-lg border border-violet-200 bg-white px-3 py-2 text-xs text-violet-950" data-testid="seller-delay-context"><p className="font-bold">{delayContext.current_stage_ko}</p><p className="mt-1">{delayContext.delay_cause_ko} {delayContext.seller_guidance.action_ko}</p><p className="mt-1 text-slate-600">{etaText}</p></div> : null;
  const progressivePreview = view.values.execution?.progress_preview;
  const progressivePreviewNotice = progressivePreview && progressivePreview.total_sections > 0 ? <section className="mt-3 rounded-lg border border-emerald-200 bg-white p-3 text-xs text-emerald-950" data-testid="seller-progressive-preview">
    <p className="font-bold">상세페이지 준비 상태</p>
    <p className="mt-1">완료된 섹션 {progressivePreview.completed_count}/{progressivePreview.total_sections} · {progressivePreview.progress_percent}%</p>
    {progressivePreview.completed_count > 0 ? <ul className="mt-2 space-y-1 text-slate-600">{progressivePreview.completed_sections.map((section, index) => <li key={section.section_id}>완료된 섹션 {index + 1}{section.summary ? ` · ${section.summary}` : ""}</li>)}</ul> : null}
    {progressivePreview.pending_sections.length > 0 ? <p className="mt-1 text-slate-600">나머지 섹션을 준비하고 있습니다.</p> : null}
  </section> : null;
  if (!pending) {
    if (delayNotice) return <section className="mx-auto mb-5 max-w-4xl rounded-xl border border-violet-200 bg-violet-50 p-4 text-sm text-violet-950">{delayNotice}{progressivePreviewNotice}</section>;
    if (qualityReworkActive) {
      const reworkMessages: Record<string, string> = {
        COPY_REWORK: "문구 품질을 자동으로 수정하고 있습니다.",
        IMAGE_REWORK: "이미지 품질을 자동으로 수정하고 있습니다.",
        VISUAL_REWORK: "화면 구성 품질을 자동으로 수정하고 있습니다.",
        BLOCKED_POLICY: "판매 전 확인이 필요한 항목을 점검하고 있습니다.",
      };
      const reworkMessage = reworkMessages[quality?.routing_code || ""] || "품질 기준을 다시 확인하고 있습니다.";
      return <section className="mx-auto mb-5 max-w-4xl rounded-xl border border-amber-200 bg-amber-50 p-5 text-sm text-amber-950" data-testid="lg12-quality-rework">
        <p className="text-xs font-bold text-amber-700">최종 품질 검토</p>
        <h2 className="mt-1 font-black">{reworkMessage}</h2>
        {progressivePreviewNotice}
        <dl className="mt-3 grid gap-2 rounded-lg border border-amber-200 bg-white p-3 text-xs sm:grid-cols-3">
          <div><dt className="font-bold text-slate-700">현재 품질 상태</dt><dd>수정이 필요합니다</dd></div>
          <div><dt className="font-bold text-slate-700">자동 수정</dt><dd>진행 중</dd></div>
          <div><dt className="font-bold text-slate-700">최종 사용 및 내보내기</dt><dd>수정이 끝날 때까지 사용할 수 없습니다</dd></div>
        </dl>
        <p className="mt-3 text-xs leading-5">자동 수정 결과를 기다려 주세요. 추가 확인이 필요하면 알려드리겠습니다.</p>
      </section>;
    }
    const intake = view.values.intake;
    const briefVersion = intake?.creative_brief?.brief_version;
    const masterVersion = intake?.commerce_creative_master?.master_version;
    if (view.status === "completed" && view.current_stage === "master_ready" && masterVersion?.id) {
      return <section className="mx-auto mb-5 max-w-4xl rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-950" data-testid="lg12i-master-ready">
        <p className="text-xs font-bold text-emerald-700">LG-12I Commerce Creative Master 준비 완료</p>
        <h2 className="mt-1 font-black">상품 사실과 판매자 확인을 고정한 Creative Master가 준비되었습니다</h2>
        <p className="mt-1 text-xs leading-5 text-slate-600">새 페이지나 이미지 생성은 아직 시작하지 않았습니다. 이후 Planning 단계는 이 immutable Master reference를 사용합니다.</p>
        <dl className="mt-3 grid gap-2 rounded-lg border border-emerald-200 bg-white p-3 text-xs sm:grid-cols-2">
          <div><dt className="font-bold text-slate-700">Master</dt><dd>{masterVersion.id} · v{masterVersion.version || 1}</dd></div>
          <div><dt className="font-bold text-slate-700">Creative Brief</dt><dd>{briefVersion?.id || "연결된 Brief"}{briefVersion?.version ? ` · v${briefVersion.version}` : ""}</dd></div>
          <div><dt className="font-bold text-slate-700">입력 방식</dt><dd>{intake?.input_mode || intake?.envelope?.input_mode || "-"} · {intake?.requested_generation_mode || intake?.envelope?.requested_generation_mode || "-"}</dd></div>
          <div><dt className="font-bold text-slate-700">대상 채널</dt><dd>{(intake?.target_channels || intake?.envelope?.target_channels || []).join(", ") || "-"}</dd></div>
        </dl>
      </section>;
    }
    const completedJobs = (view.values.generation?.jobs || []).filter((job) => job.output_asset_id);
    const detailPageVersionId = view.values.rendering?.detail_page_version?.id
      || view.values.edit?.version_restore?.detail_page_version_id;
    if (view.status === "completed" && view.current_stage === "quality_promotion_ready" && detailPageVersionId) {
      const promoted = qualityStatus?.promotion_status === "promoted";
      const channels = Object.entries(qualityStatus?.export_readiness || {});
      return <section className="mx-auto mb-5 max-w-4xl rounded-xl border border-emerald-200 bg-emerald-50 p-5 text-sm text-emerald-950" data-testid="lg12-quality-status">
        <p className="text-xs font-bold text-emerald-700">최종 품질 검토</p>
        <h2 className="mt-1 font-black">{promoted ? "상세페이지를 내보낼 준비가 되었습니다" : "품질 검토를 통과했습니다"}</h2>
        <p className="mt-2 leading-6">{promoted ? "현재 상세페이지 버전만 내보낼 수 있습니다." : "최종 사용 가능 상태로 전환하면 선택한 채널의 내보내기가 열립니다."}</p>
        <dl className="mt-3 grid gap-2 rounded-lg border border-emerald-200 bg-white p-3 text-xs sm:grid-cols-3">
          <div><dt className="font-bold text-slate-700">현재 버전</dt><dd>{detailPageVersionId}</dd></div>
          <div><dt className="font-bold text-slate-700">품질 상태</dt><dd>{qualityStatus?.quality_verdict === "PASS" ? "품질 검토 통과" : "상태 확인 중"}</dd></div>
          <div><dt className="font-bold text-slate-700">자동 수정</dt><dd>{qualityStatus?.attempt_summary?.automatic_rework_count || 0}회</dd></div>
        </dl>
        {!promoted ? <button type="button" data-testid="lg12-promote-page" onClick={() => void promoteQualityPage()} disabled={working || qualityStatus?.status === "needs_attention"} className="mt-4 rounded-lg bg-emerald-700 px-3 py-2 text-xs font-bold text-white disabled:opacity-50">{working ? "처리 중..." : "최종 사용 가능 상태로 전환"}</button> : <div className="mt-4 flex flex-wrap gap-2">{channels.filter(([, ready]) => ready).map(([channel]) => <a key={channel} data-testid={`lg12-export-ready-${channel}`} href={`/workspace/projects/${projectId}/render?version_id=${encodeURIComponent(detailPageVersionId)}&channel=${channel}`} className="rounded-lg bg-emerald-700 px-3 py-2 text-xs font-bold text-white">{channel === "smartstore" ? "SmartStore 미리보기" : "Coupang 미리보기"}</a>)}{qualityStatus?.export_readiness?.smartstore ? <button type="button" data-testid="lg12-smartstore-standalone-export" onClick={() => void createStandaloneExport(detailPageVersionId, "smartstore")} disabled={standaloneExporting} className="rounded-lg border border-emerald-300 bg-white px-3 py-2 text-xs font-bold text-emerald-800 disabled:opacity-50">{standaloneExporting ? "SmartStore HTML/ZIP 준비 중..." : "SmartStore HTML/ZIP 내보내기"}</button> : null}</div>}
        {standaloneExport ? <div className="mt-3 flex flex-wrap gap-2" data-testid="lg12-smartstore-export-downloads"><a data-testid="lg12-smartstore-html-download" href={apiUrl(standaloneExport.html_download_url)} className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-xs font-bold text-slate-800">SmartStore HTML 다운로드</a><a data-testid="lg12-smartstore-zip-download" href={apiUrl(standaloneExport.zip_download_url)} className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-xs font-bold text-slate-800">SmartStore ZIP 다운로드</a></div> : null}
        {qualityStatus?.review_required ? <p className="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">확인이 필요한 항목이 있습니다. 기존 검토 단계에서 필요한 정보를 확인해 주세요.</p> : null}
        {qualityStatus?.message ? <p role="status" className="mt-3 text-xs text-slate-700">{qualityStatus.message}</p> : null}
        {message ? <p role="status" className="mt-3 text-xs font-semibold text-emerald-800">{message}</p> : null}
      </section>;
    }
    if (view.status === "completed" && (completedJobs.length > 0 || detailPageVersionId)) {
      return <section className="mx-auto mb-5 max-w-4xl rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-950" data-testid="lg5r-completed-gallery">
        <p className="text-xs font-bold text-emerald-700">상세페이지 생성 완료</p>
        <h2 className="mt-1 font-black">{completedJobs.length > 0 ? "승인된 장면 결과" : "정보형 상세페이지 결과"}</h2>
        <p className="mt-1 text-xs leading-5 text-slate-600">{completedJobs.length > 0 ? "이 실행에서 승인한 이미지를 다시 확인할 수 있습니다." : "추가 이미지 생성 없이 정보와 권리 보유 원본으로 상세페이지를 완성했습니다."}</p>
        {completedJobs.length > 0 ? <div className="mt-4 grid gap-3 sm:grid-cols-2">
          {completedJobs.map((job) => <figure key={job.job_id} className="overflow-hidden rounded-lg border border-emerald-100 bg-white">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={apiUrl(`/api/v1/files/assets/${job.output_asset_id}`)} alt={`${job.role || job.section_id || "장면"} 승인 이미지`} className="aspect-square w-full object-contain" loading="lazy" />
            <figcaption className="border-t border-emerald-100 px-3 py-2 text-xs"><b>{job.role || job.section_id || job.job_id}</b> · {job.status}</figcaption>
          </figure>)}
        </div> : null}
        {detailPageVersionId ? <div className="mt-4 flex flex-wrap gap-2">
          <label className="inline-flex items-center gap-1 rounded-lg border border-emerald-200 bg-white px-2 text-xs font-semibold text-emerald-900">채널<select data-testid="lg11-channel-preview" value={previewChannel} onChange={(event) => setPreviewChannel(event.target.value as "smartstore" | "coupang")} className="bg-transparent py-2 outline-none"><option value="smartstore">스마트스토어</option><option value="coupang">쿠팡</option></select></label>
          <a data-testid="lg11-channel-preview-link" href={`/workspace/projects/${projectId}/render?version_id=${encodeURIComponent(detailPageVersionId)}&channel=${previewChannel}`} className="inline-flex rounded-lg bg-emerald-700 px-3 py-2 text-xs font-bold text-white">완성 상세페이지 미리보기</a>
          <button type="button" data-testid="lg10-standalone-export" onClick={() => void createStandaloneExport(detailPageVersionId)} disabled={standaloneExporting} className="rounded-lg border border-emerald-300 bg-white px-3 py-2 text-xs font-bold text-emerald-800 disabled:opacity-50">{standaloneExporting ? "HTML/ZIP 준비 중..." : "HTML/ZIP 내보내기"}</button>
          {standaloneExport ? <><button type="button" data-testid="lg10-copyable-html-copy" onClick={() => void copyLg10Html()} className="rounded-lg border border-emerald-300 bg-white px-3 py-2 text-xs font-bold text-emerald-800">쇼핑몰 HTML 코드 복사</button><a data-testid="lg10-copyable-html-download" href={apiUrl(standaloneExport.html_download_url)} className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-xs font-bold text-slate-800">독립 실행 HTML 다운로드</a><a data-testid="lg10-standalone-zip-download" href={apiUrl(standaloneExport.zip_download_url)} className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-xs font-bold text-slate-800">독립 실행 ZIP 다운로드</a></> : null}
        </div> : null}
        {detailPageVersionId ? <div className="mt-4 rounded-lg border border-emerald-200 bg-white p-3 text-xs" data-testid="lg11-selected-conversation-editor">
          <div className="mb-2 flex flex-wrap gap-2">
            <button type="button" data-testid="lg11-edit-preview" onClick={() => void previewSelectedLg11Edit()} disabled={working || !conversationalInstruction.trim()} className="rounded border border-emerald-300 bg-emerald-50 px-3 py-2 font-bold text-emerald-900 disabled:opacity-50">Impact preview</button>
            {conversationalPreview ? <div data-testid="lg11-edit-impact-preview" className="basis-full rounded border border-amber-200 bg-amber-50 p-3"><p className="font-bold">Impact preview</p><p>sections: {(conversationalPreview.impact_preview.affected_artifacts?.section_ids || []).join(", ") || "none"}</p><p>scenes: {(conversationalPreview.impact_preview.affected_artifacts?.scene_ids || []).join(", ") || "none"}</p><p>assets: {(conversationalPreview.impact_preview.affected_artifacts?.assets || []).map((asset) => `${asset.asset_id}:${asset.asset_content_hash}`).join(", ") || "none"}</p><p>copy refs: {(conversationalPreview.impact_preview.affected_artifacts?.copy_artifacts || []).map((copy) => `${copy.artifact_key}:${copy.artifact_hash}`).join(", ") || "none"}</p><p>facts/evidence: {(conversationalPreview.impact_preview.affected_artifacts?.facts || []).map((fact) => `${fact.fact_id}:${(fact.evidence_ids || []).join("/")}`).join(", ") || "none"}</p><p>layout/style: {(conversationalPreview.impact_preview.affected_artifacts?.style_layout_tokens || []).map((item) => `${item.section_id}:${item.layout_token}`).join(", ") || "none"}</p><p>provider cost: {JSON.stringify(conversationalPreview.impact_preview.expected_provider_cost || {})}</p><p>Brand Kit: {JSON.stringify(conversationalPreview.impact_preview.affected_artifacts?.brand_kit || {})}</p><p>evidence review: {String(Boolean(conversationalPreview.impact_preview.requires_evidence_review))}</p><p>execution blocked: {String(Boolean(conversationalPreview.impact_preview.execution_blocked))}</p><button type="button" data-testid="lg11-edit-confirm" onClick={() => void startConfirmedLg11Edit()} disabled={working || Boolean(conversationalPreview.impact_preview.execution_blocked)} className="mt-2 rounded bg-emerald-700 px-3 py-2 font-bold text-white disabled:opacity-50">Confirm and start edit</button></div> : null}
            <select data-testid="lg11-edit-route" value={conversationalMode} onChange={(event) => { setConversationalMode(event.target.value as typeof conversationalMode); setConversationalPreview(null); setConfirmedEditPayload(null); }} className="rounded border border-slate-300 bg-white px-2 py-1">
              <option value="canvas">Canvas edit</option><option value="copy">Copy edit</option><option value="fact">Fact change</option><option value="style">Style / Brand Kit</option><option value="scene_regenerate">Scene regenerate</option><option value="asset_replace">Scene asset replace</option><option value="restore">Frozen restore</option>
            </select>
            {conversationalMode === "scene_regenerate" || conversationalMode === "asset_replace" ? <><select data-testid="lg11-edit-scene" value={selectedEditSceneId} onChange={(event) => { setSelectedEditSceneId(event.target.value); setConversationalPreview(null); setConfirmedEditPayload(null); }} className="rounded border border-slate-300 bg-white px-2 py-1"><option value="">Scene</option>{Array.from(new Set(frozenCanvasSections.flatMap((section) => (section.approved_assets || []).map((asset) => asset.scene_id || "")).filter(Boolean))).map((sceneId) => <option key={sceneId} value={sceneId}>{sceneId}</option>)}</select>{conversationalMode === "asset_replace" ? <select data-testid="lg11-edit-replacement-asset" value={selectedReplacementAssetId} onChange={(event) => { setSelectedReplacementAssetId(event.target.value); setConversationalPreview(null); setConfirmedEditPayload(null); }} className="rounded border border-slate-300 bg-white px-2 py-1"><option value="">Rights-approved asset</option>{uploadAssets.map((asset) => <option key={asset.id} value={asset.id}>{asset.filename}</option>)}</select> : null}</> : null}
            {conversationalMode === "style" ? <><select data-testid="lg11-edit-direction" value={selectedDesignDirection} onChange={(event) => { setSelectedDesignDirection(event.target.value); setConversationalPreview(null); setConfirmedEditPayload(null); }} className="rounded border border-slate-300 bg-white px-2 py-1"><option value="safe_information">safe_information</option><option value="image_centric">image_centric</option><option value="balanced_sale">balanced_sale</option></select><select data-testid="lg11-edit-brand-kit" value={selectedBrandKitVersionId} onChange={(event) => { setSelectedBrandKitVersionId(event.target.value); setConversationalPreview(null); setConfirmedEditPayload(null); }} className="rounded border border-slate-300 bg-white px-2 py-1"><option value="">Current Brand Kit</option>{brandKitVersionOptions.map((kit) => <option key={kit.id} value={kit.id}>Brand Kit v{kit.version || ""}</option>)}</select></> : null}
            {conversationalMode === "restore" ? <select data-testid="lg11-restore-version" value={selectedRestoreVersionId} onChange={(event) => { setSelectedRestoreVersionId(event.target.value); setConversationalPreview(null); setConfirmedEditPayload(null); }} className="rounded border border-slate-300 bg-white px-2 py-1"><option value="">Frozen version to restore</option>{frozenVersionOptions.filter((version) => version.id !== detailPageVersionId && version.lg11_frozen).map((version) => <option key={version.id} value={version.id}>{version.name || version.id}</option>)}</select> : null}
          </div>
          <p className="font-bold text-emerald-900">선택 요소 기반 편집</p>
          <p className="mt-1 text-slate-600">현재 frozen version의 선택 대상만 LG-11 확인 흐름으로 전달합니다.</p>
          <div className="mt-2 flex flex-wrap gap-2">
            <select data-testid="lg11-edit-section" value={selectedEditSectionId} onChange={(event) => { const nextSectionId = event.target.value; const nextSection = frozenCanvasSections.find((section) => section.section_id === nextSectionId); setSelectedEditSectionId(nextSectionId); setSelectedEditElementId(""); setSelectedEditCopyField(nextSection?.copy_ref?.fields?.[0] || ""); setConversationalPreview(null); setConfirmedEditPayload(null); }} className="rounded border border-slate-300 bg-white px-2 py-1">
              <option value="">섹션 선택</option>
              {frozenCanvasSections.map((section) => <option key={section.section_id} value={section.section_id}>{section.section_id}</option>)}
            </select>
            <select data-testid="lg11-edit-element" value={selectedEditElementId} onChange={(event) => { setSelectedEditElementId(event.target.value); setConversationalPreview(null); setConfirmedEditPayload(null); }} className="rounded border border-slate-300 bg-white px-2 py-1">
              <option value="">섹션 전체</option>
              {(frozenCanvasSections.find((section) => section.section_id === selectedEditSectionId)?.canvas_elements || []).map((element) => <option key={element.element_id} value={element.element_id}>{element.kind} · {element.element_id}</option>)}
            </select>
            <select data-testid="lg11-edit-mode" value={conversationalMode} onChange={(event) => { setConversationalMode(event.target.value as typeof conversationalMode); setConversationalPreview(null); setConfirmedEditPayload(null); }} className="rounded border border-slate-300 bg-white px-2 py-1"><option value="canvas">Canvas 편집</option><option value="copy">카피 수정</option><option value="fact">사실값 수정</option><option value="style">스타일·Brand Kit</option><option value="scene_regenerate">장면 재생성</option><option value="asset_replace">장면 자산 교체</option><option value="restore">frozen 버전 복원</option></select>
          </div>
          <textarea data-testid="lg11-edit-instruction" value={conversationalInstruction} onChange={(event) => setConversationalInstruction(event.target.value)} placeholder="예: 선택한 요소를 오른쪽으로 옮겨 주세요" className="mt-2 min-h-16 w-full rounded border border-slate-300 p-2" />
          {conversationalMode === "copy" ? <><select data-testid="lg11-edit-copy-field" value={selectedEditCopyField || frozenCanvasSections.find((section) => section.section_id === selectedEditSectionId)?.copy_ref?.fields?.[0] || ""} onChange={(event) => setSelectedEditCopyField(event.target.value)} className="mt-2 rounded border border-slate-300 bg-white px-2 py-1"><option value="">카피 필드 선택</option>{(frozenCanvasSections.find((section) => section.section_id === selectedEditSectionId)?.copy_ref?.fields || []).map((field) => <option key={field} value={field}>{field}</option>)}</select><textarea data-testid="lg11-edit-copy" value={conversationalCopy} onChange={(event) => setConversationalCopy(event.target.value)} placeholder="새 문구" className="mt-2 min-h-16 w-full rounded border border-slate-300 p-2" /></> : null}
          <button type="button" data-testid="lg11-edit-start" onClick={() => void startSelectedLg11Edit()} disabled={working || !selectedEditSectionId || !conversationalInstruction.trim() || (conversationalMode === "copy" && !conversationalCopy.trim())} className="mt-2 rounded border border-emerald-300 bg-emerald-50 px-3 py-2 font-bold text-emerald-900 disabled:opacity-50">영향 미리보기·확인 시작</button>
        </div> : null}
        {standaloneExport ? <details className="mt-3 rounded-lg border border-emerald-100 bg-white p-3 text-xs text-slate-700"><summary className="cursor-pointer font-bold text-emerald-800">복사할 쇼핑몰 HTML 코드 보기</summary><textarea ref={copyableHtmlRef} data-testid="lg10-copyable-html-code" readOnly value={standaloneExport.copyable_html} className="mt-3 h-40 w-full rounded border border-slate-200 p-2 font-mono text-[10px] text-slate-700" aria-label="쇼핑몰에 붙여넣을 HTML 코드" /></details> : null}
        {message ? <p role="status" className="mt-3 text-xs font-semibold text-emerald-800">{message}</p> : null}
      </section>;
    }
    return null;
  }
  if (hidePlanningAction && pending.review_stage === "planning_review") {
    return <section className="mx-auto mb-5 max-w-4xl rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-900">스토리보드가 승인 대기 중입니다. 아래의 <b>스토리보드 승인</b> 버튼은 동일한 작업 실행을 재개합니다.</section>;
  }
  const generationWaiting = pending.review_stage === "generation_pending";
  const providerWaiting = pending.review_stage === "provider_wait";
  const imageReview = pending.review_stage === "image_review";
  const canvasEdit = pending.review_stage === "canvas_edit";
  const slo08Choice = pending.seller_choice?.choice_required === true;
  const canvasSections = view.values.canvas?.canonical_page_assembly_input?.sections || [];
  const canvasFinalSpecIndex = canvasSections.findIndex((section) => section.section_id === "specs" || section.section_id.endsWith("_specs"));
  const canvasAddPosition = canvasFinalSpecIndex >= 0 ? canvasFinalSpecIndex : canvasSections.length;
  const canvasOperation = (kind: string, sectionId?: string, extra: Record<string, unknown> = {}) => ({
    operation_id: `${kind}-${sectionId || "draft"}-${crypto.randomUUID()}`,
    kind,
    ...(sectionId ? { section_id: sectionId } : {}),
    ...extra,
  });
  const canvasGroups = view.values.canvas?.element_groups || [];
  const canvasReplacementAssets = Array.from(new Map<string, { id: string; filename: string; content_hash: string }>([
    ...canvasSections.flatMap((section) => (section.canvas_elements || [])
      .filter((element) => element.kind === "asset" && element.asset_id && element.asset_content_hash)
      .map((element) => [element.asset_id!, { id: element.asset_id!, filename: "승인된 장면 자산", content_hash: element.asset_content_hash! }] as const)),
    ...uploadAssets.flatMap((asset) => asset.content_hash
      ? [[asset.id, { id: asset.id, filename: asset.filename, content_hash: asset.content_hash }] as const]
      : []),
  ]).values());
  const canvasElementControls = <div className="mt-3 space-y-2 rounded border border-violet-100 bg-white p-3 text-xs" data-testid="lg11-canvas-elements">
    <div className="flex flex-wrap items-center justify-between gap-2"><p className="font-bold">내부 요소 · 레이어</p><button type="button" data-testid="lg11-canvas-group-selected" disabled={working || selectedCanvasElements.length < 2} onClick={() => void resume("apply", { canvasOperation: canvasOperation("group", undefined, { element_ids: selectedCanvasElements }) })} className="rounded border px-2 py-1">선택 요소 그룹화</button></div>
    {canvasSections.map((section) => <div key={`${section.section_id}-elements`} className="border-t pt-2"><p className="font-semibold">{section.section_id}</p><div className="flex gap-1"><button type="button" data-testid={`lg11-canvas-add-mask-${section.section_id}`} onClick={() => void resume("apply", { canvasOperation: canvasOperation("create_element", section.section_id, { element_kind: "mask", token: "rounded" }) })} className="rounded border px-2 py-1">마스크 추가</button><button type="button" data-testid={`lg11-canvas-add-icon-${section.section_id}`} onClick={() => void resume("apply", { canvasOperation: canvasOperation("create_element", section.section_id, { element_kind: "icon", token: "check" }) })} className="rounded border px-2 py-1">아이콘 추가</button><button type="button" data-testid={`lg11-canvas-add-decorative-${section.section_id}`} onClick={() => void resume("apply", { canvasOperation: canvasOperation("create_element", section.section_id, { element_kind: "decorative", token: "divider" }) })} className="rounded border px-2 py-1">장식 추가</button></div>{(section.canvas_elements || []).filter((element) => !element.deleted).map((element) => <div key={element.element_id} className="mt-1 flex flex-wrap items-center gap-1" data-testid={`lg11-canvas-element-${element.element_id}`}><input aria-label={`${element.element_id} 선택`} type="checkbox" checked={selectedCanvasElements.includes(element.element_id)} onChange={() => setSelectedCanvasElements((current) => current.includes(element.element_id) ? current.filter((value) => value !== element.element_id) : [...current, element.element_id])}/><span>{element.kind} · z{element.z_index}{element.locked ? " · 잠김" : ""}</span><button type="button" data-testid={`lg11-canvas-move-${element.element_id}`} disabled={working} onClick={() => void resume("apply", { canvasOperation: canvasOperation("move_element", section.section_id, { element_id: element.element_id, dx: 10, dy: 0 }) })} className="rounded border px-2 py-1">오른쪽 이동</button><button type="button" data-testid={`lg11-canvas-resize-${element.element_id}`} disabled={working} onClick={() => void resume("apply", { canvasOperation: canvasOperation("resize_element", section.section_id, { element_id: element.element_id, width: Math.min(760, element.width + 10), height: element.height }) })} className="rounded border px-2 py-1">너비 +10</button><button type="button" data-testid={`lg11-canvas-z-${element.element_id}`} disabled={working} onClick={() => void resume("apply", { canvasOperation: canvasOperation("set_z_order", section.section_id, { element_id: element.element_id, z_index: Math.min(100, element.z_index + 1) }) })} className="rounded border px-2 py-1">앞으로</button><button type="button" data-testid={`lg11-canvas-lock-${element.element_id}`} disabled={working} onClick={() => void resume("apply", { canvasOperation: canvasOperation("set_lock", section.section_id, { element_id: element.element_id, locked: !element.locked }) })} className="rounded border px-2 py-1">{element.locked ? "잠금 해제" : "잠금"}</button><button type="button" data-testid={`lg11-canvas-duplicate-${element.element_id}`} disabled={working} onClick={() => void resume("apply", { canvasOperation: canvasOperation("duplicate_element", section.section_id, { element_id: element.element_id }) })} className="rounded border px-2 py-1">요소 복제</button><button type="button" data-testid={`lg11-canvas-delete-${element.element_id}`} disabled={working} onClick={() => void resume("apply", { canvasOperation: canvasOperation("delete_element", section.section_id, { element_id: element.element_id }) })} className="rounded border border-rose-300 px-2 py-1">요소 삭제</button>{element.kind === "asset" ? <><select aria-label={`${element.element_id} 교체 자산`} value={canvasAssetReplacements[element.element_id] || ""} onChange={(event) => setCanvasAssetReplacements((current) => ({ ...current, [element.element_id]: event.target.value }))}><option value="">권리 보유 자산 선택</option>{canvasReplacementAssets.map((asset) => <option key={asset.id} value={asset.id}>{asset.filename}</option>)}</select><button type="button" data-testid={`lg11-canvas-replace-${element.element_id}`} disabled={working || !canvasAssetReplacements[element.element_id]} onClick={() => { const asset = canvasReplacementAssets.find((item) => item.id === canvasAssetReplacements[element.element_id]); if (asset?.content_hash) void resume("apply", { canvasOperation: canvasOperation("replace_element", section.section_id, { element_id: element.element_id, asset_id: asset.id, asset_content_hash: asset.content_hash }) }); }} className="rounded border px-2 py-1">자산 교체</button></> : null}</div>)}</div>)}
    {canvasGroups.map((group) => <div key={group.group_id} className="flex flex-wrap items-center gap-1 border-t pt-2" data-testid={`lg11-canvas-group-${group.group_id}`}><span>그룹 {group.group_id.slice(-6)} · {group.child_element_ids.length}개{group.locked ? " · 잠김" : ""}</span><button type="button" disabled={working} onClick={() => void resume("apply", { canvasOperation: canvasOperation("move_group", group.section_id, { group_id: group.group_id, dx: 10, dy: 0 }) })} className="rounded border px-2 py-1">그룹 이동</button><button type="button" disabled={working} onClick={() => void resume("apply", { canvasOperation: canvasOperation("set_lock", group.section_id, { group_id: group.group_id, locked: !group.locked }) })} className="rounded border px-2 py-1">{group.locked ? "그룹 잠금 해제" : "그룹 잠금"}</button><button type="button" disabled={working || group.locked} onClick={() => void resume("apply", { canvasOperation: canvasOperation("ungroup", group.section_id, { group_id: group.group_id }) })} className="rounded border px-2 py-1">그룹 해제</button></div>)}
  </div>;
  const jobs = view.values.generation?.jobs || [];
  const costPlan = view.values.generation?.cost_plan;
  return <section
    className="mx-auto mb-5 max-w-4xl rounded-xl border border-violet-200 bg-violet-50 p-4 text-sm text-violet-950"
    data-testid={`graph-review-${pending.review_stage}`}
  >
    {recoveryNotice ? <p role="status" className="mb-3 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs font-semibold text-emerald-900">{recoveryNotice}</p> : null}
    {delayNotice}
    {progressivePreviewNotice}
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div><p className="text-xs font-bold text-violet-700">확인 필요</p><h2 className="mt-1 font-black">{pending.seller_guidance?.cause_ko || pending.title}</h2><p className="mt-1 leading-5 text-slate-700">{pending.seller_guidance?.action_ko || pending.description}</p></div>
      {slo08Choice ? <div className="flex flex-wrap gap-2" data-testid="seller-slo08-choice">{pending.seller_choice?.available_actions.includes("fallback") ? <><label className="flex items-center gap-1 text-xs"><input type="checkbox" checked={slo08Attested} onChange={(event) => setSlo08Attested(event.target.checked)} /> 이 사진의 사용 권한을 확인했습니다</label><button type="button" data-testid="seller-slo08-fallback" onClick={() => void resume("fallback", { sellerAttested: slo08Attested })} disabled={working || !slo08Attested} className="rounded-lg bg-emerald-600 px-3 py-2 text-xs font-bold text-white disabled:opacity-50">기존 사진으로 계속하기</button></> : null}<button type="button" data-testid="seller-slo08-wait" onClick={() => void resume("wait")} disabled={working} className="rounded-lg border border-violet-300 bg-white px-3 py-2 text-xs font-bold text-violet-800 disabled:opacity-50">대기 상태로 유지</button></div> : generationWaiting ? <div className="flex gap-2"><button type="button" onClick={() => void resume("defer")} disabled={working} className="rounded-lg border border-violet-300 bg-white px-3 py-2 text-xs font-bold text-violet-800 disabled:opacity-50">대기 상태 저장</button><button type="button" onClick={() => void resume("approve")} disabled={working} className="rounded-lg bg-emerald-600 px-3 py-2 text-xs font-bold text-white disabled:opacity-50">{working ? "확인 중..." : "비용 승인 후 이미지 생성"}</button></div> : providerWaiting ? <button type="button" onClick={() => void resume("refresh")} disabled={working} className="rounded-lg border border-violet-300 bg-white px-3 py-2 text-xs font-bold text-violet-800 disabled:opacity-50">{working ? "확인 중..." : "작업 상태 새로고침"}</button> : imageReview ? <p className="rounded-lg bg-white px-3 py-2 text-xs font-bold text-violet-800">아래 장면별로 승인·거절·재생성·직접 업로드를 선택하세요.</p> : canvasEdit ? <div className="flex flex-wrap gap-2"><button type="button" onClick={() => void resume("undo", { canvasOperation: canvasOperation("undo") })} disabled={working} className="rounded-lg border px-3 py-2 text-xs font-bold">실행 취소</button><button type="button" onClick={() => void resume("redo", { canvasOperation: canvasOperation("redo") })} disabled={working} className="rounded-lg border px-3 py-2 text-xs font-bold">다시 실행</button><button type="button" onClick={() => void resume("commit", { canvasOperation: canvasOperation("commit") })} disabled={working} className="rounded-lg bg-emerald-600 px-3 py-2 text-xs font-bold text-white">변경 저장</button></div> : <div className="flex gap-2"><button type="button" onClick={() => void resume("reject")} disabled={working} className="rounded-lg border border-rose-300 bg-white px-3 py-2 text-xs font-bold text-rose-700 disabled:opacity-50">수정 후 재검토</button><button type="button" onClick={() => void resume("approve")} disabled={working} className="rounded-lg bg-emerald-600 px-3 py-2 text-xs font-bold text-white disabled:opacity-50">{working ? "승인 중..." : "확인·다음 단계"}</button></div>}
    </div>
    {canvasEdit ? <div className="mt-4 space-y-2 rounded-lg border border-violet-100 bg-white p-3 text-xs" data-testid="lg11-canvas-draft"><p className="font-bold">섹션 구조 초안 · revision {view.values.canvas?.revision || 0}</p>{canvasSections.map((section, index) => <div key={section.section_id} className="flex flex-wrap items-center justify-between gap-2 border-t pt-2"><span>{index + 1}. {section.section_id}</span><span className="flex flex-wrap gap-1"><button type="button" disabled={working || index === 0} onClick={() => void resume("apply", { canvasOperation: canvasOperation("reorder", section.section_id, { position: index - 1 }) })} className="rounded border px-2 py-1">위로</button><button type="button" disabled={working || index === canvasSections.length - 1} onClick={() => void resume("apply", { canvasOperation: canvasOperation("reorder", section.section_id, { position: index + 1 }) })} className="rounded border px-2 py-1">아래로</button><button type="button" disabled={working} onClick={() => void resume("apply", { canvasOperation: canvasOperation("duplicate", section.section_id, { position: index + 1 }) })} className="rounded border px-2 py-1">복제</button><button type="button" disabled={working} onClick={() => void resume("apply", { canvasOperation: canvasOperation("set_visibility", section.section_id, { is_visible: section.canvas?.is_visible === false }) })} className="rounded border px-2 py-1">{section.canvas?.is_visible === false ? "표시" : "숨김"}</button><input aria-label={`${section.section_id} 높이`} type="number" min="160" max="2400" value={canvasHeights[section.section_id] ?? String(section.canvas?.height_px || 160)} onChange={(event) => setCanvasHeights((current) => ({ ...current, [section.section_id]: event.target.value }))} className="w-16 rounded border px-1 py-1"/><button type="button" disabled={working} onClick={() => void resume("apply", { canvasOperation: canvasOperation("set_height", section.section_id, { height_px: Number(canvasHeights[section.section_id] ?? section.canvas?.height_px ?? 160) }) })} className="rounded border px-2 py-1">높이 적용</button><button type="button" disabled={working} onClick={() => void resume("apply", { canvasOperation: canvasOperation("remove", section.section_id) })} className="rounded border border-rose-300 px-2 py-1 text-rose-700">삭제</button></span></div>)}<button type="button" disabled={working} onClick={() => void resume("apply", { canvasOperation: canvasOperation("add", undefined, { position: canvasAddPosition === 0 && canvasSections.length ? canvasSections.length : canvasAddPosition }) })} className="rounded border border-violet-300 px-2 py-1 font-bold text-violet-800">섹션 추가</button></div> : null}
    {canvasEdit ? canvasElementControls : null}
    {generationWaiting && costPlan ? <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-950" data-testid="lg5r-cost-plan">
      <p className="font-black">생성 전 비용 확인</p>
      <p className="mt-1">{costPlan.scene_count}개 장면 · {costPlan.provider} / {costPlan.model}</p>
      <ul className="mt-2 space-y-1">
        {costPlan.scenes.map((scene) => <li key={scene.scene_id} className="flex justify-between gap-3"><span>{scene.title} · {scene.output_size}</span><b>{scene.estimated_cost} {costPlan.currency}</b></li>)}
      </ul>
      <p className="mt-2 border-t border-amber-200 pt-2 text-right font-black">총 예상 비용 {costPlan.total_estimated_cost} {costPlan.currency}</p>
    </div> : null}
    {(providerWaiting || imageReview) && jobs.length > 0 ? <div className="mt-4 space-y-2 rounded-lg border border-violet-100 bg-white/70 p-3 text-xs">
      <div className="flex flex-wrap items-center justify-between gap-2"><p className="font-bold text-slate-800">장면별 이미지 작업</p>{imageReview ? <p>{view.values.generation?.approved_count || 0}/{view.values.generation?.required_scene_count || jobs.length}개 필수 장면 승인</p> : null}</div>
      {jobs.map((job) => <article key={job.job_id} className="rounded-md border border-slate-100 p-3" data-testid={`lg5r-scene-${job.scene_id || job.job_id}`}>
        <div className="flex flex-wrap items-start justify-between gap-2"><span><b>{job.role || job.section_id || job.job_id}</b> · 생성 시도 {job.generation_attempt || 1}</span><span>{job.estimated_cost ?? 0} credit</span></div>
        {job.output_asset_id ? <figure className="mt-3 overflow-hidden rounded-lg border border-slate-200 bg-slate-100">
          {/* The authenticated asset endpoint serves both fake-provider previews
              and real provider results, so reviewers always approve a visible image. */}
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={apiUrl(`/api/v1/files/assets/${job.output_asset_id}`)}
            alt={`${job.role || job.section_id || "장면"} 생성 이미지 미리보기`}
            className="aspect-square w-full bg-slate-100 object-contain"
            loading="lazy"
            data-testid={`lg5r-scene-preview-${job.scene_id || job.job_id}`}
          />
          <figcaption className="border-t border-slate-200 bg-white px-3 py-2 text-[11px] text-slate-500">생성 결과 미리보기 · 이미지를 확인한 뒤 승인해 주세요.</figcaption>
        </figure> : imageReview && job.status === "needs_review" ? <p className="mt-3 rounded bg-rose-50 px-3 py-2 text-rose-700">검수할 이미지 파일을 불러오지 못했습니다. 이 장면을 승인하지 말고 상태를 새로고침해 주세요.</p> : null}
        {job.output_asset_id && job.source_asset_ids?.length ? <section className="mt-3 rounded-lg border border-violet-100 bg-violet-50/50 p-3" data-testid={`lg9-scene-comparison-${job.scene_id || job.job_id}`}>
          <p className="text-[11px] font-bold text-violet-900">생성 결과와 기준 사진 비교</p>
          <p className="mt-1 text-[10px] leading-4 text-slate-600">기준 사진은 생성 참고용이며, 최종 사용 여부는 생성 결과와 검사 보고서를 함께 확인해 결정합니다.</p>
          <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-3">
            {job.source_asset_ids.map((assetId, index) => <figure key={assetId} className="overflow-hidden rounded border border-violet-100 bg-white">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={apiUrl(`/api/v1/files/assets/${assetId}`)} alt={`${job.role || job.section_id || "장면"} 기준 사진 ${index + 1}`} className="aspect-square w-full object-contain" loading="lazy" data-testid={`lg9-reference-${job.scene_id || job.job_id}-${assetId}`} />
              <figcaption className="px-2 py-1 text-[10px] text-slate-600">기준 사진 {index + 1}</figcaption>
            </figure>)}
          </div>
        </section> : null}
        {job.validation?.status && job.validation.status !== "pending" ? <section className={`mt-3 rounded-lg border p-3 text-[11px] ${job.validation.status === "blocked" ? "border-rose-200 bg-rose-50 text-rose-900" : job.validation.status === "needs_review" ? "border-amber-200 bg-amber-50 text-amber-950" : "border-emerald-200 bg-emerald-50 text-emerald-950"}`} data-testid={`lg9-validation-${job.scene_id || job.job_id}`}>
          <p className="font-bold">자동 검사 보고서 · {validationStatusLabel[job.validation.status] || job.validation.status}</p>
          {job.validation.checks ? <div className="mt-2 grid gap-1 sm:grid-cols-2">
            {Object.entries(validationCheckLabel).map(([key, label]) => {
              const status = job.validation?.checks?.[key];
              return <p key={key}><b>{label}</b> · {status ? (validationCheckStatusLabel[status] || status) : "미확인"}</p>;
            })}
          </div> : null}
          {job.validation.risk_codes?.length ? <p className="mt-2">감지 항목: {job.validation.risk_codes.join(", ")}</p> : null}
          {job.validation.ocr_text ? <p className="mt-2">감지 문구: {job.validation.ocr_text}</p> : null}
          {job.validation.warnings?.length ? <p className="mt-2">검사 메모: {job.validation.warnings.join(" · ")}</p> : null}
        </section> : null}
        {job.seller_guidance ? <p className="mt-2 text-rose-700">{job.seller_guidance.cause_ko} {job.seller_guidance.action_ko}</p> : null}
        {imageReview ? <div className="mt-3 flex flex-wrap gap-2">
          {job.status === "needs_review" ? <><button type="button" onClick={() => void resume("approve", { jobId: job.job_id })} disabled={working} className="rounded bg-emerald-600 px-2 py-1 font-bold text-white disabled:opacity-50">이 장면 승인</button><button type="button" onClick={() => void resume("reject", { jobId: job.job_id })} disabled={working} className="rounded border border-rose-300 px-2 py-1 font-bold text-rose-700 disabled:opacity-50">거절</button></> : null}
          {["failed", "blocked", "rejected", "cancelled", "dead_letter", "needs_review"].includes(job.status) ? <button type="button" onClick={() => void resume("regenerate", { jobId: job.job_id })} disabled={working} className="rounded border border-amber-300 px-2 py-1 font-bold text-amber-800 disabled:opacity-50">이 장면 재생성</button> : null}
          {job.status !== "approved" ? <><select aria-label={`${job.job_id} 직접 업로드 사진`} value={uploadByJob[job.job_id] || ""} onChange={(event) => setUploadByJob((current) => ({ ...current, [job.job_id]: event.target.value }))} className="rounded border border-slate-200 bg-white px-2 py-1"><option value="">권리 보유 사진 선택</option>{uploadAssets.map((asset) => <option key={asset.id} value={asset.id}>{asset.filename}</option>)}</select><button type="button" onClick={() => void resume("upload", { jobId: job.job_id, assetId: uploadByJob[job.job_id] })} disabled={working || !uploadByJob[job.job_id]} className="rounded border border-violet-300 px-2 py-1 font-bold text-violet-800 disabled:opacity-50">선택 사진 연결</button></> : null}
        </div> : null}
      </article>)}
      {imageReview && (view.values.generation?.failed_job_ids?.length || 0) > 0 ? <button type="button" onClick={() => void resume("regenerate")} disabled={working} className="rounded border border-amber-300 bg-white px-2 py-1 font-bold text-amber-800 disabled:opacity-50">실패 장면만 재생성</button> : null}
    </div> : null}
    {message ? <p role="status" className="mt-3 text-xs font-semibold text-violet-800">{message}</p> : null}
  </section>;
}

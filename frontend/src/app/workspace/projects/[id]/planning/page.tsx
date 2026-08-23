"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import { useParams, useSearchParams } from "next/navigation";
import { apiUrl } from "@/lib/api";
import PlanningDraftEditor, { StoryboardDraft } from "@/components/planning/PlanningDraftEditor";
import ApiReadyGenerationPlanPanel from "@/components/planning/ApiReadyGenerationPlanPanel";
import GraphReviewPanel, { GraphView } from "@/components/planning/GraphReviewPanel";
import CreativeBriefInputPanel from "@/components/planning/CreativeBriefInputPanel";
import ScenePromptReviewPanel from "@/components/planning/ScenePromptReviewPanel";

type SourceCapture = {
  id: string;
  url: string;
  platform: string;
  source_role: string;
  collection_status: "pending" | "collected" | "access_limited" | "failed";
  failure_code?: string | null;
  collected_image_count: number;
  collected_spec_count: number;
};

type ProjectAsset = {
  id: string;
  filename: string;
  source_type: string;
  mime_type?: string;
  asset_role?: string;
  usage_status?: string;
};

const identityRoleOptions = [
  { value: "unknown", label: "역할 선택" },
  { value: "product_main", label: "대표 제품 전체" },
  { value: "product_detail", label: "조작부·측면 상세" },
  { value: "product_component", label: "제품 구성품" },
  { value: "product_in_use", label: "제품 실사용" },
  { value: "usage_scene", label: "사용 장면" },
] as const;

const defaultHeaders = () => ({ "Content-Type": "application/json" });

const apiErrorMessage = async (response: Response, fallback: string) => {
  const payload = await response.json().catch(() => null);
  const detail = payload?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => typeof item?.msg === "string" ? item.msg : null)
      .filter(Boolean);
    if (messages.length) return messages.join(" · ");
  }
  if (detail && typeof detail === "object") {
    if (typeof detail.message === "string") return detail.message;
    if (typeof detail.msg === "string") return detail.msg;
  }
  return fallback;
};

const captureStatusLabel = (capture: SourceCapture) => {
  if (capture.collection_status === "collected") {
    return `수집 완료 · 이미지 ${capture.collected_image_count}장 · 스펙 ${capture.collected_spec_count}개`;
  }
  if (capture.collection_status === "access_limited") {
    const reason: Record<string, string> = {
      http_403: "사이트 접근 제한(403)",
      login_required: "로그인 필요",
      captcha_required: "사람 확인 필요",
      dynamic_page: "동적 페이지 제한",
    };
    return `${reason[capture.failure_code || ""] || "사이트 접근 제한"} · 직접 업로드로 계속 가능`;
  }
  if (capture.collection_status === "failed") return "수집 실패 · 직접 업로드로 계속 가능";
  return "수집 대기 중";
};

export default function ProjectPlanningPage() {
  const params = useParams();
  const searchParams = useSearchParams();
  const projectId = String(params.id);
  const graphRunId = searchParams.get("runId");
  const [draft, setDraft] = useState<StoryboardDraft | null>(null);
  const [loading, setLoading] = useState(true);
  const [statusText, setStatusText] = useState("기획 초안을 불러오는 중입니다...");
  const [error, setError] = useState<string | null>(null);
  const [sourceCaptures, setSourceCaptures] = useState<SourceCapture[]>([]);
  const [assets, setAssets] = useState<ProjectAsset[]>([]);
  const [sourceType, setSourceType] = useState<"sourced" | "uploaded" | "self_shot">("sourced");
  const [uploading, setUploading] = useState(false);
  const [classifyingAssetId, setClassifyingAssetId] = useState<string | null>(null);
  const [assetMessage, setAssetMessage] = useState<string | null>(null);
  const [graphView, setGraphView] = useState<GraphView | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const graphReviewStage = graphView?.values.review?.pending?.review_stage ?? null;
  const isQualityReview = graphReviewStage === "quality_review";

  const loadAssets = useCallback(async () => {
    const response = await fetch(apiUrl(`/api/v1/projects/${projectId}/assets`), {
      headers: defaultHeaders(),
      credentials: "include",
      cache: "no-store",
    });
    if (!response.ok) throw new Error("상품 사진 목록을 불러오지 못했습니다.");
    const nextAssets = await response.json();
    const inputPhotos = Array.isArray(nextAssets)
      ? nextAssets.filter((asset: ProjectAsset) =>
          ["sourced", "uploaded", "self_shot"].includes(asset.source_type)
          && (!asset.mime_type || asset.mime_type.startsWith("image/")),
        )
      : [];
    // The project asset table also holds AI candidates, exported ZIPs, and
    // page-render artifacts. This box is deliberately limited to the
    // seller/supplier images supplied as product input.
    setAssets(inputPhotos);
  }, [projectId]);

  const handleAssetUpload = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files || []);
    event.target.value = "";
    if (!files.length) return;

    setUploading(true);
    setAssetMessage(null);
    try {
      for (const file of files) {
        if (!file.type.startsWith("image/")) {
          throw new Error(`${file.name}은(는) 이미지 파일이 아닙니다.`);
        }
        const formData = new FormData();
        formData.append("project_id", projectId);
        formData.append("source_type", sourceType);
        formData.append("file", file);
        const response = await fetch(apiUrl("/api/v1/files/upload"), {
          method: "POST",
          credentials: "include",
          body: formData,
        });
        if (!response.ok) {
          throw new Error(await apiErrorMessage(response, `${file.name} 업로드에 실패했습니다.`));
        }
      }
      await loadAssets();
      setAssetMessage(`${files.length}장의 사진을 추가했습니다. 아래 “후보 3개 다시 만들기”를 누르면 새 사진을 반영합니다.`);
    } catch (uploadError) {
      setAssetMessage(uploadError instanceof Error ? uploadError.message : "상품 사진 업로드에 실패했습니다.");
    } finally {
      setUploading(false);
    }
  };

  const handleAssetRoleChange = async (asset: ProjectAsset, assetRole: string) => {
    setClassifyingAssetId(asset.id);
    setAssetMessage(null);
    try {
      const response = await fetch(
        apiUrl(`/api/v1/projects/${projectId}/assets/${asset.id}/classification`),
        {
          method: "PATCH",
          headers: defaultHeaders(),
          credentials: "include",
          body: JSON.stringify({ asset_role: assetRole }),
        },
      );
      if (!response.ok) {
        throw new Error(await apiErrorMessage(response, `${asset.filename} 사진 역할을 저장하지 못했습니다.`));
      }
      const updated = await response.json() as ProjectAsset;
      setAssets((current) => current.map((item) => item.id === updated.id ? updated : item));
      setAssetMessage(
        assetRole === "unknown"
          ? `${asset.filename} 사진 역할을 미지정으로 변경했습니다.`
          : `${asset.filename} 사진 역할을 저장했습니다. 제품 전체 사진 1장과 상세·구성품·사용 사진 1장을 지정해 주세요.`,
      );
    } catch (classificationError) {
      const message = classificationError instanceof Error
        ? classificationError.message
        : "알 수 없는 오류가 발생했습니다.";
      setAssetMessage(`사진 역할 저장 실패: ${message}`);
    } finally {
      setClassifyingAssetId(null);
    }
  };

  useEffect(() => {
    let active = true;
    const fetchSourceCaptures = async () => {
      try {
        const response = await fetch(apiUrl(`/api/v1/projects/${projectId}/source-captures`), {
          headers: defaultHeaders(),
          credentials: "include",
          cache: "no-store",
        });
        if (!response.ok) return;
        const captures = await response.json();
        if (active && Array.isArray(captures)) setSourceCaptures(captures);
      } catch {
        // Collection status is supplementary; planning remains available.
      }
    };
    void fetchSourceCaptures();
    return () => { active = false; };
  }, [projectId]);

  useEffect(() => {
    void loadAssets().catch(() => {
      // The planning screen stays usable even when an old project has no assets.
      setAssets([]);
    });
  }, [loadAssets]);

  useEffect(() => {
    let active = true;
    const fetchPlanningDraft = async () => {
      try {
        setLoading(true);
        setError(null);
        const endpoint = apiUrl(`/api/v1/projects/${projectId}/planning-draft`);
        const getRes = await fetch(endpoint, { headers: defaultHeaders(), credentials: "include", cache: "no-store" });
        if (getRes.status === 404) {
          // A new LG-4 run must pause at input/evidence approval before the
          // old storyboard endpoint is allowed to create anything.
          if (graphRunId) {
            if (active) setDraft(null);
            return;
          }
          if (!active) return;
          setStatusText("AI 기획 초안을 새로 준비하는 중입니다...");
          const postRes = await fetch(apiUrl(`/api/v1/projects/${projectId}/storyboard/recommendations`), { method: "POST", headers: defaultHeaders(), credentials: "include" });
          if (!postRes.ok) throw new Error("AI 기획 초안 생성에 실패했습니다.");
          const postData = await postRes.json();
          if (active) setDraft(postData);
        } else if (!getRes.ok) {
          throw new Error("기획 초안 조회에 실패했습니다.");
        } else {
          const getData = await getRes.json();
          if (getData.storyboard_version && Array.isArray(getData.recommendations)) {
            if (active) setDraft(getData);
          } else {
            const postRes = await fetch(apiUrl(`/api/v1/projects/${projectId}/storyboard/recommendations`), { method: "POST", headers: defaultHeaders(), credentials: "include" });
            if (!postRes.ok) throw new Error("스토리보드 후보 생성에 실패했습니다.");
            const postData = await postRes.json();
            if (active) setDraft(postData);
          }
        }
      } catch (err) {
        if (active) setError(err instanceof Error ? err.message : "기획안을 준비하는 중 오류가 발생했습니다.");
      } finally {
        if (active) setLoading(false);
      }
    };
    void fetchPlanningDraft();
    return () => { active = false; };
  }, [projectId, graphRunId]);

  if (loading) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center bg-slate-50 p-6 text-slate-800">
        <div className="flex w-full max-w-md flex-col items-center space-y-6 rounded-3xl border border-slate-100 bg-white p-10 text-center shadow-xl">
          <div className="relative h-16 w-16"><div className="absolute inset-0 animate-spin rounded-full border-4 border-emerald-100 border-t-emerald-600" /></div>
          <div className="space-y-2">
            <h3 className="text-lg font-extrabold text-slate-900">기획 초안 준비 중</h3>
            <p className="text-xs leading-relaxed text-slate-500">{statusText}</p>
          </div>
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-slate-100"><div className="h-full w-2/5 animate-pulse rounded-full bg-emerald-600" /></div>
          <p className="text-[10px] font-medium text-slate-400">판매 구조와 섹션 흐름을 먼저 구성하고 있습니다.</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-50 p-6 text-slate-800">
        <div className="w-full max-w-md space-y-6 rounded-3xl border border-rose-100 bg-white p-8 text-center shadow-xl">
          <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full border border-rose-100 bg-rose-50 text-xl font-extrabold text-rose-600">!</div>
          <div className="space-y-2"><h3 className="font-extrabold text-slate-900">기획안을 불러오지 못했습니다</h3><p className="text-xs text-rose-600">{error}</p></div>
          <button type="button" onClick={() => window.location.reload()} className="w-full rounded-xl bg-slate-900 py-3 text-xs font-bold text-white hover:bg-slate-800">다시 시도하기</button>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-50 p-6 text-slate-800 md:p-10">
      <section className="mx-auto mb-5 max-w-4xl rounded-xl border border-slate-200 bg-white p-4 text-sm">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="font-bold text-slate-900">상품 사진 확인·추가</h2>
            <p className="mt-1 text-xs leading-5 text-slate-600">
              후보를 다시 만들어도 기존 사진은 삭제되지 않습니다. 이 프로젝트에는 현재 {assets.length}장의 입력 사진이 저장되어 있습니다.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <select
              value={sourceType}
              onChange={(event) => setSourceType(event.target.value as "sourced" | "uploaded" | "self_shot")}
              className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs font-semibold text-slate-700"
              aria-label="사진 권리 유형"
            >
              <option value="sourced">공급처 참고 사진</option>
              <option value="uploaded">권리 보유 이미지</option>
              <option value="self_shot">직접 촬영 사진</option>
            </select>
            <input
              ref={fileInputRef}
              type="file"
              accept="image/png,image/jpeg,image/webp"
              multiple
              className="hidden"
              onChange={handleAssetUpload}
            />
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              disabled={uploading}
              className="rounded-lg bg-emerald-600 px-3 py-2 text-xs font-bold text-white disabled:opacity-50"
            >
              {uploading ? "올리는 중..." : "사진 추가"}
            </button>
          </div>
        </div>
        {assets.length > 0 && (
          <div className="mt-3 grid gap-2 sm:grid-cols-2">
            {assets.map((asset) => (
              <div key={asset.id} className="rounded-lg border border-slate-200 bg-slate-50 p-2.5 text-xs text-slate-700">
                <div className="flex items-center justify-between gap-2">
                  <span className="min-w-0 truncate font-semibold" title={asset.filename}>{asset.filename}</span>
                  <span className={asset.usage_status === "seller_owned" ? "text-emerald-700" : "text-amber-700"}>
                    {asset.usage_status === "seller_owned" ? "권리 보유" : "참고 전용"}
                  </span>
                </div>
                <label className="mt-2 block">
                  <span className="sr-only">{asset.filename} 사진 역할</span>
                  <select
                    aria-label={`${asset.filename} 사진 역할`}
                    data-testid={`asset-role-${asset.id}`}
                    value={asset.asset_role || "unknown"}
                    disabled={classifyingAssetId === asset.id}
                    onChange={(event) => void handleAssetRoleChange(asset, event.target.value)}
                    className="w-full rounded-md border border-slate-200 bg-white px-2 py-1.5 text-xs disabled:opacity-50"
                  >
                    {identityRoleOptions.map((option) => (
                      <option key={option.value} value={option.value}>{option.label}</option>
                    ))}
                  </select>
                </label>
              </div>
            ))}
          </div>
        )}
        {assets.some((asset) => asset.usage_status === "seller_owned") && (
          <p className="mt-3 rounded-lg bg-sky-50 px-3 py-2 text-[11px] leading-5 text-sky-800">
            AI 이미지 생성에는 권리 보유 사진 중 `대표 제품 전체` 1장과 `조작부·측면 상세`, `제품 구성품`, `제품 실사용`, `사용 장면` 중 1장 이상이 필요합니다.
          </p>
        )}
        <p className="mt-3 text-[11px] leading-5 text-slate-500">
          AI 후보 이미지와 다운로드 파일은 여기서 제외됩니다. 장면별 AI 후보는 아래 스토리보드 영역에서 확인하세요.
        </p>
        {assetMessage && (
          <p className={`mt-3 rounded-lg px-3 py-2 text-xs ${assetMessage.includes("실패") || assetMessage.includes("아닙니다") ? "bg-rose-50 text-rose-700" : "bg-emerald-50 text-emerald-800"}`}>
            {assetMessage}
          </p>
        )}
      </section>
      {sourceCaptures.length > 0 && (
        <section className="mx-auto mb-5 max-w-4xl rounded-xl border border-slate-200 bg-white px-4 py-4 text-sm">
          <h2 className="font-bold text-slate-900">상품 링크 수집 결과</h2>
          <ul className="mt-3 space-y-2">
            {sourceCaptures.map((capture) => (
              <li key={capture.id} className={`rounded-lg px-3 py-2 ${capture.collection_status === "collected" ? "bg-emerald-50 text-emerald-800" : "bg-amber-50 text-amber-900"}`}>
                <span className="font-semibold">{capture.platform}</span>
                <span className="mx-2 text-slate-400">·</span>
                <span>{capture.source_role === "product" ? "상품 링크" : "참고 링크"}</span>
                <p className="mt-1 text-xs">{captureStatusLabel(capture)}</p>
              </li>
            ))}
          </ul>
          {sourceCaptures.some((capture) => capture.collection_status !== "collected") && (
            <p className="mt-3 text-xs leading-5 text-slate-600">링크 수집이 제한되어도 직접 올린 대표컷·기능컷·사용 장면·구성품 사진과 판매자 입력 정보를 우선 사용합니다.</p>
          )}
        </section>
      )}
      <CreativeBriefInputPanel projectId={projectId} runId={graphRunId} />
      <GraphReviewPanel projectId={projectId} runId={graphRunId} hidePlanningAction={Boolean(draft)} onStateChange={setGraphView} />
      {graphRunId && graphReviewStage === "generation_pending" && (
        <ScenePromptReviewPanel projectId={projectId} />
      )}
      {draft && draft.cards.length > 0 ? (
        <PlanningDraftEditor projectId={projectId} initialDraft={draft} graphRunId={graphRunId} graphReviewStage={graphReviewStage} />
      ) : (
        <div className="mx-auto max-w-4xl space-y-5">{graphRunId ? (graphView?.status !== "failed" && graphView?.values.review?.pending && <div className="rounded-xl border border-violet-200 bg-violet-50 p-5 text-center text-sm font-semibold text-violet-900">{isQualityReview ? "품질 확인이 필요한 항목이 있습니다. 위에서 다음 단계를 선택해 주세요." : "판매자 확인을 기다리고 있습니다. 위 승인 요청을 완료하면 이 화면에 스토리보드가 표시됩니다."}</div>) : <><ApiReadyGenerationPlanPanel projectId={projectId} /><div className="py-6 text-center font-bold text-slate-400">표시할 스토리보드가 없습니다. 상품 브리프·장면 계획을 먼저 확인한 뒤 스토리보드를 생성하세요.</div></>}</div>
      )}
    </div>
  );
}

"use client";

import React, { useEffect, useRef, useState } from "react";
import GenerationProgressShell from "./GenerationProgressShell";
import StructuredIntakeReview from "./StructuredIntakeReview";
import GenerationDuplicateRunDialog, { DuplicateRunDetail } from "./GenerationDuplicateRunDialog";
import { apiUrl, structureIntake, StructuredIntakeDraft } from "@/lib/api";
import { useRouter, useSearchParams } from "next/navigation";
import PlanningModeSelector from "./planning/PlanningModeSelector";

type PendingImage = {
  id: string;
  file: File;
  previewUrl: string;
  sourceType: "self_shot" | "uploaded" | "sourced";
};

const MAX_PRODUCT_IMAGES = 20;

export default function AIDetailPageIntake() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [productName, setProductName] = useState("");
  const [category, setCategory] = useState("Living");
  const [planningMode, setPlanningMode] = useState<"quality" | "quick">("quality");
  const [description, setDescription] = useState("");
  const [featureDetails, setFeatureDetails] = useState("");
  const [components, setComponents] = useState("");
  const [cautions, setCautions] = useState("");
  const [price, setPrice] = useState("");
  const [shipping, setShipping] = useState("");
  const [salesChannel, setSalesChannel] = useState("");
  const [modelOptions, setModelOptions] = useState("");
  const [productUrl, setProductUrl] = useState("");
  const [referenceUrlsText, setReferenceUrlsText] = useState("");
  const [freeformInput, setFreeformInput] = useState("");
  const [structuredDraft, setStructuredDraft] = useState<StructuredIntakeDraft | null>(null);
  const [selectedPreset, setSelectedPreset] = useState("깔끔한");
  const [pendingImages, setPendingImages] = useState<PendingImage[]>([]);
  const pendingImagesRef = useRef<PendingImage[]>([]);
  const [isDragActive, setIsDragActive] = useState(false);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [duplicateRunDetail, setDuplicateRunDetail] = useState<DuplicateRunDetail | null>(null);
  const runId = searchParams.get("runId");

  const presets = ["깔끔한", "감성적인", "프리미엄", "실용 강조", "선물용"];

  const duplicateRunDialog = duplicateRunDetail ? (
    <GenerationDuplicateRunDialog
      detail={duplicateRunDetail}
      onClose={() => setDuplicateRunDetail(null)}
      onForceNew={() => {
        void handleSubmit({ preventDefault() {} } as React.FormEvent, structuredDraft, true);
      }}
    />
  ) : null;

  useEffect(() => {
    pendingImagesRef.current = pendingImages;
  }, [pendingImages]);

  useEffect(() => {
    return () => {
      pendingImagesRef.current.forEach((image) => URL.revokeObjectURL(image.previewUrl));
    };
  }, []);

  const addImages = (files: FileList | File[]) => {
    const incoming = Array.from(files).filter((file) => file.type.startsWith("image/"));
    if (incoming.length === 0) {
      setError("JPG, PNG, WEBP 등 이미지 파일을 선택해 주세요.");
      return;
    }
    setPendingImages((current) => {
      const remaining = MAX_PRODUCT_IMAGES - current.length;
      const accepted = incoming.slice(0, Math.max(0, remaining)).map((file) => ({
        id: `${file.name}-${file.lastModified}-${crypto.randomUUID()}`,
        file,
        previewUrl: URL.createObjectURL(file),
        // An uploaded file is not proof that the seller owns final-page usage
        // rights.  Start conservatively and require an explicit choice for a
        // self-shot or licensed asset.  This is especially important for files
        // saved from supplier marketplaces such as 1688.
        sourceType: "sourced" as const,
      }));
      if (incoming.length > remaining) {
        setError(`상품 사진은 최대 ${MAX_PRODUCT_IMAGES}장까지 올릴 수 있습니다.`);
      }
      return [...current, ...accepted];
    });
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) addImages(e.target.files);
    e.target.value = "";
  };

  const removeImage = (id: string) => {
    setPendingImages((current) => {
      const removed = current.find((image) => image.id === id);
      if (removed) URL.revokeObjectURL(removed.previewUrl);
      return current.filter((image) => image.id !== id);
    });
  };

  const moveImage = (index: number, direction: "left" | "right") => {
    setPendingImages((current) => {
      const targetIndex = direction === "left" ? index - 1 : index + 1;
      if (targetIndex < 0 || targetIndex >= current.length) return current;
      const next = [...current];
      [next[index], next[targetIndex]] = [next[targetIndex], next[index]];
      return next;
    });
  };

  const updateImageSourceType = (id: string, sourceType: PendingImage["sourceType"]) => {
    setPendingImages((current) => current.map((image) => (
      image.id === id ? { ...image, sourceType } : image
    )));
  };

  const sellerBundleText = () =>
    [
      description.trim() && `상품 상세 설명\n${description.trim()}`,
      featureDetails.trim() && `기능·장점\n${featureDetails.trim()}`,
      components.trim() && `구성품·디테일\n${components.trim()}`,
      cautions.trim() && `주의사항\n${cautions.trim()}`,
    ]
      .filter(Boolean)
      .join("\n\n");

  const imageGuidance = () => {
    const count = pendingImages.length;
    if (count === 0) return "대표 상품컷 1장부터 올려 주세요. 이어서 기능·상세컷, 사용 장면, 구성품 사진을 추가하면 좋습니다.";
    if (count === 1) return "기능·상세 이미지를 3장 이상 더 추가해 주세요. 같은 대표 사진을 반복하지 않기 위해 필요합니다.";
    if (count < 4) return `현재 ${count}장입니다. 기능/상세 이미지 ${4 - count}장을 더 추가하면 기준선(대표 1 + 상세 3)을 충족합니다.`;
    if (count < 5) return "기준선은 충족했습니다. 사용 장면 또는 구성품 사진 1장을 더 추가하면 쿠팡형 흐름을 만들기 좋습니다.";
    return `상품 사진 ${count}장 준비 완료. 아래 카드에서 HERO → 기능 → 사용 장면 → 구성품 순서로 확인할 수 있습니다.`;
  };

  const handleStructureIntake = async () => {
    const bundleText = sellerBundleText();
    if (!productName.trim() && !productUrl.trim()) {
      setError("상품명 또는 상품 URL을 입력해 주세요.");
      return;
    }
    if (pendingImages.length === 0) {
      setError("상품을 식별할 수 있는 대표 사진을 1장 이상 올려 주세요.");
      return;
    }
    if (!freeformInput.trim() && !bundleText) {
      setError("판매자가 확인한 핵심 정보 1개 이상(예: 무게, 기능, 구성품)을 입력해 주세요.");
      return;
    }

    const uid = localStorage.getItem("X-Mock-User-Id") || "00000000-0000-0000-0000-000000000001";
    const wid = localStorage.getItem("X-Mock-Workspace-Id") || "00000000-0000-0000-0000-000000000002";

    setLoading(true);
    setError(null);
    try {
      const draft = await structureIntake(
        {
          freeform_input: freeformInput,
          product_name: productName,
          category,
          description: bundleText,
          product_url: productUrl,
          reference_urls: referenceUrlsText.split(/\r?\n/).map((value) => value.trim()).filter(Boolean),
          desired_mood: selectedPreset,
          asset_ids: [],
          sales_channel: salesChannel,
          model_options: modelOptions,
        },
        {
          "X-Mock-User-Id": uid,
          "X-Mock-Workspace-Id": wid,
        }
      );
      setStructuredDraft({
        ...draft,
        category: { value: category, source: "explicit_field", confidence: "confirmed" },
        price: { value: price, source: "explicit_field", confidence: "confirmed" },
        shipping: { value: shipping, source: "explicit_field", confidence: "confirmed" },
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "상품 자료를 정리하지 못했습니다.");
    } finally {
      setLoading(false);
    }
  };

  const handleSubmitConfirmedDraft = async (confirmedDraft: StructuredIntakeDraft) => {
    setStructuredDraft(confirmedDraft);
    await handleSubmit({ preventDefault() {} } as React.FormEvent, confirmedDraft);
  };

  const handleSubmit = async (
    e: React.FormEvent,
    confirmedDraft: StructuredIntakeDraft | null = structuredDraft,
    forceNew: boolean = false
  ) => {
    e.preventDefault();
    // Sprint 1 keeps the seller in control: a normal submit first opens the
    // immutable input-bundle review. The second submit happens only after the
    // seller confirms that review (or intentionally creates a duplicate run).
    if (!confirmedDraft && !forceNew) {
      await handleStructureIntake();
      return;
    }
    const finalProductName = confirmedDraft?.product_name.value || productName.trim() || "";
    const fallbackBundleText = sellerBundleText();
    if (!finalProductName.trim() && !productUrl.trim()) {
      setError("상품명 또는 상품 URL을 입력해 주세요.");
      return;
    }
    if (pendingImages.length === 0) {
      setError("상품을 식별할 수 있는 대표 사진을 1장 이상 올려 주세요.");
      return;
    }
    if (!freeformInput.trim() && !fallbackBundleText) {
      setError("판매자가 확인한 핵심 정보 1개 이상을 입력해 주세요.");
      return;
    }

    setLoading(true);
    setError(null);

    const uid = localStorage.getItem("X-Mock-User-Id") || "00000000-0000-0000-0000-000000000001";
    const wid = localStorage.getItem("X-Mock-Workspace-Id") || "00000000-0000-0000-0000-000000000002";

    try {
      const res = await fetch(apiUrl("/api/agent-runs"), {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Mock-User-Id": uid,
          "X-Mock-Workspace-Id": wid,
        },
        body: JSON.stringify({
          product_name: finalProductName,
          // The original seller text is the source of truth for numeric
          // specifications. Do not let an intake summary drop a unit such as
          // "분" before the fact-ingestion step receives it.
          category: confirmedDraft?.category?.value || category,
          description: confirmedDraft?.description?.value || fallbackBundleText || freeformInput.trim(),
          feature_details: featureDetails,
          components,
          cautions,
          product_url: productUrl,
          freeform_input: freeformInput,
          asset_ids: [],
          reference_urls:
            confirmedDraft?.reference_urls ||
            referenceUrlsText.split(/\r?\n/).map((value) => value.trim()).filter(Boolean),
          selling_points: confirmedDraft?.selling_points.map((point) => point.text) || [],
          price: confirmedDraft?.price?.value || price,
          shipping: confirmedDraft?.shipping?.value || shipping,
          sales_channel: salesChannel,
          model_options: modelOptions,
          desired_mood: confirmedDraft?.desired_mood || [selectedPreset],
          planning_mode: planningMode,
          force_new: forceNew,
        }),
      });

      if (!res.ok) {
        const detail = await res.json().catch(() => null);
        if (res.status === 409 && detail?.detail?.code === "generation_already_running") {
          setDuplicateRunDetail(detail.detail);
          return;
        }
        throw new Error("상세페이지 생성 요청에 실패했습니다.");
      }

      const data = await res.json();
      const uploadedAssetIds: string[] = [];
      for (const image of pendingImages) {
        const formData = new FormData();
        formData.append("project_id", data.project_id);
        formData.append("source_type", image.sourceType);
        formData.append("file", image.file);

        const uploadRes = await fetch(apiUrl("/api/v1/files/upload"), {
          method: "POST",
          headers: {
            "X-Mock-User-Id": uid,
            "X-Mock-Workspace-Id": wid,
          },
          body: formData,
        });
        if (!uploadRes.ok) throw new Error(`상품 사진 업로드에 실패했습니다: ${image.file.name}`);
        const uploaded = await uploadRes.json();
        uploadedAssetIds.push(uploaded.id);
      }
      const collectedAssetIds = Array.isArray(data.product_input?.asset_ids)
        ? data.product_input.asset_ids.filter(
            (assetId: unknown): assetId is string => typeof assetId === "string" && assetId.length > 0,
          )
        : [];
      const orderedAssetIds = [
        ...uploadedAssetIds,
        ...collectedAssetIds.filter((assetId: string) => !uploadedAssetIds.includes(assetId)),
      ].slice(0, MAX_PRODUCT_IMAGES);
      if (orderedAssetIds.length > 0) {
        // Keep the order chosen by the seller and append URL-collected assets.
        // Replacing the list with only uploaded IDs would silently discard
        // useful evidence collected from the supplied product/reference URLs.
        const assetsRes = await fetch(apiUrl(`/api/agent-runs/${data.id}/input-assets`), {
          method: "PATCH",
          headers: {
            "Content-Type": "application/json",
            "X-Mock-User-Id": uid,
            "X-Mock-Workspace-Id": wid,
          },
          body: JSON.stringify({ asset_ids: orderedAssetIds }),
        });
        if (!assetsRes.ok) throw new Error("상품 사진 순서를 저장하지 못했습니다.");
      }
      if (typeof window !== "undefined") {
        sessionStorage.setItem("sellform:lastGenerationRunId", data.id);
        if (data.collection_warnings?.length) {
          sessionStorage.setItem(
            `sellform:urlCollectionWarnings:${data.project_id}`,
            JSON.stringify(data.collection_warnings),
          );
        }
      }
      if (planningMode === "quality") {
        router.push(`/workspace/projects/${data.project_id}/planning`);
      } else {
        router.push(`/workspace?runId=${data.id}`);
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "연결 오류가 발생했습니다.");
    } finally {
      setLoading(false);
    }
  };

  if (runId) {
    return (
      <>
        {duplicateRunDialog}
        <GenerationProgressShell runId={runId} />
      </>
    );
  }

  if (structuredDraft) {
    return (
      <>
        {duplicateRunDialog}
        <div className="flex min-h-screen w-full flex-col items-center justify-center bg-slate-50 p-6 text-slate-800">
          {error && (
            <div className="mb-4 w-full max-w-3xl rounded-lg border border-rose-100 bg-rose-50 px-4 py-3 text-sm text-rose-700">
              {error}
            </div>
          )}
          <StructuredIntakeReview
            draft={structuredDraft}
            inputBundle={{
              salesChannel,
              modelOptions,
              images: pendingImages.map((image, index) => ({
                order: index + 1,
                filename: image.file.name,
                sourceType: image.sourceType,
              })),
            }}
            onBack={() => setStructuredDraft(null)}
            onConfirm={handleSubmitConfirmedDraft}
          />
        </div>
      </>
    );
  }

  return (
    <>
      {duplicateRunDialog}
      <div className="min-h-screen bg-slate-50 text-slate-800 flex flex-col items-center justify-center p-6 w-full">
      {/* Brand Context */}
      <div className="mb-6 flex items-center space-x-2">
        <span className="text-xl font-bold tracking-tight text-emerald-600">Sellform</span>
        <span className="bg-emerald-50 text-emerald-700 text-xs px-2.5 py-1 rounded-full font-semibold border border-emerald-100">
          AI 상세페이지
        </span>
      </div>

      {/* Headline & Subcopy */}
      <div className="text-center max-w-xl mb-10">
        <h1 className="text-3xl font-extrabold tracking-tight text-slate-900 sm:text-4xl mb-4 leading-tight">
          상품 사진이나 URL을 넣으면 <br />
          <span className="text-emerald-600 font-black">AI가 상세페이지를 만들어드려요.</span>
        </h1>
        <p className="text-slate-500 text-base leading-relaxed">
          상품을 어떻게 설명해야 할지 몰라도 괜찮아요. <br />
          AI가 판매 포인트, 문구, 이미지 연출 방향까지 먼저 제안합니다.
        </p>
      </div>

      {/* Creation Card */}
      <form
        onSubmit={handleSubmit}
        className="w-full max-w-2xl bg-white rounded-2xl shadow-xl shadow-slate-100 border border-slate-100 p-8 space-y-6"
      >
        {error && (
          <div className="bg-rose-50 border border-rose-100 text-rose-700 text-sm px-4 py-3 rounded-lg animate-shake">
            {error}
          </div>
        )}

        {/* Upload Component */}
        <div>
          <div className="mb-2 flex items-center justify-between gap-3">
            <label className="block text-sm font-semibold text-slate-700" htmlFor="product-images">상품 사진 묶음</label>
            <span className="text-xs font-semibold text-emerald-700">{pendingImages.length} / {MAX_PRODUCT_IMAGES}장</span>
          </div>
          <div
            onDragEnter={(event) => {
              event.preventDefault();
              setIsDragActive(true);
            }}
            onDragOver={(event) => event.preventDefault()}
            onDragLeave={() => setIsDragActive(false)}
            onDrop={(event) => {
              event.preventDefault();
              setIsDragActive(false);
              addImages(event.dataTransfer.files);
            }}
            className={`rounded-xl border-2 border-dashed p-5 transition-colors ${isDragActive ? "border-emerald-500 bg-emerald-50" : "border-slate-200 bg-slate-50"}`}
          >
            <label htmlFor="product-images" className="flex cursor-pointer flex-col items-center justify-center py-3 text-center">
              <svg className="mb-2 h-8 w-8 text-slate-400" aria-hidden="true" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 20 16">
                <path stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M13 13h3a3 3 0 0 0 0-6h-.025A5.56 5.56 0 0 0 16 6.5 5.5 0 0 0 5.207 5.021C5.137 5.017 5.071 5 5 5a4 4 0 0 0 0 8h2.167" />
              </svg>
              <span className="text-sm font-bold text-slate-700">사진을 끌어 놓거나 클릭해서 여러 장 선택</span>
              <span className="mt-1 text-xs text-slate-500">대표컷, 기능컷, 사용 장면, 구성품, 스펙 이미지를 순서대로 올려 주세요.</span>
            </label>
            <input id="product-images" type="file" className="hidden" accept="image/*" multiple onChange={handleFileChange} />
          </div>
          <p className={`mt-2 rounded-lg px-3 py-2 text-xs leading-5 ${pendingImages.length >= 5 ? "bg-emerald-50 text-emerald-700" : "bg-amber-50 text-amber-800"}`}>
            {imageGuidance()}
          </p>
          {pendingImages.length > 0 && (
            <ol className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-3">
              {pendingImages.map((image, index) => (
                <li key={image.id} className="overflow-hidden rounded-xl border border-slate-200 bg-white">
                  <div className="relative aspect-square bg-slate-100">
                    <img src={image.previewUrl} alt={`${index + 1}번째 상품 사진`} className="h-full w-full object-cover" />
                    <span className="absolute left-2 top-2 rounded-full bg-slate-900/80 px-2 py-1 text-[10px] font-bold text-white">{index === 0 ? "1 · 대표 후보" : `${index + 1}번`}</span>
                  </div>
                  <div className="space-y-2 p-2">
                    <p className="truncate text-xs font-medium text-slate-700" title={image.file.name}>{image.file.name}</p>
                    <label className="block text-[11px] font-semibold text-slate-600">
                      출처·권리
                      <select
                        aria-label={`${index + 1}번째 사진 출처와 권리`}
                        value={image.sourceType}
                        onChange={(event) => updateImageSourceType(image.id, event.target.value as PendingImage["sourceType"])}
                        className="mt-1 w-full rounded border border-slate-200 bg-white px-1.5 py-1 text-[11px] font-normal"
                      >
                        <option value="self_shot">직접 촬영·보유 (최종 사용 가능)</option>
                        <option value="uploaded">사용 허가 자료 (최종 사용 가능)</option>
                        <option value="sourced">공급처 참고용 (최종 출력 제외)</option>
                      </select>
                    </label>
                    <div className="flex gap-1">
                      <button type="button" aria-label={`${index + 1}번째 사진 앞으로`} onClick={() => moveImage(index, "left")} disabled={index === 0} className="rounded border border-slate-200 px-2 py-1 text-xs disabled:opacity-30">←</button>
                      <button type="button" aria-label={`${index + 1}번째 사진 뒤로`} onClick={() => moveImage(index, "right")} disabled={index === pendingImages.length - 1} className="rounded border border-slate-200 px-2 py-1 text-xs disabled:opacity-30">→</button>
                      <button type="button" aria-label={`${index + 1}번째 사진 삭제`} onClick={() => removeImage(image.id)} className="ml-auto rounded border border-rose-100 px-2 py-1 text-xs text-rose-600">삭제</button>
                    </div>
                  </div>
                </li>
              ))}
            </ol>
          )}
        </div>

        <div>
          <label className="block text-sm font-semibold text-slate-700 mb-2" htmlFor="freeform-input">
            상품 자료
          </label>
          <textarea
            id="freeform-input"
            aria-label="상품 자료"
            value={freeformInput}
            onChange={(event) => setFreeformInput(event.target.value)}
            placeholder="상품 설명, URL, 스펙, 가격, 원하는 분위기를 자유롭게 적어주세요."
            rows={6}
            className="w-full resize-none rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm focus:border-transparent focus:outline-none focus:ring-2 focus:ring-emerald-500"
          />
          <button
            type="button"
            onClick={handleStructureIntake}
            disabled={loading}
            className="mt-3 rounded-xl bg-slate-900 px-5 py-3 text-sm font-bold text-white hover:bg-slate-800 disabled:opacity-50"
          >
            {loading ? "자료 확인 중..." : "자료 확인하기"}
          </button>
        </div>

        {/* Core product fields */}
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <div>
            <label className="block text-sm font-semibold text-slate-700 mb-2">상품 URL</label>
            <input
              type="url"
              placeholder="상품 URL"
              value={productUrl}
              onChange={(e) => setProductUrl(e.target.value)}
              className="w-full px-4 py-3 rounded-xl border border-slate-200 focus:outline-none focus:ring-2 focus:ring-emerald-500 focus:border-transparent text-sm bg-slate-50 hover:bg-slate-100/50 transition-colors"
            />
          </div>
          <div>
            <label className="block text-sm font-semibold text-slate-700 mb-2">상품명 *</label>
            <input
              type="text"
              placeholder="상품명"
              value={productName}
              onChange={(e) => setProductName(e.target.value)}
              className="w-full px-4 py-3 rounded-xl border border-slate-200 focus:outline-none focus:ring-2 focus:ring-emerald-500 focus:border-transparent text-sm bg-slate-50 hover:bg-slate-100/50 transition-colors"
            />
          </div>
          <div>
            <label className="block text-sm font-semibold text-slate-700 mb-2" htmlFor="product-category">카테고리</label>
            <select id="product-category" value={category} onChange={(event) => setCategory(event.target.value)} className="w-full rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm">
              <option value="Living">리빙·소형 가전</option>
              <option value="Beauty">뷰티</option>
              <option value="Fashion">패션</option>
              <option value="Food">식품</option>
            </select>
          </div>
          <div>
            <label className="block text-sm font-semibold text-slate-700 mb-2" htmlFor="product-price">가격</label>
            <input id="product-price" type="text" placeholder="예: 39,900원" value={price} onChange={(event) => setPrice(event.target.value)} className="w-full rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm" />
          </div>
          <div>
            <label className="block text-sm font-semibold text-slate-700 mb-2" htmlFor="product-shipping">배송 정보</label>
            <input id="product-shipping" type="text" placeholder="예: 무료배송, 오늘출발" value={shipping} onChange={(event) => setShipping(event.target.value)} className="w-full rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm" />
          </div>
        </div>

        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <label className="block text-sm font-semibold text-slate-700">
            판매 채널
            <input type="text" placeholder="예: 쿠팡, 스마트스토어, 자사몰" value={salesChannel} onChange={(event) => setSalesChannel(event.target.value)} className="mt-2 w-full rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm" />
          </label>
          <label className="block text-sm font-semibold text-slate-700">
            모델·옵션
            <input type="text" placeholder="예: YL-T02 / 그레이, 단품" value={modelOptions} onChange={(event) => setModelOptions(event.target.value)} className="mt-2 w-full rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm" />
          </label>
        </div>

        {productUrl.trim() && (
          <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-xs leading-5 text-amber-800">
            쇼핑몰 정책에 따라 링크의 이미지·상세정보 수집이 차단될 수 있습니다. 차단되더라도 위에 상품 사진과 상세 정보를 올리면 그대로 상세페이지를 만들 수 있습니다.
          </div>
        )}

        <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-xs leading-5 text-slate-600">
          <strong className="text-slate-800">현재 상품 가져오기 확장 기능은 준비 중입니다.</strong> 지금은 상품 URL을 붙여넣거나 사진·스펙을 직접 올려 주세요. 로그인·캡차·403 제한을 우회하지 않습니다.
        </div>

        <div>
          <label className="block text-sm font-semibold text-slate-700 mb-2" htmlFor="reference-urls">
            참고 상세페이지 URL
          </label>
          <textarea
            id="reference-urls"
            aria-label="참고 상세페이지 URL"
            value={referenceUrlsText}
            onChange={(event) => setReferenceUrlsText(event.target.value)}
            placeholder="한 줄에 하나씩 입력"
            rows={2}
            className="w-full resize-none rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm"
          />
        </div>

        {/* Seller evidence fields */}
        <div>
          <label className="block text-sm font-semibold text-slate-700 mb-2">상품 상세 설명</label>
          <textarea
            placeholder="간단한 설명 · 예: 무게 260g, 연속 사용 시간 10분, 배터리 용량 800mAh"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={3}
            className="w-full px-4 py-3 rounded-xl border border-slate-200 focus:outline-none focus:ring-2 focus:ring-emerald-500 focus:border-transparent text-sm bg-slate-50 hover:bg-slate-100/50 transition-colors resize-none"
          />
          <p className="mt-2 text-xs text-slate-500">수치에는 단위를 함께 입력해 주세요. 예: <strong>260g</strong>, <strong>10분</strong>, <strong>800mAh</strong></p>
        </div>

        <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
          <label className="block text-sm font-semibold text-slate-700">
            기능·장점
            <textarea value={featureDetails} onChange={(event) => setFeatureDetails(event.target.value)} placeholder="예: 3단 진동, 저소음 설계" rows={4} className="mt-2 w-full resize-none rounded-xl border border-slate-200 bg-slate-50 px-3 py-3 text-sm" />
          </label>
          <label className="block text-sm font-semibold text-slate-700">
            구성품·디테일
            <textarea value={components} onChange={(event) => setComponents(event.target.value)} placeholder="예: 본체, 충전 케이블, 설명서" rows={4} className="mt-2 w-full resize-none rounded-xl border border-slate-200 bg-slate-50 px-3 py-3 text-sm" />
          </label>
          <label className="block text-sm font-semibold text-slate-700">
            주의사항
            <textarea value={cautions} onChange={(event) => setCautions(event.target.value)} placeholder="예: 사용 전 설명서를 확인해 주세요." rows={4} className="mt-2 w-full resize-none rounded-xl border border-slate-200 bg-slate-50 px-3 py-3 text-sm" />
          </label>
        </div>

        {/* Preset Section */}
        <div>
          <label className="block text-sm font-semibold text-slate-700 mb-3">상세페이지 분위기 선택</label>
          <div className="flex flex-wrap gap-2">
            {presets.map((preset) => (
              <button
                key={preset}
                type="button"
                onClick={() => setSelectedPreset(preset)}
                className={`px-4 py-2 rounded-xl text-xs font-semibold border transition-all cursor-pointer ${
                  selectedPreset === preset
                    ? "bg-emerald-600 text-white border-emerald-600 shadow-md shadow-emerald-100"
                    : "bg-slate-50 text-slate-600 border-slate-200 hover:bg-slate-100 hover:text-slate-800"
                }`}
              >
                {preset}
              </button>
            ))}
          </div>
        </div>

        {/* Planning Mode Selection */}
        <PlanningModeSelector mode={planningMode} onChange={setPlanningMode} />

        {/* CTA Button */}
        <button
          type="submit"
          disabled={loading}
          className="w-full bg-emerald-600 hover:bg-emerald-700 text-white font-bold py-4 px-6 rounded-xl transition-all shadow-lg shadow-emerald-100 hover:shadow-emerald-200 disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center space-x-2 text-sm cursor-pointer"
        >
          {loading ? (
            <span>생성 요청 중...</span>
          ) : (
            <>
              <span>입력 자료 확인 후 생성하기</span>
              <svg
                className="w-4 h-4"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                viewBox="0 0 24 24"
                xmlns="http://www.w3.org/2000/svg"
              >
                <path strokeLinecap="round" strokeLinejoin="round" d="M13.5 4.5L21 12m0 0l-7.5 7.5M21 12H3" />
              </svg>
            </>
          )}
        </button>
      </form>

      {/* Preview Steps */}
      <div className="mt-12 w-full max-w-2xl text-center">
        <p className="text-xs font-semibold uppercase tracking-wider text-slate-400 mb-4">상세페이지 생성 과정</p>
        <div className="flex flex-wrap justify-center gap-4 text-xs font-medium text-slate-400">
          {["상품 분석", "판매 전략", "문구 작성", "이미지 기획", "상세페이지 조립"].map((step, idx) => (
            <div key={step} className="flex items-center space-x-2">
              <span className="bg-slate-200 text-slate-600 w-5 h-5 rounded-full inline-flex items-center justify-center font-bold text-[10px]">
                {idx + 1}
              </span>
              <span>{step}</span>
              {idx < 4 && <span className="text-slate-300">→</span>}
            </div>
          ))}
        </div>
      </div>
      </div>
    </>
  );
}

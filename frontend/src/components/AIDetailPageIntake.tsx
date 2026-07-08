"use client";

import React, { useEffect, useState } from "react";
import GenerationProgressShell from "./GenerationProgressShell";
import StructuredIntakeReview from "./StructuredIntakeReview";
import GenerationDuplicateRunDialog, { DuplicateRunDetail } from "./GenerationDuplicateRunDialog";
import { apiUrl, structureIntake, StructuredIntakeDraft } from "@/lib/api";
import { useRouter, useSearchParams } from "next/navigation";
import PlanningModeSelector from "./planning/PlanningModeSelector";

export default function AIDetailPageIntake() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [productName, setProductName] = useState("");
  const [planningMode, setPlanningMode] = useState<"quality" | "quick">("quality");
  const [description, setDescription] = useState("");
  const [productUrl, setProductUrl] = useState("");
  const [referenceUrlsText, setReferenceUrlsText] = useState("");
  const [freeformInput, setFreeformInput] = useState("");
  const [structuredDraft, setStructuredDraft] = useState<StructuredIntakeDraft | null>(null);
  const [selectedPreset, setSelectedPreset] = useState("깔끔한");
  const [fileName, setFileName] = useState<string | null>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [imagePreviewUrl, setImagePreviewUrl] = useState<string | null>(null);

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
    return () => {
      if (imagePreviewUrl) {
        URL.revokeObjectURL(imagePreviewUrl);
      }
    };
  }, [imagePreviewUrl]);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      const file = e.target.files[0];
      setFileName(file.name);
      setSelectedFile(file);
      setImagePreviewUrl((previousUrl) => {
        if (previousUrl) {
          URL.revokeObjectURL(previousUrl);
        }
        return URL.createObjectURL(file);
      });
    }
  };

  const handleStructureIntake = async () => {
    if (!freeformInput.trim() && !productName.trim() && !productUrl.trim() && !selectedFile) {
      setError("상품 사진, URL, 설명 중 하나는 입력해주세요.");
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
          description,
          product_url: productUrl,
          reference_urls: referenceUrlsText.split(/\r?\n/).map((value) => value.trim()).filter(Boolean),
          desired_mood: selectedPreset,
          asset_ids: [],
        },
        {
          "X-Mock-User-Id": uid,
          "X-Mock-Workspace-Id": wid,
        }
      );
      setStructuredDraft(draft);
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
    const finalProductName = confirmedDraft?.product_name.value || productName.trim() || "";
    if (!finalProductName.trim() && !freeformInput.trim() && !productUrl.trim() && !selectedFile) {
      setError("상품명을 입력해주세요.");
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
          description: confirmedDraft?.description?.value || description || freeformInput,
          product_url: productUrl,
          freeform_input: freeformInput,
          asset_ids: [],
          reference_urls:
            confirmedDraft?.reference_urls ||
            referenceUrlsText.split(/\r?\n/).map((value) => value.trim()).filter(Boolean),
          selling_points: confirmedDraft?.selling_points.map((point) => point.text) || [],
          price: confirmedDraft?.price?.value || "",
          shipping: confirmedDraft?.shipping?.value || "",
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
      if (selectedFile) {
        const formData = new FormData();
        formData.append("project_id", data.project_id);
        formData.append("source_type", "uploaded");
        formData.append("file", selectedFile);

        const uploadRes = await fetch(apiUrl("/api/v1/files/upload"), {
          method: "POST",
          headers: {
            "X-Mock-User-Id": uid,
            "X-Mock-Workspace-Id": wid,
          },
          body: formData,
        });

        if (!uploadRes.ok) {
          throw new Error("상품 사진 업로드에 실패했습니다.");
        }
      }
      if (typeof window !== "undefined") {
        sessionStorage.setItem("sellform:lastGenerationRunId", data.id);
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
          <label className="block text-sm font-semibold text-slate-700 mb-2">상품 사진</label>
          <div className="flex items-center justify-center w-full">
            <label className="flex flex-col items-center justify-center w-full min-h-48 border-2 border-slate-200 border-dashed rounded-xl cursor-pointer bg-slate-50 hover:bg-slate-100 transition-colors overflow-hidden">
              {imagePreviewUrl && (
                <div className="relative h-56 w-full bg-white">
                  <img
                    src={imagePreviewUrl}
                    alt={fileName ? `${fileName} 미리보기` : "업로드 이미지 미리보기"}
                    className="h-full w-full object-contain p-3"
                  />
                  <div className="absolute bottom-3 left-1/2 max-w-[90%] -translate-x-1/2 rounded-full bg-white/90 px-3 py-1 text-xs font-semibold text-emerald-700 shadow-sm">
                    사진 변경하기
                  </div>
                </div>
              )}
              <div className={`flex flex-col items-center justify-center pt-5 pb-6 ${imagePreviewUrl ? "hidden" : ""}`}>
                <svg
                  className="w-8 h-8 mb-2 text-slate-400"
                  aria-hidden="true"
                  xmlns="http://www.w3.org/2000/svg"
                  fill="none"
                  viewBox="0 0 20 16"
                >
                  <path
                    stroke="currentColor"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth="2"
                    d="M13 13h3a3 3 0 0 0 0-6h-.025A5.56 5.56 0 0 0 16 6.5 5.5 5.5 0 0 0 5.207 5.021C5.137 5.017 5.071 5 5 5a4 4 0 0 0 0 8h2.167"
                  />
                </svg>
                <p className="text-xs text-slate-500 font-medium">
                  {fileName ? (
                    <span className="text-emerald-600 font-semibold">{fileName}</span>
                  ) : (
                    "클릭하여 이미지 업로드"
                  )}
                </p>
              </div>
              <input type="file" className="hidden" accept="image/*" onChange={handleFileChange} />
            </label>
          </div>
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

        {/* Inputs row */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
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

        {/* Description Textarea */}
        <div>
          <label className="block text-sm font-semibold text-slate-700 mb-2">간단한 설명</label>
          <textarea
            placeholder="간단한 설명"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={3}
            className="w-full px-4 py-3 rounded-xl border border-slate-200 focus:outline-none focus:ring-2 focus:ring-emerald-500 focus:border-transparent text-sm bg-slate-50 hover:bg-slate-100/50 transition-colors resize-none"
          />
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
              <span>AI 상세페이지 만들기</span>
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

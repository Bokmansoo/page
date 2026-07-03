"use client";

import React, { useState } from "react";
import GenerationProgressShell from "./GenerationProgressShell";

export default function AIDetailPageIntake() {
  const [productName, setProductName] = useState("");
  const [description, setDescription] = useState("");
  const [productUrl, setProductUrl] = useState("");
  const [selectedPreset, setSelectedPreset] = useState("깔끔한");
  const [fileName, setFileName] = useState<string | null>(null);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [runId, setRunId] = useState<string | null>(null);

  const presets = ["깔끔한", "감성적인", "프리미엄", "실용 강조", "선물용"];

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      setFileName(e.target.files[0].name);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!productName.trim()) {
      setError("상품명을 입력해주세요.");
      return;
    }

    setLoading(true);
    setError(null);

    const uid = localStorage.getItem("X-Mock-User-Id") || "00000000-0000-0000-0000-000000000001";
    const wid = localStorage.getItem("X-Mock-Workspace-Id") || "00000000-0000-0000-0000-000000000002";

    try {
      const res = await fetch("http://localhost:8000/api/agent-runs", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Mock-User-Id": uid,
          "X-Mock-Workspace-Id": wid,
        },
        body: JSON.stringify({
          product_name: productName,
          description: description,
          product_url: productUrl,
          asset_ids: [],
          reference_urls: [],
        }),
      });

      if (!res.ok) {
        throw new Error("상세페이지 생성 요청에 실패했습니다.");
      }

      const data = await res.json();
      setRunId(data.id);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "연결 오류가 발생했습니다.");
    } finally {
      setLoading(false);
    }
  };

  if (runId) {
    return <GenerationProgressShell runId={runId} />;
  }

  return (
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
            <label className="flex flex-col items-center justify-center w-full h-32 border-2 border-slate-200 border-dashed rounded-xl cursor-pointer bg-slate-50 hover:bg-slate-100 transition-colors">
              <div className="flex flex-col items-center justify-center pt-5 pb-6">
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
              required
              className="w-full px-4 py-3 rounded-xl border border-slate-200 focus:outline-none focus:ring-2 focus:ring-emerald-500 focus:border-transparent text-sm bg-slate-50 hover:bg-slate-100/50 transition-colors"
            />
          </div>
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
  );
}

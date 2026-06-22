"use client";

import React, { useState } from "react";
import { useRouter } from "next/navigation";

export default function NewProjectPage() {
  const router = useRouter();
  const [step, setStep] = useState(1);
  const [projectName, setProjectName] = useState("");
  const [brandId, setBrandId] = useState("00000000-0000-0000-0000-000000000003"); // DEFAULT_BRAND_ID
  const [inputUrl, setInputUrl] = useState("");
  const [inputText, setInputText] = useState("");
  const [uploadedFiles, setUploadedFiles] = useState<File[]>([]);
  const [isSubmitting, setIsSubmitting] = useState(false);

  // Validation States
  const [urlError, setUrlError] = useState<string | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [validationFailed, setValidationFailed] = useState(false);

  const handleUrlValidate = async () => {
    setUrlError(null);
    setValidationFailed(false);

    if (!inputUrl) {
      setUrlError("공급처 URL 주소를 입력해 주세요.");
      return;
    }

    try {
      setIsSubmitting(true);
      const res = await fetch("http://localhost:8000/api/v1/projects", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Mock-User-Id": localStorage.getItem("X-Mock-User-Id") || "00000000-0000-0000-0000-000000000001",
          "X-Mock-Workspace-Id": localStorage.getItem("X-Mock-Workspace-Id") || "00000000-0000-0000-0000-000000000002"
        },
        body: JSON.stringify({
          name: projectName,
          brand_id: brandId,
          raw_input_url: inputUrl
        })
      });

      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.detail || "URL 검증 실패");
      }

      // If successful, project is created as processing, redirect to dashboard
      router.push("/workspace");
    } catch {
      // Trigger SOURCE_EXTRACTION_UNAVAILABLE fallback UI
      setValidationFailed(true);
      setUrlError(
        `자동 추출 실패 (오류 코드: SOURCE_EXTRACTION_UNAVAILABLE) - 보안 차단(캡차, 로그인 필수) 또는 사설 대역 IP 주소 접근 제한 정책으로 인해 해당 주소에 접근하지 못했습니다. 아래 수동 입력 양식을 채워 프로젝트를 계속 진행하세요.`
      );
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    setFileError(null);
    if (!e.target.files) return;

    const files = Array.from(e.target.files);
    const maxSizeBytes = 10 * 1024 * 1024; // 10MB
    const allowedTypes = ["image/jpeg", "image/jpg", "image/png"];

    const validFiles: File[] = [];
    for (const file of files) {
      if (file.size > maxSizeBytes) {
        setFileError(`파일 '${file.name}' 크기가 10MB를 초과하여 제외되었습니다.`);
        continue;
      }
      if (!allowedTypes.includes(file.type)) {
        setFileError(`파일 '${file.name}'은 허용되지 않는 형식입니다. JPG, JPEG, PNG 형식만 업로드 가능합니다.`);
        continue;
      }
      validFiles.push(file);
    }

    setUploadedFiles((prev) => [...prev, ...validFiles]);
  };

  const removeFile = (index: number) => {
    setUploadedFiles((prev) => prev.filter((_, i) => i !== index));
  };

  const handleCreateManualProject = async () => {
    if (!inputText && uploadedFiles.length === 0) {
      setUrlError("수동 입력을 위해 상세 설명 글을 작성하거나 한 개 이상의 이미지를 첨부해 주세요.");
      return;
    }

    try {
      setIsSubmitting(true);
      const uid = localStorage.getItem("X-Mock-User-Id") || "00000000-0000-0000-0000-000000000001";
      const wid = localStorage.getItem("X-Mock-Workspace-Id") || "00000000-0000-0000-0000-000000000002";

      // 1. Create project
      const projectRes = await fetch("http://localhost:8000/api/v1/projects", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Mock-User-Id": uid,
          "X-Mock-Workspace-Id": wid
        },
        body: JSON.stringify({
          name: projectName,
          brand_id: brandId,
          raw_input_text: inputText,
          raw_input_url: inputUrl || null
        })
      });

      if (!projectRes.ok) {
        const errData = await projectRes.json();
        throw new Error(errData.detail || "프로젝트 저장 실패");
      }

      const project = await projectRes.json();

      // 2. Upload assets if any
      for (const file of uploadedFiles) {
        const formData = new FormData();
        formData.append("project_id", project.id);
        formData.append("source_type", "sourced");
        formData.append("file", file);

        const uploadRes = await fetch("http://localhost:8000/api/v1/files/upload", {
          method: "POST",
          headers: {
            "X-Mock-User-Id": uid,
            "X-Mock-Workspace-Id": wid
          },
          body: formData
        });

        if (!uploadRes.ok) {
          console.error(`파일 업로드 실패: ${file.name}`);
        }
      }

      router.push("/workspace");
    } catch (err: unknown) {
      setUrlError(err instanceof Error ? err.message : "프로젝트 저장 도중 오류 발생");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="max-w-2xl mx-auto space-y-8 py-4">
      {/* Wizard Header */}
      <div>
        <h1 className="text-2xl font-extrabold tracking-tight">새 상품 프로젝트 생성</h1>
        <p className="text-slate-400 text-xs mt-1">
          공급처 소싱 자료를 업로드하고 검증하여 상품 상세페이지 초안 작성 단계를 구성합니다.
        </p>
      </div>

      {/* Progress Bar */}
      <div className="flex items-center space-x-4">
        <div className="flex items-center space-x-2">
          <div className={`w-7 h-7 rounded-full flex items-center justify-center font-bold text-xs ${
            step >= 1 ? "bg-indigo-600 text-white" : "bg-slate-800 text-slate-400"
          }`}>
            1
          </div>
          <span className={`text-xs font-semibold ${step >= 1 ? "text-indigo-400" : "text-slate-500"}`}>
            기본 정보 설정
          </span>
        </div>
        <div className="w-16 h-0.5 bg-slate-800"></div>
        <div className="flex items-center space-x-2">
          <div className={`w-7 h-7 rounded-full flex items-center justify-center font-bold text-xs ${
            step >= 2 ? "bg-indigo-600 text-white" : "bg-slate-800 text-slate-400"
          }`}>
            2
          </div>
          <span className={`text-xs font-semibold ${step >= 2 ? "text-indigo-400" : "text-slate-500"}`}>
            자료 수집 등록
          </span>
        </div>
      </div>

      {/* STEP 1: Basic Info */}
      {step === 1 && (
        <div className="glass-card p-6 bg-slate-900/10 border-slate-800 space-y-5">
          <h2 className="text-base font-bold">프로젝트 기본 정보 기입</h2>
          
          <div className="space-y-1.5">
            <label className="text-xs font-semibold text-slate-400 block">프로젝트(상품) 이름</label>
            <input
              type="text"
              placeholder="예: 프리미엄 오가닉 대나무 테이블 매트"
              value={projectName}
              onChange={(e) => setProjectName(e.target.value)}
              className="w-full form-input px-4 py-2.5 text-sm"
            />
          </div>

          <div className="space-y-1.5">
            <label className="text-xs font-semibold text-slate-400 block">적용 브랜드</label>
            <select
              value={brandId}
              onChange={(e) => setBrandId(e.target.value)}
              className="w-full bg-slate-900/50 border border-slate-800 text-sm rounded-xl px-4 py-2.5 focus:outline-none focus:border-indigo-500 cursor-pointer"
            >
              <option value="00000000-0000-0000-0000-000000000003">Default Brand</option>
            </select>
          </div>

          <div className="flex justify-end pt-3">
            <button
              onClick={() => {
                if (!projectName.trim()) {
                  alert("프로젝트 이름을 입력해 주세요.");
                  return;
                }
                setStep(2);
              }}
              className="btn-primary px-5 py-2.5 rounded-xl text-sm font-semibold"
            >
              다음 단계로
            </button>
          </div>
        </div>
      )}

      {/* STEP 2: Raw data upload & validation */}
      {step === 2 && (
        <div className="space-y-5">
          <div className="glass-card p-6 bg-slate-900/10 border-slate-800 space-y-5">
            <h2 className="text-base font-bold">공급처 주소 분석 등록</h2>
            <p className="text-slate-400 text-xs leading-relaxed">
              타오바오, 1688 등 소싱 상품의 판매 링크 주소를 입력하면 AI가 제품 속성과 이미지 자산을 자동으로 수집합니다.
            </p>

            <div className="space-y-1.5">
              <label className="text-xs font-semibold text-slate-400 block">수집 대상 주소 (URL)</label>
              <div className="flex space-x-2">
                <input
                  type="url"
                  placeholder="https://detail.1688.com/offer/..."
                  value={inputUrl}
                  onChange={(e) => setInputUrl(e.target.value)}
                  disabled={isSubmitting}
                  className="flex-1 form-input px-4 py-2.5 text-sm"
                />
                <button
                  onClick={handleUrlValidate}
                  disabled={isSubmitting}
                  className="btn-primary px-5 py-2.5 rounded-xl text-sm font-semibold flex items-center space-x-1.5"
                >
                  {isSubmitting ? (
                    <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin"></div>
                  ) : (
                    <span>분석 및 수집</span>
                  )}
                </button>
              </div>
            </div>

            {urlError && !validationFailed && (
              <div className="text-red-400 text-xs font-semibold mt-1">{urlError}</div>
            )}
          </div>

          {/* FALLBACK UI: SOURCE_EXTRACTION_UNAVAILABLE Triggered */}
          {validationFailed && (
            <div className="glass-card p-6 bg-rose-950/20 border-rose-500/30 space-y-6">
              <div className="flex items-start space-x-3 text-rose-400 text-xs">
                <svg className="w-5 h-5 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                </svg>
                <div className="space-y-1">
                  <p className="font-extrabold text-sm text-slate-100">자동 추출 제한 감지 (SOURCE_EXTRACTION_UNAVAILABLE)</p>
                  <p className="text-slate-300 leading-relaxed">
                    입력하신 주소는 사설망 차단 필터에 감지되었거나 플랫폼의 자동수집 방지 캡차/로그인 차단으로 인해 긁어올 수 없습니다. 
                    프로젝트가 중단되지 않도록 **수동 자료 입력** 양식으로 무중단 자동 전환되었습니다.
                  </p>
                </div>
              </div>

              <div className="border-t border-slate-900/60 pt-5 space-y-5">
                <div className="space-y-1.5">
                  <label className="text-xs font-semibold text-slate-400 block">상품 상세정보 수동 입력 (텍스트)</label>
                  <textarea
                    rows={6}
                    placeholder="공급처 상세 설명글이나 중국어 스펙 테이블을 복사해서 붙여넣어 주세요. 한글 번역 및 정제는 다음 단계에서 AI가 처리합니다."
                    value={inputText}
                    onChange={(e) => setInputText(e.target.value)}
                    className="w-full form-input px-4 py-3 text-sm resize-y"
                  ></textarea>
                </div>

                <div className="space-y-2">
                  <label className="text-xs font-semibold text-slate-400 block">공급처 이미지 업로드 (최대 10MB/장, JPG, PNG)</label>
                  <div className="border-2 border-dashed border-slate-800 rounded-xl p-6 text-center hover:border-slate-600 transition bg-slate-950/30">
                    <input
                      type="file"
                      multiple
                      accept=".jpg,.jpeg,.png"
                      onChange={handleFileUpload}
                      className="hidden"
                      id="manual-file-input"
                    />
                    <label htmlFor="manual-file-input" className="cursor-pointer flex flex-col items-center space-y-1 text-xs text-slate-400">
                      <svg className="w-8 h-8 text-slate-500 mb-1" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
                      </svg>
                      <span className="font-semibold text-indigo-400">여기를 클릭하여 파일 선택</span>
                      <span>또는 이미지 파일을 드래그하여 업로드</span>
                    </label>
                  </div>
                  {fileError && <p className="text-red-400 text-xs font-semibold mt-1">{fileError}</p>}
                </div>

                {uploadedFiles.length > 0 && (
                  <div className="space-y-2">
                    <label className="text-xs font-semibold text-slate-400 block">첨부된 사진 목록 ({uploadedFiles.length}장)</label>
                    <div className="grid grid-cols-2 gap-3">
                      {uploadedFiles.map((file, idx) => (
                        <div key={idx} className="bg-slate-900 border border-slate-800/80 rounded-lg p-2.5 flex items-center justify-between text-xs">
                          <span className="truncate w-40 font-medium">{file.name}</span>
                          <button 
                            type="button"
                            onClick={() => removeFile(idx)}
                            className="text-red-400 hover:text-red-300 font-bold px-1.5 py-0.5"
                          >
                            제거
                          </button>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>

              <div className="flex justify-between pt-3 border-t border-slate-900/60">
                <button
                  onClick={() => setStep(1)}
                  className="px-4 py-2.5 border border-slate-800 rounded-xl text-slate-400 hover:text-white text-sm"
                >
                  이전 단계
                </button>
                <button
                  onClick={handleCreateManualProject}
                  disabled={isSubmitting}
                  className="btn-primary px-5 py-2.5 rounded-xl text-sm font-semibold flex items-center space-x-1.5"
                >
                  {isSubmitting ? (
                    <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin"></div>
                  ) : (
                    <span>수동 데이터로 초안 만들기</span>
                  )}
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

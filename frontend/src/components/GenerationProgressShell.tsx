"use client";

import React, { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

interface GenerationProgressShellProps {
  runId: string;
}

export default function GenerationProgressShell({ runId }: GenerationProgressShellProps) {
  const router = useRouter();
  const steps = [
    "상품 이해",
    "판매 방향 추천",
    "상세페이지 구조 설계",
    "문구 생성",
    "이미지 연출 기획",
    "이미지 생성",
    "상세페이지 조립",
    "검수",
  ];

  const [currentStepIdx, setCurrentStepIdx] = useState(0);
  const [projectId, setProjectId] = useState<string | null>(null);
  const [isApiCompleted, setIsApiCompleted] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const runMockGeneration = async () => {
      try {
        const uid = localStorage.getItem("X-Mock-User-Id") || "00000000-0000-0000-0000-000000000001";
        const wid = localStorage.getItem("X-Mock-Workspace-Id") || "00000000-0000-0000-0000-000000000002";

        const res = await fetch(`http://localhost:8000/api/agent-runs/${runId}/run-mock`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-Mock-User-Id": uid,
            "X-Mock-Workspace-Id": wid,
          },
        });
        if (!res.ok) {
          throw new Error("Mock generation API failed");
        }
        const data = await res.json();
        setProjectId(data.project_id);
        setIsApiCompleted(true);
      } catch (err: any) {
        setError(err.message || "An error occurred");
      }
    };

    runMockGeneration();
  }, [runId]);

  useEffect(() => {
    const interval = setInterval(() => {
      setCurrentStepIdx((prev) => {
        if (prev < steps.length - 1) {
          return prev + 1;
        }
        clearInterval(interval);
        return prev;
      });
    }, 500);

    return () => clearInterval(interval);
  }, []);

  const handleNavigate = () => {
    if (projectId) {
      router.push(`/workspace/projects/${projectId}/page-editor`);
    }
  };

  const isFinished = currentStepIdx === steps.length - 1 && isApiCompleted;

  return (
    <div className="min-h-screen bg-slate-50 text-slate-800 flex flex-col items-center justify-center p-6 w-full">
      <div className="w-full max-w-xl bg-white rounded-2xl shadow-xl shadow-slate-100 border border-slate-100 p-8 space-y-6">
        <h2 className="text-2xl font-bold text-slate-900 text-center mb-6">
          AI 상세페이지 생성 진행 중...
        </h2>

        {error && (
          <div className="p-4 bg-red-50 text-red-700 rounded-xl text-sm border border-red-100 text-center animate-shake">
            {error}
          </div>
        )}

        <div className="space-y-4">
          {steps.map((step, idx) => {
            let status = "pending"; // pending, active, completed
            if (idx < currentStepIdx) status = "completed";
            else if (idx === currentStepIdx) {
              status = isFinished ? "completed" : "active";
            }

            return (
              <div
                key={step}
                className={`flex items-center space-x-4 p-3 rounded-xl border transition-all ${
                  status === "active"
                    ? "bg-emerald-50 border-emerald-200 shadow-sm"
                    : status === "completed"
                    ? "bg-slate-50/50 border-slate-100 opacity-60"
                    : "bg-white border-transparent opacity-40"
                }`}
              >
                {/* Badge/Dot */}
                <div className="flex-shrink-0">
                  {status === "completed" ? (
                    <span className="w-6 h-6 rounded-full bg-emerald-500 text-white flex items-center justify-center text-xs font-bold">
                      ✓
                    </span>
                  ) : status === "active" ? (
                    <span className="w-6 h-6 rounded-full bg-emerald-600 text-white flex items-center justify-center text-xs font-bold animate-pulse">
                      ●
                    </span>
                  ) : (
                    <span className="w-6 h-6 rounded-full bg-slate-100 text-slate-400 flex items-center justify-center text-xs font-semibold border border-slate-200">
                      {idx + 1}
                    </span>
                  )}
                </div>

                {/* Step Label */}
                <div className="flex-1">
                  <p
                    className={`text-sm font-semibold ${
                      status === "active" ? "text-emerald-900" : "text-slate-700"
                    }`}
                  >
                    {step}
                  </p>
                </div>

                {/* Status Indicator */}
                <div>
                  <span
                    className={`text-xs font-bold ${
                      status === "active"
                        ? "text-emerald-600 font-extrabold"
                        : status === "completed"
                        ? "text-emerald-600"
                        : "text-slate-400"
                    }`}
                  >
                    {status === "active" ? "진행 중" : status === "completed" ? "완료" : "대기"}
                  </span>
                </div>
              </div>
            );
          })}
        </div>

        {/* CTA Button */}
        {isFinished && projectId && (
          <div className="pt-4 flex justify-center animate-fade-in">
            <button
              onClick={handleNavigate}
              className="w-full py-4 px-6 rounded-xl text-white font-bold text-base bg-gradient-to-r from-emerald-600 to-teal-500 hover:from-emerald-700 hover:to-teal-600 shadow-lg shadow-emerald-500/25 transition-all transform hover:-translate-y-0.5 active:translate-y-0 cursor-pointer"
            >
              생성된 상세페이지 보기
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

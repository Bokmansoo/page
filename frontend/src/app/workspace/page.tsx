"use client";

import React, { useState, useEffect } from "react";
import Link from "next/link";

interface ProductProject {
  id: string;
  workspace_id: string;
  brand_id: string;
  name: string;
  status: "draft" | "processing" | "checking" | "ready";
  current_step: string;
  raw_input_url?: string;
  raw_input_text?: string;
  created_at: string;
  updated_at: string;
}

export default function DashboardPage() {
  const [projects, setProjects] = useState<ProductProject[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchProjects();
  }, []);

  const fetchProjects = async () => {
    try {
      setLoading(true);
      const uid = localStorage.getItem("X-Mock-User-Id") || "00000000-0000-0000-0000-000000000001";
      const wid = localStorage.getItem("X-Mock-Workspace-Id") || "00000000-0000-0000-0000-000000000002";

      const res = await fetch("http://localhost:8000/api/v1/projects", {
        headers: {
          "X-Mock-User-Id": uid,
          "X-Mock-Workspace-Id": wid,
        },
      });

      if (!res.ok) {
        throw new Error("서버로부터 프로젝트 목록을 불러오지 못했습니다.");
      }

      const data = await res.json();
      setProjects(data);
      setError(null);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "연결 오류");
    } finally {
      setLoading(false);
    }
  };

  const getStatusBadgeClass = (status: ProductProject["status"]) => {
    switch (status) {
      case "draft":
        return "bg-slate-900 border-slate-700/60 text-slate-400";
      case "processing":
        return "bg-amber-500/10 border-amber-500/20 text-amber-400 pulse-status";
      case "checking":
        return "bg-blue-500/10 border-blue-500/20 text-blue-400";
      case "ready":
        return "bg-emerald-500/10 border-emerald-500/20 text-emerald-400";
      default:
        return "bg-slate-900 border-slate-700 text-slate-400";
    }
  };

  const getStatusText = (status: ProductProject["status"]) => {
    switch (status) {
      case "draft":
        return "초안";
      case "processing":
        return "AI 분석중";
      case "checking":
        return "검수중";
      case "ready":
        return "완료";
      default:
        return status;
    }
  };

  return (
    <div className="space-y-8">
      {/* Header section */}
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-3xl font-extrabold tracking-tight">상품 프로젝트 대시보드</h1>
          <p className="text-slate-400 text-sm mt-1">
            소싱된 원본 정보에서 AI 가이드형 상세페이지 제작까지 완료하는 안전한 초안 작업대입니다.
          </p>
        </div>
        <Link href="/workspace/projects/new" className="btn-primary px-5 py-3 rounded-xl flex items-center space-x-2 text-sm shadow-md">
          <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M12 4v16m8-8H4" />
          </svg>
          <span>새 상품 프로젝트</span>
        </Link>
      </div>

      {/* Grid of stats */}
      <div className="grid grid-cols-4 gap-5">
        <div className="glass-card p-5 bg-slate-900/20 border-slate-800/80">
          <div className="text-xs font-semibold text-slate-400 uppercase tracking-wider">전체 프로젝트</div>
          <div className="text-3xl font-extrabold mt-2">{projects.length}</div>
        </div>
        <div className="glass-card p-5 bg-slate-900/20 border-slate-800/80">
          <div className="text-xs font-semibold text-slate-400 uppercase tracking-wider">AI 분석중</div>
          <div className="text-3xl font-extrabold mt-2 text-amber-400">
            {projects.filter((p) => p.status === "processing").length}
          </div>
        </div>
        <div className="glass-card p-5 bg-slate-900/20 border-slate-800/80">
          <div className="text-xs font-semibold text-slate-400 uppercase tracking-wider">검수 대기</div>
          <div className="text-3xl font-extrabold mt-2 text-blue-400">
            {projects.filter((p) => p.status === "checking").length}
          </div>
        </div>
        <div className="glass-card p-5 bg-slate-900/20 border-slate-800/80">
          <div className="text-xs font-semibold text-slate-400 uppercase tracking-wider">제작 완료</div>
          <div className="text-3xl font-extrabold mt-2 text-emerald-400">
            {projects.filter((p) => p.status === "ready").length}
          </div>
        </div>
      </div>

      {/* Projects List */}
      <div>
        <h2 className="text-lg font-bold mb-4 flex items-center space-x-2">
          <span>최근 진행중인 프로젝트</span>
          <button 
            onClick={fetchProjects}
            className="text-slate-400 hover:text-white p-1 hover:bg-slate-900/50 rounded-lg transition"
            title="새로고침"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 1121.213 6m0 0H16.24" />
            </svg>
          </button>
        </h2>

        {error && (
          <div className="bg-red-500/10 border border-red-500/20 text-red-400 text-sm p-4 rounded-xl flex justify-between items-center">
            <span>{error} (FastAPI 백엔드가 구동 중인지 확인해 주세요)</span>
            <button onClick={fetchProjects} className="underline font-semibold hover:text-red-300">
              다시 시도
            </button>
          </div>
        )}

        {loading ? (
          <div className="py-20 text-center text-slate-400 flex flex-col items-center space-y-3">
            <div className="w-8 h-8 border-4 border-indigo-500 border-t-transparent rounded-full animate-spin"></div>
            <span className="text-sm">프로젝트 목록을 불러오는 중...</span>
          </div>
        ) : projects.length === 0 ? (
          <div className="border border-dashed border-slate-800 rounded-2xl py-16 text-center text-slate-400 bg-slate-950/20 backdrop-blur-sm">
            <svg className="w-12 h-12 mx-auto mb-3 text-slate-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4" />
            </svg>
            <p className="font-semibold text-sm">등록된 프로젝트가 없습니다.</p>
            <p className="text-xs text-slate-500 mt-1 mb-5">상단의 &quot;새 상품 프로젝트&quot; 버튼을 클릭하여 시작하세요.</p>
            <Link href="/workspace/projects/new" className="px-4 py-2 border border-slate-800 rounded-xl hover:text-white hover:border-slate-600 transition text-xs font-semibold">
              프로젝트 생성하기
            </Link>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
            {projects.map((project) => (
              <div 
                key={project.id} 
                onClick={() => alert(`프로젝트 [${project.name}] 편집은 Sprint 2 (자료 입력 및 사실 확인) 단계에서 활성화됩니다.`)}
                className="glass-card p-5 cursor-pointer bg-slate-950/40 hover:bg-slate-900/30 flex flex-col justify-between"
              >
                <div>
                  <div className="flex justify-between items-start mb-3">
                    <span className={`px-2.5 py-0.5 rounded-full border text-xs font-semibold ${getStatusBadgeClass(project.status)}`}>
                      {getStatusText(project.status)}
                    </span>
                    <span className="text-xs text-slate-500 font-medium">
                      {new Date(project.updated_at).toLocaleString("ko-KR", { dateStyle: "short", timeStyle: "short" })}
                    </span>
                  </div>
                  <h3 className="text-base font-bold tracking-tight text-white mb-1 hover:text-indigo-400 transition truncate">
                    {project.name}
                  </h3>
                  <div className="text-xs text-slate-400 line-clamp-2 mt-2 h-8">
                    {project.raw_input_url && (
                      <div className="flex items-center space-x-1 text-slate-500 mb-0.5">
                        <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
                        </svg>
                        <span className="truncate">{project.raw_input_url}</span>
                      </div>
                    )}
                    {project.raw_input_text || "입력된 텍스트 내용이 없습니다."}
                  </div>
                </div>
                
                <div className="mt-4 pt-3 border-t border-slate-900/80 flex justify-between items-center text-xs text-slate-500">
                  <span>단계: <strong className="text-slate-400">{project.current_step}</strong></span>
                  <span className="text-indigo-400 hover:underline">프로젝트 편집 →</span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

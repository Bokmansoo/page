"use client";

import React, { useState, useEffect } from "react";

interface SummaryStats {
  total_projects: number;
  total_ai_jobs: number;
  ai_job_success_rate: number;
  ai_job_failure_rate: number;
  average_ai_duration_seconds: number;
  total_ai_cost: number;
  total_export_jobs: number;
  export_job_success_rate: number;
  export_job_failure_rate: number;
  average_export_duration_seconds: number;
}

interface CategoryData {
  project_count: number;
  total_issues: number;
  average_issues_per_project: number;
  blocker_count: number;
  major_count: number;
  warning_count: number;
}

interface CategoryStats {
  [key: string]: CategoryData;
}

interface ProjectJobInfo {
  count: number;
  total_cost?: number;
  total_duration_ms?: number;
  last_status: string;
}

interface ProjectExportInfo {
  count: number;
  last_status: string;
}

interface ProjectIssueInfo {
  blocker: number;
  major: number;
  warning: number;
}

interface ProjectStats {
  id: string;
  name: string;
  category: string;
  status: "draft" | "processing" | "checking" | "ready";
  current_step: string;
  created_at: string;
  updated_at: string;
  ai_jobs: ProjectJobInfo;
  export_jobs: ProjectExportInfo;
  issues: ProjectIssueInfo;
}

interface StatsResponse {
  summary: SummaryStats;
  category_stats: CategoryStats;
  projects: ProjectStats[];
}

export default function OperationsPage() {
  const [stats, setStats] = useState<StatsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [seeding, setSeeding] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchStats = async () => {
    try {
      setLoading(true);
      const uid = localStorage.getItem("X-Mock-User-Id") || "00000000-0000-0000-0000-000000000001";
      const wid = localStorage.getItem("X-Mock-Workspace-Id") || "00000000-0000-0000-0000-000000000002";

      const res = await fetch("http://localhost:8001/api/v1/operations/stats", {
        headers: {
          "X-Mock-User-Id": uid,
          "X-Mock-Workspace-Id": wid,
        },
      });

      if (!res.ok) {
        throw new Error("운영 지표 데이터를 가져오는 데 실패했습니다.");
      }

      const data = await res.json();
      setStats(data);
      setError(null);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "연결 오류");
    } finally {
      setLoading(false);
    }
  };

  const handleSeed = async () => {
    if (!confirm("12개의 다양한 소싱 상품 테스트 팩과 관련 AI/렌더링 이력을 생성하시겠습니까?\n기존에 생성된 동일 이름의 시드 프로젝트는 리셋됩니다.")) {
      return;
    }
    
    try {
      setSeeding(true);
      const uid = localStorage.getItem("X-Mock-User-Id") || "00000000-0000-0000-0000-000000000001";
      const wid = localStorage.getItem("X-Mock-Workspace-Id") || "00000000-0000-0000-0000-000000000002";

      const res = await fetch("http://localhost:8001/api/v1/operations/seed", {
        method: "POST",
        headers: {
          "X-Mock-User-Id": uid,
          "X-Mock-Workspace-Id": wid,
        },
      });

      if (!res.ok) {
        throw new Error("데이터 시딩에 실패했습니다.");
      }

      alert("현실감 있는 12개의 소싱 상품 시드 데이터 적재가 성공적으로 완료되었습니다!");
      fetchStats();
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : "시딩 중 오류 발생");
    } finally {
      setSeeding(false);
    }
  };

  useEffect(() => {
    fetchStats();
  }, []);

  const getStatusBadge = (status: ProjectStats["status"]) => {
    switch (status) {
      case "draft":
        return <span className="bg-slate-900 border border-slate-700/60 text-slate-400 px-2 py-0.5 rounded text-xs font-semibold">초안</span>;
      case "processing":
        return <span className="bg-amber-500/10 border border-amber-500/20 text-amber-400 px-2 py-0.5 rounded text-xs font-semibold pulse-status">분석중</span>;
      case "checking":
        return <span className="bg-blue-500/10 border border-blue-500/20 text-blue-400 px-2 py-0.5 rounded text-xs font-semibold">검수중</span>;
      case "ready":
        return <span className="bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 px-2 py-0.5 rounded text-xs font-semibold">완료</span>;
      default:
        return <span className="bg-slate-800 text-slate-300 px-2 py-0.5 rounded text-xs font-semibold">{status}</span>;
    }
  };

  return (
    <div className="space-y-8">
      {/* Header */}
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-3xl font-extrabold tracking-tight">셀폼 운영 안정성 리포트</h1>
          <p className="text-slate-400 text-sm mt-1">
            소싱 작업 처리량, AI 비용 예측, 성공률 및 카테고리별 검수 규정 준수 현황을 모니터링합니다.
          </p>
        </div>
        <div className="flex items-center space-x-3">
          <button
            onClick={fetchStats}
            className="px-4 py-2 bg-slate-900 border border-slate-800 hover:border-slate-700 hover:text-white rounded-xl text-xs font-semibold transition"
            disabled={loading}
          >
            새로고침
          </button>
          <button
            onClick={handleSeed}
            disabled={seeding}
            className="btn-primary px-4 py-2 rounded-xl text-xs font-semibold flex items-center space-x-1 shadow-md"
          >
            {seeding ? (
              <>
                <div className="w-3 h-3 border-2 border-white border-t-transparent rounded-full animate-spin mr-1"></div>
                <span>시딩 중...</span>
              </>
            ) : (
              <span>Mock 실상품 시딩</span>
            )}
          </button>
        </div>
      </div>

      {error && (
        <div className="bg-red-500/10 border border-red-500/20 text-red-400 text-sm p-4 rounded-xl flex justify-between items-center">
          <span>{error} (FastAPI 백엔드가 켜져있는지 확인해주세요.)</span>
          <button onClick={fetchStats} className="underline font-semibold hover:text-red-300">
            다시 시도
          </button>
        </div>
      )}

      {loading && !stats ? (
        <div className="py-20 text-center text-slate-400 flex flex-col items-center space-y-3">
          <div className="w-8 h-8 border-4 border-indigo-500 border-t-transparent rounded-full animate-spin"></div>
          <span className="text-sm">통계 보고서를 분석하는 중...</span>
        </div>
      ) : stats ? (
        <>
          {/* Summary Stats Grid */}
          <div className="grid grid-cols-1 md:grid-cols-3 lg:grid-cols-5 gap-5">
            <div className="glass-card p-5 bg-slate-900/20 border-slate-800/80">
              <div className="text-xs font-semibold text-slate-400 uppercase tracking-wider">전체 프로젝트</div>
              <div className="text-3xl font-extrabold mt-2 text-white">{stats.summary.total_projects}개</div>
            </div>
            
            <div className="glass-card p-5 bg-slate-900/20 border-slate-800/80">
              <div className="text-xs font-semibold text-slate-400 uppercase tracking-wider">AI 성공률 (소요시간)</div>
              <div className="text-3xl font-extrabold mt-2 text-indigo-400">
                {stats.summary.ai_job_success_rate}%
              </div>
              <div className="text-[10px] text-slate-500 mt-1">
                평균 {stats.summary.average_ai_duration_seconds}초 소요
              </div>
            </div>

            <div className="glass-card p-5 bg-slate-900/20 border-slate-800/80">
              <div className="text-xs font-semibold text-slate-400 uppercase tracking-wider">누적 AI 비용</div>
              <div className="text-3xl font-extrabold mt-2 text-emerald-400">
                ${stats.summary.total_ai_cost.toFixed(4)}
              </div>
              <div className="text-[10px] text-slate-500 mt-1">
                {stats.summary.total_ai_jobs}회 호출 완료
              </div>
            </div>

            <div className="glass-card p-5 bg-slate-900/20 border-slate-800/80">
              <div className="text-xs font-semibold text-slate-400 uppercase tracking-wider">출력 성공률 (소요시간)</div>
              <div className="text-3xl font-extrabold mt-2 text-pink-400">
                {stats.summary.export_job_success_rate}%
              </div>
              <div className="text-[10px] text-slate-500 mt-1">
                평균 {stats.summary.average_export_duration_seconds}초 소요
              </div>
            </div>

            <div className="glass-card p-5 bg-slate-900/20 border-slate-800/80">
              <div className="text-xs font-semibold text-slate-400 uppercase tracking-wider">출력 작업 횟수</div>
              <div className="text-3xl font-extrabold mt-2 text-white">
                {stats.summary.total_export_jobs}건
              </div>
              <div className="text-[10px] text-slate-500 mt-1">
                실패 개수: {stats.summary.total_export_jobs - Math.round(stats.summary.total_export_jobs * stats.summary.export_job_success_rate / 100)}건
              </div>
            </div>
          </div>

          {/* Category Compliance Ratios */}
          <div>
            <h2 className="text-lg font-bold mb-4">카테고리별 검수 규칙 위배 비율</h2>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-5">
              {Object.entries(stats.category_stats).map(([catName, data]) => {
                const totalIssues = data.blocker_count + data.major_count + data.warning_count;
                const hasIssues = totalIssues > 0;
                
                return (
                  <div key={catName} className="glass-card p-5 bg-slate-950/40 border-slate-900 flex flex-col justify-between">
                    <div>
                      <div className="flex justify-between items-center mb-3">
                        <span className="font-extrabold text-white text-base">{catName}</span>
                        <span className="text-xs text-slate-500">{data.project_count}개 상품</span>
                      </div>
                      <div className="space-y-2 mt-4 text-xs">
                        <div className="flex justify-between">
                          <span className="text-slate-400">평균 발생 이슈 수</span>
                          <span className={`font-bold ${hasIssues ? 'text-amber-400' : 'text-slate-400'}`}>
                            {data.average_issues_per_project}개
                          </span>
                        </div>
                        <div className="flex justify-between items-center">
                          <span className="text-slate-400">차단(Blocker)</span>
                          <span className={`font-semibold ${data.blocker_count > 0 ? 'text-rose-500 font-bold' : 'text-slate-600'}`}>
                            {data.blocker_count}개
                          </span>
                        </div>
                        <div className="flex justify-between items-center">
                          <span className="text-slate-400">중요(Major)</span>
                          <span className={`font-semibold ${data.major_count > 0 ? 'text-amber-500 font-bold' : 'text-slate-600'}`}>
                            {data.major_count}개
                          </span>
                        </div>
                        <div className="flex justify-between items-center">
                          <span className="text-slate-400">경고(Warning)</span>
                          <span className={`font-semibold ${data.warning_count > 0 ? 'text-sky-400 font-bold' : 'text-slate-600'}`}>
                            {data.warning_count}개
                          </span>
                        </div>
                      </div>
                    </div>

                    <div className="mt-5">
                      <div className="w-full bg-slate-900 h-2 rounded-full overflow-hidden flex">
                        {data.project_count > 0 ? (
                          <>
                            <div 
                              style={{ width: `${(data.blocker_count / (totalIssues || 1)) * 100}%` }} 
                              className="bg-rose-500 h-full"
                            ></div>
                            <div 
                              style={{ width: `${(data.major_count / (totalIssues || 1)) * 100}%` }} 
                              className="bg-amber-500 h-full"
                            ></div>
                            <div 
                              style={{ width: `${(data.warning_count / (totalIssues || 1)) * 100}%` }} 
                              className="bg-sky-400 h-full"
                            ></div>
                          </>
                        ) : (
                          <div className="w-full bg-slate-800 h-full"></div>
                        )}
                      </div>
                      <div className="text-[10px] text-slate-500 text-center mt-1.5 font-semibold">
                        {hasIssues ? `총 ${totalIssues}건 검출됨` : "검출된 유해 규칙 없음"}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Project operations tracking table */}
          <div>
            <h2 className="text-lg font-bold mb-4">프로젝트별 상세 작업 이력 및 검수 현황</h2>
            <div className="glass-card overflow-hidden bg-slate-950/20 border-slate-900/60">
              <div className="overflow-x-auto">
                <table className="w-full text-left border-collapse text-sm">
                  <thead>
                    <tr className="border-b border-slate-900 bg-slate-900/40 text-slate-400 font-semibold text-xs uppercase tracking-wider">
                      <th className="p-4">상품 프로젝트명</th>
                      <th className="p-4">카테고리</th>
                      <th className="p-4">상태</th>
                      <th className="p-4">AI 작업 (최종/비용)</th>
                      <th className="p-4">출력 작업 (최종)</th>
                      <th className="p-4">발견된 검수 규정 위반</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-900 text-slate-300">
                    {stats.projects.map((p) => {
                      const totalIssues = p.issues.blocker + p.issues.major + p.issues.warning;
                      return (
                        <tr key={p.id} className="hover:bg-slate-900/20 transition-all">
                          <td className="p-4 font-bold text-white">{p.name}</td>
                          <td className="p-4 text-xs font-semibold text-slate-400">{p.category || "미지정"}</td>
                          <td className="p-4">{getStatusBadge(p.status)}</td>
                          <td className="p-4 text-xs">
                            {p.ai_jobs.count > 0 ? (
                              <div className="space-y-0.5">
                                <div className="flex items-center space-x-1">
                                  <span className={`w-1.5 h-1.5 rounded-full ${p.ai_jobs.last_status === 'success' ? 'bg-emerald-500' : 'bg-rose-500'}`}></span>
                                  <span className="font-semibold">{p.ai_jobs.last_status === 'success' ? '정상 완료' : '실패'}</span>
                                </div>
                                <div className="text-slate-500 text-[10px]">
                                  비용: ${p.ai_jobs.total_cost?.toFixed(4)} | 시간: {((p.ai_jobs.total_duration_ms || 0) / 1000).toFixed(1)}초
                                </div>
                              </div>
                            ) : (
                              <span className="text-slate-600">-</span>
                            )}
                          </td>
                          <td className="p-4 text-xs">
                            {p.export_jobs.count > 0 ? (
                              <div className="flex items-center space-x-1">
                                <span className={`w-1.5 h-1.5 rounded-full ${p.export_jobs.last_status === 'completed' ? 'bg-emerald-500' : 'bg-rose-500'}`}></span>
                                <span className="font-semibold">{p.export_jobs.last_status === 'completed' ? '완료' : '실패'}</span>
                              </div>
                            ) : (
                              <span className="text-slate-600">-</span>
                            )}
                          </td>
                          <td className="p-4 text-xs">
                            {totalIssues > 0 ? (
                              <div className="flex flex-wrap gap-1.5">
                                {p.issues.blocker > 0 && (
                                  <span className="bg-rose-500/10 border border-rose-500/20 text-rose-400 px-1.5 py-0.5 rounded text-[10px] font-bold">
                                    차단 {p.issues.blocker}
                                  </span>
                                )}
                                {p.issues.major > 0 && (
                                  <span className="bg-amber-500/10 border border-amber-500/20 text-amber-400 px-1.5 py-0.5 rounded text-[10px] font-bold">
                                    중요 {p.issues.major}
                                  </span>
                                )}
                                {p.issues.warning > 0 && (
                                  <span className="bg-sky-500/10 border border-sky-500/20 text-sky-400 px-1.5 py-0.5 rounded text-[10px] font-bold">
                                    경고 {p.issues.warning}
                                  </span>
                                )}
                              </div>
                            ) : (
                              <span className="text-emerald-500 font-semibold text-xs">위반 사항 없음</span>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </>
      ) : (
        <div className="border border-dashed border-slate-800 rounded-2xl py-16 text-center text-slate-400 bg-slate-950/20">
          <p className="font-semibold text-sm">데이터를 로드하지 못했습니다.</p>
        </div>
      )}
    </div>
  );
}

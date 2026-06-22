"use client";

import React, { useState, useEffect } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";

export default function WorkspaceLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const pathname = usePathname();
  const [activeBrand, setActiveBrand] = useState("Default Brand");
  const [mockUserId, setMockUserId] = useState("");
  const [mockWorkspaceId, setMockWorkspaceId] = useState("");
  const [showSettingsModal, setShowSettingsModal] = useState(false);

  useEffect(() => {
    // Load local auth storage defaults
    const uid = localStorage.getItem("X-Mock-User-Id") || "00000000-0000-0000-0000-000000000001";
    const wid = localStorage.getItem("X-Mock-Workspace-Id") || "00000000-0000-0000-0000-000000000002";
    setMockUserId(uid);
    setMockWorkspaceId(wid);
    localStorage.setItem("X-Mock-User-Id", uid);
    localStorage.setItem("X-Mock-Workspace-Id", wid);
  }, []);

  const saveMockCredentials = () => {
    localStorage.setItem("X-Mock-User-Id", mockUserId);
    localStorage.setItem("X-Mock-Workspace-Id", mockWorkspaceId);
    setShowSettingsModal(false);
    window.location.reload(); // Reload to apply headers globally
  };

  return (
    <div className="flex min-h-screen text-slate-100">
      {/* Sidebar */}
      <aside className="w-64 border-r border-slate-800/80 bg-slate-950/70 backdrop-blur-xl p-6 flex flex-col justify-between fixed h-screen">
        <div>
          {/* Logo */}
          <div className="flex items-center space-x-3 mb-8">
            <div className="w-9 h-9 rounded-xl bg-gradient-to-tr from-indigo-500 to-emerald-400 flex items-center justify-center font-bold text-white shadow-lg shadow-indigo-500/20">
              S
            </div>
            <span className="text-xl font-bold tracking-tight bg-gradient-to-r from-white via-slate-200 to-indigo-300 bg-clip-text text-transparent">
              Sellform
            </span>
          </div>

          {/* Brand Dropdown (Mock) */}
          <div className="mb-8">
            <label className="text-xs font-semibold text-slate-400 tracking-wider uppercase block mb-2">
              활성 브랜드
            </label>
            <div className="relative">
              <select
                value={activeBrand}
                onChange={(e) => setActiveBrand(e.target.value)}
                className="w-full bg-slate-900/60 border border-slate-800/80 text-sm rounded-lg px-3 py-2.5 focus:outline-none focus:border-indigo-500/80 cursor-pointer appearance-none"
              >
                <option value="Default Brand">Default Brand</option>
                <option value="Premium Label">Premium Label</option>
                <option value="Eco Friendly">Eco Friendly</option>
              </select>
              <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center px-3 text-slate-400">
                <svg className="fill-current h-4 w-4" viewBox="0 0 20 20">
                  <path d="M9.293 12.95l.707.707L15.657 8l-1.414-1.414L10 10.828 5.757 6.586 4.343 8z" />
                </svg>
              </div>
            </div>
          </div>

          {/* Navigation Menu */}
          <nav className="space-y-1.5">
            <Link
              href="/workspace"
              className={`flex items-center space-x-3 px-4 py-3 rounded-xl transition-all duration-200 text-sm font-medium ${
                pathname === "/workspace"
                  ? "bg-indigo-500/10 border border-indigo-500/20 text-indigo-400"
                  : "text-slate-400 hover:text-white hover:bg-slate-900/40 border border-transparent"
              }`}
            >
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6a2 2 0 012-2h2a2 2 0 012 2v4a2 2 0 01-2 2H6a2 2 0 01-2-2V6zM14 6a2 2 0 012-2h2a2 2 0 012 2v4a2 2 0 01-2 2h-2a2 2 0 01-2-2V6zM4 16a2 2 0 012-2h2a2 2 0 012 2v4a2 2 0 01-2 2H6a2 2 0 01-2-2v-4zM14 16a2 2 0 012-2h2a2 2 0 012 2v4a2 2 0 01-2 2h-2a2 2 0 01-2-2v-4z" />
              </svg>
              <span>상품 프로젝트</span>
            </Link>
            
            <button
              onClick={() => alert("브랜드 설정 기능은 후속 스프린트에서 구현됩니다.")}
              className="w-full flex items-center space-x-3 px-4 py-3 rounded-xl text-slate-400 hover:text-white hover:bg-slate-900/40 border border-transparent transition-all duration-200 text-sm text-left"
            >
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 6V4m0 2a2 2 0 100 4m0-4a2 2 0 110 4m-6 8a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4m6 6v10m6-2a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4" />
              </svg>
              <span>브랜드 설정</span>
            </button>
            
            <button
              onClick={() => alert("출력 이력 및 관리 기능은 후속 스프린트에서 구현됩니다.")}
              className="w-full flex items-center space-x-3 px-4 py-3 rounded-xl text-slate-400 hover:text-white hover:bg-slate-900/40 border border-transparent transition-all duration-200 text-sm text-left"
            >
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 4H6a2 2 0 00-2 2v12a2 2 0 002 2h12a2 2 0 002-2V6a2 2 0 00-2-2h-2m-4-1v8m0 0l3-3m-3 3L9 8m-5 5h2.586a1 1 0 01.707.293l2.414 2.414a1 1 0 00.707.293h3.172a1 1 0 00.707-.293l2.414-2.414a1 1 0 01.707-.293H20" />
              </svg>
              <span>출력 이력</span>
            </button>
          </nav>
        </div>

        {/* Mock auth setting at the bottom */}
        <div className="border-t border-slate-900 pt-4">
          <div className="bg-slate-900/40 border border-slate-800/40 rounded-xl p-3 text-xs text-slate-400 space-y-1">
            <div className="flex justify-between items-center mb-1">
              <span className="font-semibold text-slate-300">Mock 테넌트 설정</span>
              <button 
                onClick={() => setShowSettingsModal(true)}
                className="text-indigo-400 hover:text-indigo-300 underline font-medium"
              >
                변경
              </button>
            </div>
            <div className="truncate">User: {mockUserId.slice(0, 8)}...</div>
            <div className="truncate">Workspace: {mockWorkspaceId.slice(0, 8)}...</div>
          </div>
        </div>
      </aside>

      {/* Main Content Area */}
      <main className="flex-1 pl-64 min-h-screen">
        <div className="max-w-6xl mx-auto p-8">{children}</div>
      </main>

      {/* Mock Auth Settings Modal */}
      {showSettingsModal && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4">
          <div className="glass-card w-full max-w-md p-6 bg-slate-950/90 border border-slate-800">
            <h3 className="text-lg font-bold mb-4">개발용 Mock 테넌트 설정 변경</h3>
            <p className="text-slate-400 text-xs mb-4">
              FastAPI 백엔드의 `X-Mock-User-Id` 및 `X-Mock-Workspace-Id` 헤더에 실릴 UUID값을 테스트 상황에 맞게 커스텀 설정할 수 있습니다.
            </p>
            <div className="space-y-4 mb-6">
              <div>
                <label className="text-xs font-semibold text-slate-400 block mb-1.5">Mock User ID</label>
                <input 
                  type="text"
                  value={mockUserId}
                  onChange={(e) => setMockUserId(e.target.value)}
                  className="w-full form-input px-3.5 py-2 text-sm"
                />
              </div>
              <div>
                <label className="text-xs font-semibold text-slate-400 block mb-1.5">Mock Workspace ID</label>
                <input 
                  type="text"
                  value={mockWorkspaceId}
                  onChange={(e) => setMockWorkspaceId(e.target.value)}
                  className="w-full form-input px-3.5 py-2 text-sm"
                />
              </div>
            </div>
            <div className="flex justify-end space-x-3 text-sm">
              <button 
                onClick={() => setShowSettingsModal(false)}
                className="px-4 py-2 border border-slate-800 rounded-lg text-slate-400 hover:text-white"
              >
                취소
              </button>
              <button 
                onClick={saveMockCredentials}
                className="px-4 py-2 btn-primary rounded-lg text-white"
              >
                저장 후 리로드
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

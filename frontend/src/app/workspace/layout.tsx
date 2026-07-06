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
  const [brands, setBrands] = useState<{ id: string; name: string }[]>([
    { id: "00000000-0000-0000-0000-000000000003", name: "Default Brand" }
  ]);
  const [activeBrandId, setActiveBrandId] = useState("00000000-0000-0000-0000-000000000003");
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

    // Fetch actual brands from API
    const loadBrands = async () => {
      try {
        const res = await fetch("http://localhost:8001/api/v1/brands", {
          headers: {
            "X-Mock-User-Id": uid,
            "X-Mock-Workspace-Id": wid,
          },
        });
        if (res.ok) {
          const data = await res.json();
          if (data && data.length > 0) {
            setBrands(data);
            const savedBrandId = localStorage.getItem("activeBrandId");
            const stillExists = data.some((b: { id: string }) => b.id === savedBrandId);
            const initialBrandId = stillExists ? (savedBrandId as string) : data[0].id;
            setActiveBrandId(initialBrandId);
            localStorage.setItem("activeBrandId", initialBrandId);
          }
        }
      } catch (e) {
        console.warn("Failed to fetch brands from API, falling back to mock defaults.", e);
      }
    };
    loadBrands();
  }, []);

  const handleBrandChange = (brandId: string) => {
    setActiveBrandId(brandId);
    localStorage.setItem("activeBrandId", brandId);
    // Raise event or dispatch to sync if needed, or simply reload / keep state in localStorage
  };

  const saveMockCredentials = () => {
    localStorage.setItem("X-Mock-User-Id", mockUserId);
    localStorage.setItem("X-Mock-Workspace-Id", mockWorkspaceId);
    setShowSettingsModal(false);
    window.location.reload(); // Reload to apply headers globally
  };

  const isProjectFlow = pathname.startsWith("/workspace/projects/");
  const isIntakePage = pathname === "/workspace";

  const renderSettingsModal = () => (
    <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-2xl w-full max-w-md p-6 border border-slate-200 shadow-xl">
        <h3 className="text-lg font-bold mb-3 text-slate-900">개발용 Mock 테넌트 설정 변경</h3>
        <p className="text-slate-500 text-xs mb-4 leading-relaxed">
          FastAPI 백엔드의 `X-Mock-User-Id` 및 `X-Mock-Workspace-Id` 헤더에 실릴 UUID값을 테스트 상황에 맞게 커스텀 설정할 수 있습니다.
        </p>
        <div className="space-y-4 mb-6">
          <div>
            <label className="text-xs font-semibold text-slate-600 block mb-1.5">Mock User ID</label>
            <input 
              type="text"
              value={mockUserId}
              onChange={(e) => setMockUserId(e.target.value)}
              className="w-full px-3.5 py-2 border border-slate-200 rounded-lg text-sm focus:outline-none focus:border-emerald-500 text-slate-800 bg-white"
            />
          </div>
          <div>
            <label className="text-xs font-semibold text-slate-600 block mb-1.5">Mock Workspace ID</label>
            <input 
              type="text"
              value={mockWorkspaceId}
              onChange={(e) => setMockWorkspaceId(e.target.value)}
              className="w-full px-3.5 py-2 border border-slate-200 rounded-lg text-sm focus:outline-none focus:border-emerald-500 text-slate-800 bg-white"
            />
          </div>
        </div>
        <div className="flex justify-end space-x-3 text-sm font-semibold">
          <button 
            onClick={() => setShowSettingsModal(false)}
            className="px-4 py-2 border border-slate-200 rounded-lg text-slate-500 hover:text-slate-800 hover:bg-slate-50 font-medium cursor-pointer"
          >
            취소
          </button>
          <button 
            onClick={saveMockCredentials}
            className="px-4 py-2 bg-emerald-600 hover:bg-emerald-700 rounded-lg text-white font-medium cursor-pointer"
          >
            저장 후 리로드
          </button>
        </div>
      </div>
    </div>
  );

  return (
    <div className="min-h-screen bg-slate-50 text-slate-800 flex flex-col w-full">
      <header className="w-full bg-white border-b border-slate-200/80 px-6 py-4 flex items-center justify-between sticky top-0 z-30">
        <div className="flex items-center space-x-8">
          <Link href="/workspace" className="flex items-center space-x-2.5 group">
            <div className="w-8 h-8 rounded-lg bg-emerald-500 flex items-center justify-center font-bold text-white shadow-sm shadow-emerald-500/20">
              S
            </div>
            <span className="text-lg font-bold tracking-tight text-slate-900">Sellform</span>
          </Link>

          <nav className="flex items-center space-x-6 text-sm font-medium text-slate-500">
            <Link href="/workspace" className="text-emerald-700 font-semibold hover:text-emerald-800">
              AI 상세페이지 생성
            </Link>
            <Link
              href="/workspace/projects"
              className="hover:text-slate-800 transition-colors"
            >
              작업 목록
            </Link>
            <Link
              href="/workspace/exports"
              className="hover:text-slate-800 transition-colors"
            >
              출력 이력
            </Link>
          </nav>
        </div>

        <div className="bg-slate-100 border border-slate-200/60 rounded-lg px-3 py-1.5 text-xs text-slate-600 flex items-center space-x-2.5">
          <div className="flex flex-col">
            <span className="font-semibold text-slate-700">개발용 워크스페이스</span>
            <span className="text-[10px] text-slate-500 truncate max-w-[120px]">
              U: {mockUserId.slice(0, 8)}... / W: {mockWorkspaceId.slice(0, 8)}...
            </span>
          </div>
          <button
            onClick={() => setShowSettingsModal(true)}
            className="text-emerald-600 hover:text-emerald-700 underline font-medium cursor-pointer"
          >
            변경
          </button>
        </div>
      </header>

      <main className="flex-1 w-full bg-slate-50">
        <div className={isProjectFlow ? "w-full" : "max-w-6xl mx-auto p-8 w-full"}>{children}</div>
      </main>

      {showSettingsModal && renderSettingsModal()}
    </div>
  );

  if (isIntakePage) {
    return (
      <div className="min-h-screen bg-slate-50 text-slate-800 flex flex-col w-full">
        {/* Light Header */}
        <header className="w-full bg-white border-b border-slate-200/80 px-6 py-4 flex items-center justify-between sticky top-0 z-30">
          <div className="flex items-center space-x-8">
            {/* Logo */}
            <Link href="/" className="flex items-center space-x-2.5 group">
              <div className="w-8 h-8 rounded-lg bg-gradient-to-tr from-emerald-500 to-teal-400 flex items-center justify-center font-bold text-white shadow-sm shadow-emerald-500/20">
                S
              </div>
              <span className="text-lg font-bold tracking-tight text-slate-900">
                Sellform
              </span>
            </Link>

            {/* Low-emphasis nav links */}
            <nav className="flex items-center space-x-6 text-sm font-medium text-slate-500">
              <span className="text-emerald-600 font-semibold">AI 상세페이지 생성</span>
              <Link
                href="/workspace/projects"
                className="hover:text-slate-800 transition-colors"
              >
                작업 목록
              </Link>
              <Link
                href="/workspace/exports"
                className="hover:text-slate-800 transition-colors"
              >
                출력 이력
              </Link>
            </nav>
          </div>

          <div className="flex items-center space-x-4">
            {/* Mock auth settings widget */}
            <div className="bg-slate-100 border border-slate-200/60 rounded-lg px-3 py-1.5 text-xs text-slate-600 flex items-center space-x-2.5">
              <div className="flex flex-col">
                <span className="font-semibold text-slate-700">Mock 테넌트</span>
                <span className="text-[10px] text-slate-500 truncate max-w-[120px]">
                  U: {mockUserId.slice(0, 8)}... / W: {mockWorkspaceId.slice(0, 8)}...
                </span>
              </div>
              <button
                onClick={() => setShowSettingsModal(true)}
                className="text-emerald-600 hover:text-emerald-700 underline font-medium cursor-pointer"
              >
                변경
              </button>
            </div>
          </div>
        </header>

        {/* Content Area */}
        <main className="flex-1 w-full bg-slate-50">
          <div className="max-w-6xl mx-auto p-8 w-full">{children}</div>
        </main>

        {/* Mock Settings Modal */}
        {showSettingsModal && renderSettingsModal()}
      </div>
    );
  }

  return (
    <div className="flex min-h-screen text-slate-100 bg-slate-950">
      {/* Sidebar */}
      <aside className="w-64 border-r border-slate-800/80 bg-slate-950/70 backdrop-blur-xl p-6 flex flex-col justify-between fixed h-screen">
        <div>
          {/* Logo */}
          <Link href="/" className="flex items-center space-x-3 mb-8 group">
            <div className="w-9 h-9 rounded-xl bg-gradient-to-tr from-indigo-500 to-emerald-400 flex items-center justify-center font-bold text-white shadow-lg shadow-indigo-500/20">
               S
            </div>
            <span className="text-xl font-bold tracking-tight bg-gradient-to-r from-white via-slate-200 to-indigo-300 bg-clip-text text-transparent">
              Sellform
            </span>
          </Link>

          {/* Brand Dropdown (Dynamic) */}
          <div className="mb-8">
            <label className="text-xs font-semibold text-slate-400 tracking-wider uppercase block mb-2">
              활성 브랜드
            </label>
            <div className="relative">
              <select
                value={activeBrandId}
                onChange={(e) => handleBrandChange(e.target.value)}
                className="w-full bg-slate-900/60 border border-slate-800/80 text-sm rounded-lg px-3 py-2.5 focus:outline-none focus:border-indigo-500/80 cursor-pointer appearance-none"
              >
                {brands.map((b) => (
                  <option key={b.id} value={b.id}>
                    {b.name}
                  </option>
                ))}
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
            
            <Link
              href="/workspace/operations"
              className={`flex items-center space-x-3 px-4 py-3 rounded-xl transition-all duration-200 text-sm font-medium ${
                pathname === "/workspace/operations"
                  ? "bg-indigo-500/10 border border-indigo-500/20 text-indigo-400"
                  : "text-slate-400 hover:text-white hover:bg-slate-900/40 border border-transparent"
              }`}
            >
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 002 2h2a2 2 0 002-2z" />
              </svg>
              <span>운영 리포트</span>
            </Link>
            
            <Link
              href="/workspace/settings"
              className={`flex items-center space-x-3 px-4 py-3 rounded-xl transition-all duration-200 text-sm font-medium ${
                pathname === "/workspace/settings"
                  ? "bg-indigo-500/10 border border-indigo-500/20 text-indigo-400"
                  : "text-slate-400 hover:text-white hover:bg-slate-900/40 border border-transparent"
              }`}
            >
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 6V4m0 2a2 2 0 100 4m0-4a2 2 0 110 4m-6 8a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4m6 6v10m6-2a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4" />
              </svg>
              <span>워크스페이스 설정</span>
            </Link>
            
            <Link
              href="/workspace/exports"
              className="w-full flex items-center space-x-3 px-4 py-3 rounded-xl text-slate-400 hover:text-white hover:bg-slate-900/40 border border-transparent transition-all duration-200 text-sm text-left"
            >
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 4H6a2 2 0 00-2 2v12a2 2 0 002 2h12a2 2 0 002-2V6a2 2 0 00-2-2h-2m-4-1v8m0 0l3-3m-3 3L9 8m-5 5h2.586a1 1 0 01.707.293l2.414 2.414a1 1 0 00.707.293h3.172a1 1 0 00.707-.293l2.414-2.414a1 1 0 01.707-.293H20" />
              </svg>
              <span>출력 이력</span>
            </Link>
            
            <Link
              href="/workspace/projects"
              className={`flex items-center space-x-3 px-4 py-3 rounded-xl transition-all duration-200 text-sm font-medium ${
                pathname === "/workspace/projects"
                  ? "bg-indigo-500/10 border border-indigo-500/20 text-indigo-400"
                  : "text-slate-400 hover:text-white hover:bg-slate-900/40 border border-transparent"
              }`}
            >
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 7a2 2 0 012-2h12a2 2 0 012 2v2H4V7zm0 4h16v6a2 2 0 01-2 2H6a2 2 0 01-2-2v-6zm4 3h4" />
              </svg>
              <span>작업 목록</span>
            </Link>
          </nav>
        </div>

        {/* Mock auth setting at the bottom */}
        <div className="border-t border-slate-900 pt-4">
          <div className="bg-slate-900/40 border border-slate-800/40 rounded-xl p-3 text-xs text-slate-400 space-y-1">
            <div className="flex justify-between items-center mb-1">
              <span className="font-semibold text-slate-300">Mock 테넌트 설정</span>
              <button 
                onClick={() => setShowSettingsModal(true)}
                className="text-indigo-400 hover:text-indigo-300 underline font-medium cursor-pointer"
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

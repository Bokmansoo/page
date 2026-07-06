"use client";

import React, { useState, useEffect } from "react";
import { formatKstDateTime } from "@/lib/datetime";

interface UsageStats {
  total_ai_cost: number;
  ai_budget_limit: number;
  recent_jobs_count_1h: number;
  jobs_limit_1h: number;
  is_blocked: boolean;
}

interface WorkspaceMember {
  user_id: string;
  email: string;
  name: string;
  role: string;
  joined_at: string;
}

interface WorkspaceInvitation {
  id: string;
  workspace_id: string;
  email: string;
  role: string;
  status: string;
  created_at: string;
  expires_at: string;
}

interface Brand {
  id: string;
  workspace_id: string;
  name: string;
  logo_url: string | null;
  brand_colors: { primary: string; secondary: string } | null;
  font_tone: string;
  default_disclaimer: string | null;
}

export default function SettingsPage() {
  const [usage, setUsage] = useState<UsageStats | null>(null);
  const [members, setMembers] = useState<WorkspaceMember[]>([]);
  const [invites, setInvites] = useState<WorkspaceInvitation[]>([]);
  const [brands, setBrands] = useState<Brand[]>([]);

  // Invite form state
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState("member");

  // Brand CRUD form state
  const [editingBrand, setEditingBrand] = useState<Brand | null>(null);
  const [newBrandName, setNewBrandName] = useState("");
  const [newBrandPrimaryColor, setNewBrandPrimaryColor] = useState("#4F46E5");
  const [newBrandSecondaryColor, setNewBrandSecondaryColor] = useState("#10B981");
  const [newBrandDisclaimer, setNewBrandDisclaimer] = useState("");

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const uid = typeof window !== "undefined" ? localStorage.getItem("X-Mock-User-Id") || "00000000-0000-0000-0000-000000000001" : "00000000-0000-0000-0000-000000000001";
  const wid = typeof window !== "undefined" ? localStorage.getItem("X-Mock-Workspace-Id") || "00000000-0000-0000-0000-000000000002" : "00000000-0000-0000-0000-000000000002";

  const headers = {
    "X-Mock-User-Id": uid,
    "X-Mock-Workspace-Id": wid,
    "Content-Type": "application/json",
  };

  const fetchData = async () => {
    try {
      setLoading(true);
      
      // 1. Fetch usage stats
      const usageRes = await fetch("http://localhost:8001/api/v1/workspaces/usage", { headers });
      if (usageRes.ok) {
        setUsage(await usageRes.json());
      }

      // 2. Fetch members
      const membersRes = await fetch("http://localhost:8001/api/v1/workspaces/members", { headers });
      if (membersRes.ok) {
        setMembers(await membersRes.json());
      }

      // 3. Fetch pending invitations
      const invitesRes = await fetch("http://localhost:8001/api/v1/workspaces/invitations", { headers });
      if (invitesRes.ok) {
        setInvites(await invitesRes.json());
      }

      // 4. Fetch brands
      const brandsRes = await fetch("http://localhost:8001/api/v1/brands", { headers });
      if (brandsRes.ok) {
        const brandsData = await brandsRes.json();
        setBrands(brandsData);
        if (brandsData.length > 0 && !editingBrand) {
          setEditingBrand(brandsData[0]);
        }
      }

      setError(null);
    } catch (err) {
      console.error("Failed to fetch settings data:", err);
      setError("데이터를 불러오는데 실패했습니다.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Send team member invite
  const handleInvite = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!inviteEmail) return;

    try {
      const res = await fetch("http://localhost:8001/api/v1/workspaces/invitations", {
        method: "POST",
        headers,
        body: JSON.stringify({ email: inviteEmail, role: inviteRole }),
      });

      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.detail || "초대에 실패했습니다.");
      }

      alert(`${inviteEmail}님에게 초대 발송 완료!`);
      setInviteEmail("");
      fetchData();
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : "오류가 발생했습니다.");
    }
  };

  // Create brand
  const handleCreateBrand = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newBrandName) return;

    try {
      const res = await fetch("http://localhost:8001/api/v1/brands", {
        method: "POST",
        headers,
        body: JSON.stringify({
          name: newBrandName,
          brand_colors: { primary: newBrandPrimaryColor, secondary: newBrandSecondaryColor },
          font_tone: "modern",
          default_disclaimer: newBrandDisclaimer || null,
        }),
      });

      if (!res.ok) throw new Error("브랜드 생성에 실패했습니다.");

      alert("새로운 브랜드가 등록되었습니다!");
      setNewBrandName("");
      setNewBrandDisclaimer("");
      fetchData();
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : "오류가 발생했습니다.");
    }
  };

  // Update brand details
  const handleUpdateBrand = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!editingBrand) return;

    try {
      const res = await fetch(`http://localhost:8001/api/v1/brands/${editingBrand.id}`, {
        method: "PATCH",
        headers,
        body: JSON.stringify({
          name: editingBrand.name,
          brand_colors: editingBrand.brand_colors,
          font_tone: editingBrand.font_tone,
          default_disclaimer: editingBrand.default_disclaimer,
        }),
      });

      if (!res.ok) throw new Error("브랜드 수정에 실패했습니다.");

      alert("브랜드 설정이 성공적으로 저장되었습니다!");
      fetchData();
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : "오류가 발생했습니다.");
    }
  };

  // Delete brand
  const handleDeleteBrand = async (brandId: string) => {
    if (!confirm("정말 이 브랜드를 삭제하시겠습니까?")) return;

    try {
      const res = await fetch(`http://localhost:8001/api/v1/brands/${brandId}`, {
        method: "DELETE",
        headers,
      });

      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.detail || "브랜드 삭제에 실패했습니다.");
      }

      alert("브랜드가 삭제되었습니다.");
      if (editingBrand?.id === brandId) {
        setEditingBrand(null);
      }
      fetchData();
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : "오류가 발생했습니다.");
    }
  };

  // Accept/Decline simulated invites
  const handleAcceptInvite = async (inviteId: string) => {
    try {
      const res = await fetch(`http://localhost:8001/api/v1/workspaces/invitations/${inviteId}/accept`, {
        method: "POST",
        headers,
      });
      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.detail || "초대 수락 실패");
      }
      alert("초대를 수락하여 멤버로 합류했습니다!");
      fetchData();
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : "오류 발생");
    }
  };

  const handleDeclineInvite = async (inviteId: string) => {
    try {
      const res = await fetch(`http://localhost:8001/api/v1/workspaces/invitations/${inviteId}/decline`, {
        method: "POST",
        headers,
      });
      if (!res.ok) throw new Error("초대 거절 실패");
      alert("초대를 거절했습니다.");
      fetchData();
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : "오류 발생");
    }
  };

  if (loading && !usage) {
    return (
      <div className="py-20 text-center text-slate-400 flex flex-col items-center space-y-3">
        <div className="w-8 h-8 border-4 border-indigo-500 border-t-transparent rounded-full animate-spin"></div>
        <span className="text-sm font-semibold">설정 데이터를 가져오는 중...</span>
      </div>
    );
  }

  return (
    <div className="space-y-8">
      {/* Header */}
      <div>
        <h1 className="text-3xl font-extrabold tracking-tight">워크스페이스 설정</h1>
        <p className="text-slate-400 text-sm mt-1">
          다중 브랜드 자산 프로필, 팀원 초대 권한 제어 및 SaaS 사용량 제한 가드레일을 관리합니다.
        </p>
      </div>

      {error && (
        <div className="bg-red-500/10 border border-red-500/20 text-red-400 text-sm p-4 rounded-xl">
          {error}
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        
        {/* Left Column: Limits & Team management */}
        <div className="lg:col-span-2 space-y-8">
          
          {/* Usage Guardrails Card */}
          {usage && (
            <div className="glass-card p-6 bg-slate-900/10 border-slate-800/80">
              <h2 className="text-lg font-bold mb-4 flex items-center justify-between">
                <span>SaaS 사용량 및 가드레일</span>
                {usage.is_blocked ? (
                  <span className="bg-red-500/10 border border-red-500/20 text-red-400 text-xs px-2.5 py-0.5 rounded-full font-bold animate-pulse">
                    사용량 한도 제한 작동 중
                  </span>
                ) : (
                  <span className="bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 text-xs px-2.5 py-0.5 rounded-full font-bold">
                    사용 가능
                  </span>
                )}
              </h2>

              <div className="space-y-6">
                {/* AI Cost Gage */}
                <div>
                  <div className="flex justify-between text-sm mb-1.5 font-medium">
                    <span className="text-slate-400">누적 예상 AI 비용</span>
                    <span className="text-white font-semibold">
                      ${usage.total_ai_cost.toFixed(4)} / ${usage.ai_budget_limit.toFixed(2)}
                    </span>
                  </div>
                  <div className="w-full bg-slate-950 h-3 rounded-full overflow-hidden border border-slate-850">
                    <div
                      style={{ width: `${Math.min((usage.total_ai_cost / usage.ai_budget_limit) * 100, 100)}%` }}
                      className={`h-full transition-all duration-500 ${
                        usage.total_ai_cost >= 4.5 ? "bg-rose-500" : (usage.total_ai_cost >= 3.5 ? "bg-amber-500" : "bg-indigo-500")
                      }`}
                    ></div>
                  </div>
                  <p className="text-[10px] text-slate-500 mt-1.5 font-medium">
                    * 베타 체험 기본 비용 예산은 $5.00이며, 초과 시 AI 기능 실행이 제한됩니다.
                  </p>
                </div>

                {/* Rate limits */}
                <div className="grid grid-cols-2 gap-4 pt-2 border-t border-slate-900">
                  <div>
                    <span className="text-slate-400 text-xs font-semibold uppercase tracking-wider block">최근 1시간 작업 횟수</span>
                    <span className="text-2xl font-black text-white mt-1 block">
                      {usage.recent_jobs_count_1h}회 <span className="text-xs text-slate-500 font-medium">/ 1시간당 {usage.jobs_limit_1h}회 제한</span>
                    </span>
                  </div>
                  <div>
                    <span className="text-slate-400 text-xs font-semibold uppercase tracking-wider block">가용 스로틀링 상태</span>
                    <span className={`text-sm font-bold mt-2.5 block ${usage.recent_jobs_count_1h >= 10 ? 'text-red-400' : 'text-emerald-400'}`}>
                      {usage.recent_jobs_count_1h >= 10 ? '속도제한 초과 차단됨' : '원활한 호출 가능'}
                    </span>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* Members list & Invite management */}
          <div className="glass-card p-6 bg-slate-900/10 border-slate-800/80 space-y-6">
            <div>
              <h2 className="text-lg font-bold">팀원 및 멤버십 (RBAC)</h2>
              <p className="text-slate-400 text-xs mt-0.5">이 워크스페이스에 초대된 팀원과 접근 역할을 관리합니다.</p>
            </div>

            {/* Member list table */}
            <div className="border border-slate-900 rounded-xl overflow-hidden">
              <table className="w-full text-left text-xs border-collapse">
                <thead>
                  <tr className="bg-slate-900/40 text-slate-400 font-bold border-b border-slate-900">
                    <th className="p-3">이름/이메일</th>
                    <th className="p-3">역할</th>
                    <th className="p-3">합류 일자</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-900">
                  {members.map((m) => (
                    <tr key={m.user_id} className="text-slate-300">
                      <td className="p-3">
                        <div className="font-bold text-white text-sm">{m.name}</div>
                        <div className="text-slate-500 text-[10px]">{m.email}</div>
                      </td>
                      <td className="p-3">
                        <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                          m.role === 'owner' ? 'bg-indigo-500/10 text-indigo-400 border border-indigo-500/20' : 
                          (m.role === 'admin' ? 'bg-purple-500/10 text-purple-400 border border-purple-500/20' : 
                          (m.role === 'member' ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' : 'bg-slate-800 text-slate-400'))
                        }`}>
                          {m.role.toUpperCase()}
                        </span>
                      </td>
                      <td className="p-3 text-slate-500">
                        {formatKstDateTime(m.joined_at)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Invite Form */}
            <form onSubmit={handleInvite} className="bg-slate-950/40 border border-slate-900 p-4 rounded-xl space-y-4">
              <h3 className="text-sm font-bold text-white flex items-center space-x-1.5">
                <svg className="w-4 h-4 text-indigo-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M18 9v3m0 0v3m0-3h3m-3 0h-3m-2-5a4 4 0 11-8 0 4 4 0 018 0zM3 20a6 6 0 0112 0v1H3v-1z" />
                </svg>
                <span>신규 팀원 초대하기</span>
              </h3>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                <input
                  type="email"
                  placeholder="초대할 이메일 입력"
                  value={inviteEmail}
                  onChange={(e) => setInviteEmail(e.target.value)}
                  className="w-full form-input px-3 py-2 text-xs md:col-span-2"
                  required
                />
                <select
                  value={inviteRole}
                  onChange={(e) => setInviteRole(e.target.value)}
                  className="w-full bg-slate-900 border border-slate-800/80 rounded-xl px-3 py-2 text-xs text-slate-300 focus:outline-none"
                >
                  <option value="member">MEMBER (생성/편집)</option>
                  <option value="admin">ADMIN (전체 관리)</option>
                  <option value="viewer">VIEWER (조회 전용)</option>
                </select>
              </div>
              <div className="flex justify-end">
                <button type="submit" className="btn-primary px-4 py-2 rounded-lg text-xs font-semibold">
                  초대장 발송
                </button>
              </div>
            </form>

            {/* Pending Invitations list */}
            {invites.length > 0 && (
              <div>
                <h3 className="text-sm font-bold mb-2">보낸 대기중인 초대장</h3>
                <div className="space-y-2">
                  {invites.map((inv) => (
                    <div key={inv.id} className="flex justify-between items-center bg-slate-950/20 border border-slate-900 p-3 rounded-lg text-xs">
                      <div>
                        <span className="font-bold text-white">{inv.email}</span>
                        <span className="text-slate-500 ml-2">역할: {inv.role}</span>
                      </div>
                      {/* Simulated accept decline for easy testing in mock mode */}
                      <div className="flex items-center space-x-2">
                        <button
                          onClick={() => handleAcceptInvite(inv.id)}
                          className="px-2.5 py-1 bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 hover:bg-emerald-500/20 rounded font-semibold text-[10px]"
                          title="테스트용으로 초대 수락 대행"
                        >
                          수락 시뮬레이션
                        </button>
                        <button
                          onClick={() => handleDeclineInvite(inv.id)}
                          className="px-2.5 py-1 bg-rose-500/10 border border-rose-500/20 text-rose-400 hover:bg-rose-500/20 rounded font-semibold text-[10px]"
                        >
                          거절
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Right Column: Brands management */}
        <div className="space-y-8">
          
          {/* Brand list */}
          <div className="glass-card p-6 bg-slate-900/10 border-slate-800/80 space-y-6">
            <div>
              <h2 className="text-lg font-bold">등록된 브랜드 목록</h2>
              <p className="text-slate-400 text-xs mt-0.5">다중 브랜드를 선택 및 편집할 수 있습니다.</p>
            </div>

            <div className="space-y-2.5">
              {brands.map((b) => (
                <div 
                  key={b.id} 
                  onClick={() => setEditingBrand(b)}
                  className={`p-3.5 rounded-xl border cursor-pointer transition flex justify-between items-center ${
                    editingBrand?.id === b.id 
                      ? 'bg-indigo-500/10 border-indigo-500/40 text-white' 
                      : 'bg-slate-950/40 border-slate-900 text-slate-400 hover:border-slate-800'
                  }`}
                >
                  <div className="flex items-center space-x-3">
                    <span 
                      style={{ backgroundColor: b.brand_colors?.primary || "#4F46E5" }}
                      className="w-4 h-4 rounded-full border border-white/20 block"
                    ></span>
                    <span className="font-bold text-sm text-white">{b.name}</span>
                  </div>
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      handleDeleteBrand(b.id);
                    }}
                    className="text-slate-500 hover:text-rose-400 p-1 rounded transition"
                    title="브랜드 삭제"
                  >
                    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                    </svg>
                  </button>
                </div>
              ))}
            </div>

            {/* Create Brand trigger */}
            <form onSubmit={handleCreateBrand} className="bg-slate-950/50 border border-slate-900 p-4 rounded-xl space-y-3">
              <h3 className="text-xs font-bold text-white">신규 브랜드 등록</h3>
              <input
                type="text"
                placeholder="브랜드명 입력"
                value={newBrandName}
                onChange={(e) => setNewBrandName(e.target.value)}
                className="w-full form-input px-3 py-1.5 text-xs"
                required
              />
              <div className="grid grid-cols-2 gap-2 text-xs">
                <div>
                  <label className="text-slate-500 text-[10px] block mb-1">기본색</label>
                  <input
                    type="color"
                    value={newBrandPrimaryColor}
                    onChange={(e) => setNewBrandPrimaryColor(e.target.value)}
                    className="w-full bg-transparent h-8 cursor-pointer rounded border border-slate-800"
                  />
                </div>
                <div>
                  <label className="text-slate-500 text-[10px] block mb-1">보조색</label>
                  <input
                    type="color"
                    value={newBrandSecondaryColor}
                    onChange={(e) => setNewBrandSecondaryColor(e.target.value)}
                    className="w-full bg-transparent h-8 cursor-pointer rounded border border-slate-800"
                  />
                </div>
              </div>
              <input
                type="text"
                placeholder="대표 고지문구 입력"
                value={newBrandDisclaimer}
                onChange={(e) => setNewBrandDisclaimer(e.target.value)}
                className="w-full form-input px-3 py-1.5 text-xs"
              />
              <button type="submit" className="w-full btn-primary py-2 rounded-lg text-xs font-semibold">
                브랜드 신규 추가
              </button>
            </form>
          </div>

          {/* Edit Active Brand Info */}
          {editingBrand && (
            <div className="glass-card p-6 bg-slate-900/10 border-slate-800/80 space-y-4">
              <h2 className="text-sm font-bold text-white">선택 브랜드 설정 편집</h2>
              <form onSubmit={handleUpdateBrand} className="space-y-4 text-xs">
                <div>
                  <label className="text-slate-400 block mb-1">브랜드 이름</label>
                  <input
                    type="text"
                    value={editingBrand.name}
                    onChange={(e) => setEditingBrand({ ...editingBrand, name: e.target.value })}
                    className="w-full form-input px-3 py-2"
                    required
                  />
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="text-slate-400 block mb-1">기본 색상</label>
                    <div className="flex items-center space-x-2">
                      <input
                        type="color"
                        value={editingBrand.brand_colors?.primary || "#4F46E5"}
                        onChange={(e) => setEditingBrand({
                          ...editingBrand,
                          brand_colors: {
                            primary: e.target.value,
                            secondary: editingBrand.brand_colors?.secondary || "#10B981"
                          }
                        })}
                        className="bg-transparent h-8 w-8 cursor-pointer rounded border border-slate-800"
                      />
                      <span className="text-slate-400">{editingBrand.brand_colors?.primary}</span>
                    </div>
                  </div>
                  <div>
                    <label className="text-slate-400 block mb-1">보조 색상</label>
                    <div className="flex items-center space-x-2">
                      <input
                        type="color"
                        value={editingBrand.brand_colors?.secondary || "#10B981"}
                        onChange={(e) => setEditingBrand({
                          ...editingBrand,
                          brand_colors: {
                            primary: editingBrand.brand_colors?.primary || "#4F46E5",
                            secondary: e.target.value
                          }
                        })}
                        className="bg-transparent h-8 w-8 cursor-pointer rounded border border-slate-800"
                      />
                      <span className="text-slate-400">{editingBrand.brand_colors?.secondary}</span>
                    </div>
                  </div>
                </div>
                <div>
                  <label className="text-slate-400 block mb-1">하단 고통 고지/면책문구</label>
                  <textarea
                    rows={3}
                    value={editingBrand.default_disclaimer || ""}
                    onChange={(e) => setEditingBrand({ ...editingBrand, default_disclaimer: e.target.value })}
                    className="w-full form-input px-3 py-2 resize-none"
                    placeholder="상세페이지 하단에 항상 고정 삽입될 브랜드의 정품보증 및 CS 면책 문구를 입력하세요."
                  ></textarea>
                </div>
                <button type="submit" className="w-full btn-primary py-2.5 rounded-xl font-bold text-white">
                  브랜드 정보 저장
                </button>
              </form>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

"use client";

import { useEffect, useState } from "react";
import { apiUrl } from "@/lib/api";

type Connection = {
  id: string;
  extension_name: string;
  extension_version: string;
  created_at: string;
  last_used_at?: string | null;
  token_expires_at?: string | null;
  active: boolean;
};

function mockHeaders() { return {}; }

export default function BrowserCapturePage() {
  const [code, setCode] = useState("");
  const [expiresAt, setExpiresAt] = useState("");
  const [connections, setConnections] = useState<Connection[]>([]);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  const loadConnections = async () => {
    try {
      const response = await fetch(apiUrl("/api/v1/browser-extension/connections"), { headers: mockHeaders() });
      if (!response.ok) throw new Error("연결 목록을 불러오지 못했습니다.");
      const body = await response.json();
      setConnections((body.connections || []).map((connection: Connection & { revoked?: boolean; pending_code?: boolean; expires_at?: string | null }) => ({
        ...connection,
        token_expires_at: connection.expires_at,
        active: !connection.revoked && !connection.pending_code && (!connection.expires_at || new Date(connection.expires_at) > new Date()),
      })));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "연결 목록을 불러오지 못했습니다.");
    }
  };

  useEffect(() => { void loadConnections(); }, []);

  const issueCode = async () => {
    setError(""); setNotice("");
    try {
      const response = await fetch(apiUrl("/api/v1/browser-extension/connection-codes"), {
        method: "POST",
        headers: { "Content-Type": "application/json", ...mockHeaders() },
        body: JSON.stringify({ extension_name: "Sellform Product Capture", extension_version: "0.1.0" }),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail || "연결 코드를 만들지 못했습니다.");
      setCode(body.connection_code);
      setExpiresAt(new Date(body.expires_at).toLocaleString("ko-KR"));
      setNotice("코드를 확장 프로그램 팝업에 입력하세요. 코드는 한 번만 사용할 수 있습니다.");
      await loadConnections();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "연결 코드를 만들지 못했습니다.");
    }
  };

  const revoke = async (connectionId: string) => {
    if (!window.confirm("이 확장 프로그램 연결을 해제할까요?")) return;
    setError("");
    const response = await fetch(apiUrl(`/api/v1/browser-extension/connections/${connectionId}`), {
      method: "DELETE", headers: mockHeaders(),
    });
    if (!response.ok) { setError("연결을 해제하지 못했습니다."); return; }
    setNotice("확장 프로그램 연결을 해제했습니다.");
    await loadConnections();
  };

  const revokeAll = async () => {
    if (!window.confirm("이 작업공간의 모든 브라우저 확장 프로그램 연결을 해제할까요? 모든 기기에서 즉시 다시 연결해야 합니다.")) return;
    setError("");
    const response = await fetch(apiUrl("/api/v1/browser-extension/connections"), {
      method: "DELETE", headers: mockHeaders(),
    });
    if (!response.ok) { setError("전체 연결을 해제하지 못했습니다."); return; }
    const body = await response.json();
    setNotice(`${body.revoked_count || 0}개의 확장 프로그램 연결을 모두 해제했습니다.`);
    await loadConnections();
  };

  return (
    <section className="space-y-6">
      <div>
        <p className="text-emerald-700 text-sm font-semibold">V2 Sprint 8</p>
        <h1 className="text-3xl font-bold text-slate-900 mt-1">브라우저 상품 자료 수집</h1>
        <p className="text-slate-600 mt-2">판매자가 열어 둔 현재 상품 탭에서 선택한 내용만 프로젝트에 참고 자료로 보냅니다.</p>
      </div>

      <div className="rounded-2xl border border-emerald-200 bg-emerald-50 p-5 text-sm text-emerald-950 leading-6">
        <b>안전 원칙:</b> 사이트 제한·로그인·CAPTCHA를 우회하지 않습니다. 쿠키, 비밀번호, 주문·회원 정보는 수집하지 않으며, 공급처 자료는 최종 출력이 아닌 <b>참고용</b>으로만 저장됩니다.
      </div>

      <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <h2 className="font-bold text-lg text-slate-900">1. 확장 프로그램 연결</h2>
        <p className="text-sm text-slate-600 mt-2">Chrome 확장 프로그램을 설치한 뒤, 아래에서 만든 일회용 코드를 팝업에 붙여 넣으세요.</p>
        <button onClick={issueCode} className="mt-4 rounded-lg bg-emerald-600 px-4 py-2.5 text-white font-semibold hover:bg-emerald-700">연결 코드 만들기</button>
        {code && <div className="mt-4 rounded-xl border border-emerald-200 bg-emerald-50 p-4">
          <p className="text-xs font-semibold text-emerald-800">일회용 연결 코드 · {expiresAt}까지</p>
          <code className="block mt-1 text-xl tracking-wider font-bold text-slate-900">{code}</code>
        </div>}
        <ol className="mt-5 list-decimal pl-5 text-sm text-slate-700 space-y-1">
          <li><code>chrome://extensions</code>에서 개발자 모드를 켭니다.</li>
          <li><b>압축해제된 확장 프로그램 로드</b>를 눌러 <code>C:\page\browser-extension</code> 폴더를 선택합니다.</li>
          <li>상품 페이지에서 확장 프로그램을 열고 코드 입력 → 현재 탭 캡처를 누릅니다.</li>
          <li>선택한 텍스트·이미지·대상 프로젝트를 확인한 뒤 전송합니다.</li>
        </ol>
      </div>

      <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <div className="flex items-center justify-between gap-3"><h2 className="font-bold text-lg text-slate-900">2. 내 연결 관리</h2>{connections.some((connection) => connection.active) && <button onClick={revokeAll} className="rounded-lg border border-red-200 px-3 py-1.5 text-sm text-red-700 hover:bg-red-50">모든 기기 연결 해제</button>}</div>
        <div className="mt-3 space-y-2">
          {connections.length === 0 && <p className="text-sm text-slate-500">아직 연결된 확장 프로그램이 없습니다.</p>}
          {connections.map((connection) => <div key={connection.id} className="flex flex-wrap gap-3 items-center justify-between border rounded-xl p-3 text-sm">
            <div><b>{connection.extension_name}</b> <span className="text-slate-500">v{connection.extension_version}</span><p className="text-xs text-slate-500 mt-1">{connection.active ? "연결됨" : "연결 해제 또는 만료"} · 마지막 사용: {connection.last_used_at ? new Date(connection.last_used_at).toLocaleString("ko-KR") : "없음"}</p></div>
            {connection.active && <button onClick={() => revoke(connection.id)} className="rounded-lg border border-red-200 px-3 py-1.5 text-red-700 hover:bg-red-50">연결 해제</button>}
          </div>)}
        </div>
      </div>
      {notice && <p className="rounded-lg bg-emerald-50 p-3 text-sm text-emerald-800">{notice}</p>}
      {error && <p className="rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</p>}
    </section>
  );
}

"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { apiUrl, sessionFetch } from "@/lib/api";

type Pack = { id: string; pack_type: string; pack_key: string; version: number; status: string; content_hash: string; evaluation_score?: number };
type Kit = { id: string; name: string };
type KitVersion = { id: string; brand_kit_id: string; version: number; status: string; scope: string; project_id?: string; content_hash: string };
type Asset = { id: string; filename: string; file_path: string; usage_status: string; asset_role: string };
type Project = { id: string; name: string };
type Classification = { category: string; confidence: number; rationale: string; fallback: boolean; classifier_version: string };

async function request(path: string, init: RequestInit = {}) {
  const response = await sessionFetch(apiUrl(path), {
    ...init,
    headers: { "Content-Type": "application/json", ...(init.headers || {}) },
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(typeof payload.detail === "string" ? payload.detail : "요청을 처리하지 못했습니다.");
  return payload;
}

export default function IntelligenceSettingsPage() {
  const [packs, setPacks] = useState<Pack[]>([]);
  const [kits, setKits] = useState<Kit[]>([]);
  const [versions, setVersions] = useState<KitVersion[]>([]);
  const [assets, setAssets] = useState<Asset[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [kitName, setKitName] = useState("기본 브랜드 키트");
  const [selectedKit, setSelectedKit] = useState("");
  const [selectedProject, setSelectedProject] = useState("");
  const [logoIds, setLogoIds] = useState<string[]>([]);
  const [fontIds, setFontIds] = useState<string[]>([]);
  const [primaryColor, setPrimaryColor] = useState("#0F766E");
  const [secondaryColor, setSecondaryColor] = useState("#F8FAFC");
  const [tone, setTone] = useState("명확하고 신뢰감 있는 한국어");
  const [forbiddenTerms, setForbiddenTerms] = useState("무조건, 완치, 최저가 보장");
  const [ctaRule, setCtaRule] = useState("제품 정보를 확인하세요");
  const [imageDirection, setImageDirection] = useState("clean_product_led");
  const [layoutDirection, setLayoutDirection] = useState("mobile_first");
  const [backgroundDirection, setBackgroundDirection] = useState("light_neutral");
  const [watermarkPolicy, setWatermarkPolicy] = useState("disabled");
  const [proposalType, setProposalType] = useState<"category" | "channel">("category");
  const [proposalKey, setProposalKey] = useState("other");
  const [classificationText, setClassificationText] = useState("휴대용 무선 선풍기 USB 충전 배터리");
  const [classification, setClassification] = useState<Classification | null>(null);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [evaluation, setEvaluation] = useState<{ accuracy: number; dataset_version: string } | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    const [packData, kitData, assetData, projectData] = await Promise.all([
      request("/api/v1/prompt-intelligence/packs"), request("/api/v1/brand-kits"),
      request("/api/v1/brand-kits/assets"), request("/api/v1/projects"),
    ]);
    setPacks(packData); setKits(kitData.kits); setVersions(kitData.versions);
    setAssets(assetData); setProjects(projectData);
    setSelectedKit((value) => value || kitData.kits[0]?.id || "");
    setSelectedProject((value) => value || projectData[0]?.id || "");
  }, []);

  useEffect(() => { load().catch((reason) => setError(reason.message)); }, [load]);

  const act = async (work: () => Promise<unknown>, success: string) => {
    setBusy(true); setError(""); setMessage("");
    try { await work(); await load(); setMessage(success); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "요청을 처리하지 못했습니다."); }
    finally { setBusy(false); }
  };

  const activeVersions = useMemo(() => versions.filter((item) => item.status === "active"), [versions]);
  const versionPayload = {
    logo_asset_ids: logoIds, font_asset_ids: fontIds,
    color_tokens: { primary: primaryColor, secondary: secondaryColor },
    typography: { heading: "Pretendard", body: "Pretendard" },
    tone_of_voice: { description: tone }, forbidden_terms: forbiddenTerms.split(",").map((value) => value.trim()).filter(Boolean),
    cta_rules: { primary: ctaRule }, image_style: { direction: imageDirection },
    layout_rules: { direction: layoutDirection, mobile_first: layoutDirection === "mobile_first" },
    background_rules: { preference: backgroundDirection },
    watermark_policy: { mode: watermarkPolicy },
    constraints: { preserve_identity: true }, asset_rights: { attested: true },
  };

  return (
    <main className="mx-auto max-w-6xl space-y-8 px-6 py-10 text-slate-900">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div><p className="text-sm font-semibold text-emerald-700">LG-6</p><h1 className="text-3xl font-bold">Prompt Intelligence · Brand Kit</h1>
          <p className="mt-2 text-sm text-slate-600">활성 팩과 불변 Brand Kit 버전을 관리합니다. 실제 이미지 생성 비용은 발생하지 않습니다.</p></div>
        <a href="/workspace/settings" className="rounded-lg border px-4 py-2 text-sm">기본 설정으로</a>
      </header>
      {error && <div role="alert" className="rounded-xl border border-red-300 bg-red-50 p-4 text-sm text-red-700">{error}</div>}
      {message && <div className="rounded-xl border border-emerald-300 bg-emerald-50 p-4 text-sm text-emerald-800">{message}</div>}

      <section className="rounded-2xl border bg-white p-6 shadow-sm" data-testid="prompt-pack-admin">
        <div className="flex flex-wrap items-center justify-between gap-3"><div><h2 className="text-xl font-bold">프롬프트 팩 운영</h2>
          <p className="text-sm text-slate-500">category와 channel은 별도 버전이며 draft는 자동 활성화되지 않습니다.</p></div>
          <div className="flex gap-2"><button disabled={busy} onClick={() => act(() => request("/api/v1/prompt-intelligence/packs/seed", { method: "POST" }), "기본 팩을 준비했습니다.")} className="rounded-lg bg-slate-900 px-4 py-2 text-sm text-white">기본 팩 준비</button>
          <button disabled={busy} onClick={() => act(async () => { const data = await request("/api/v1/prompt-intelligence/evaluate", { method: "POST" }); setEvaluation(data); }, "Golden Dataset 평가를 완료했습니다.")} className="rounded-lg bg-emerald-700 px-4 py-2 text-sm text-white">분류 정확도 평가</button></div></div>
        {evaluation && <p className="mt-4 rounded-lg bg-emerald-50 p-3 text-sm">{evaluation.dataset_version} 정확도: <b>{(evaluation.accuracy * 100).toFixed(1)}%</b></p>}
        <div className="mt-4 rounded-xl border border-sky-200 bg-sky-50 p-4" data-testid="classifier-preview">
          <h3 className="font-semibold">카테고리 분류 미리보기</h3>
          <div className="mt-2 flex flex-wrap gap-2">
            <input aria-label="분류할 상품 설명" value={classificationText} onChange={(event) => setClassificationText(event.target.value)} className="min-w-72 flex-1 rounded-lg border bg-white px-3 py-2 text-sm" />
            <button disabled={busy || !classificationText.trim()} onClick={() => act(async () => {
              const data = await request("/api/v1/prompt-intelligence/classify", { method: "POST", body: JSON.stringify({ text: classificationText }) });
              setClassification(data);
            }, "분류 결과를 확인했습니다.")} className="rounded-lg border border-sky-400 bg-white px-4 py-2 text-sm">분류 확인</button>
          </div>
          {classification && <dl className="mt-3 grid gap-2 text-sm sm:grid-cols-4">
            <div><dt className="text-slate-500">카테고리</dt><dd className="font-semibold">{classification.category}</dd></div>
            <div><dt className="text-slate-500">신뢰도</dt><dd>{(classification.confidence * 100).toFixed(1)}%</dd></div>
            <div><dt className="text-slate-500">안전 fallback</dt><dd>{classification.fallback ? "사용" : "미사용"}</dd></div>
            <div><dt className="text-slate-500">근거</dt><dd>{classification.rationale}</dd></div>
          </dl>}
        </div>
        <div className="mt-5 grid gap-3 md:grid-cols-2">
          {packs.length === 0 && <p className="text-sm text-slate-500">아직 팩이 없습니다. ‘기본 팩 준비’를 눌러 주세요.</p>}
          {packs.map((pack) => <article key={pack.id} className="rounded-xl border p-4">
            <div className="flex items-center justify-between"><b>{pack.pack_type} · {pack.pack_key}</b><span className="rounded bg-slate-100 px-2 py-1 text-xs">v{pack.version} {pack.status}</span></div>
            <code className="mt-2 block truncate text-xs text-slate-500">{pack.content_hash}</code>
            <div className="mt-3 flex flex-wrap gap-2">
              {pack.status === "draft_generated" && <button onClick={() => act(() => request(`/api/v1/prompt-intelligence/versions/${pack.id}/validate`, { method: "POST" }), "검증 대기 상태로 변경했습니다.")} className="rounded border px-2 py-1 text-xs">검증</button>}
              {pack.status === "validation_pending" && <button onClick={() => act(() => request(`/api/v1/prompt-intelligence/versions/${pack.id}/approve`, { method: "POST" }), "팩을 승인했습니다.")} className="rounded border px-2 py-1 text-xs">승인</button>}
              {pack.status === "approved" && <button onClick={() => act(() => request(`/api/v1/prompt-intelligence/versions/${pack.id}/activate`, { method: "POST" }), "팩을 활성화했습니다.")} className="rounded bg-emerald-700 px-2 py-1 text-xs text-white">활성화</button>}
              {pack.status === "active" && <button onClick={() => act(() => request(`/api/v1/prompt-intelligence/versions/${pack.id}/deprecate`, { method: "POST" }), "팩을 사용 중지했습니다.")} className="rounded border px-2 py-1 text-xs">사용 중지</button>}
            </div></article>)}
        </div>
        <div className="mt-4 flex flex-wrap gap-2">
          <select aria-label="제안 팩 유형" value={proposalType} onChange={(event) => setProposalType(event.target.value as "category" | "channel")} className="rounded-lg border px-3 py-2 text-sm"><option value="category">category</option><option value="channel">channel</option></select>
          <input aria-label="제안 팩 키" value={proposalKey} onChange={(event) => setProposalKey(event.target.value)} className="rounded-lg border px-3 py-2 text-sm" />
          <button disabled={busy || !proposalKey.trim()} onClick={() => act(() => request("/api/v1/prompt-intelligence/packs/propose", { method: "POST", body: JSON.stringify({ pack_type: proposalType, pack_key: proposalKey.trim() }) }), "새 draft 제안을 만들었습니다. 자동 활성화되지 않았습니다.")} className="rounded-lg border border-violet-300 px-4 py-2 text-sm text-violet-700">새 draft 제안</button>
        </div>
      </section>

      <section className="rounded-2xl border bg-white p-6 shadow-sm" data-testid="brand-kit-admin">
        <h2 className="text-xl font-bold">Brand Kit</h2><p className="text-sm text-slate-500">새 프로젝트는 생성 시점의 활성 workspace 버전을 고정합니다.</p>
        <div className="mt-5 flex gap-2"><input aria-label="Brand Kit 이름" value={kitName} onChange={(event) => setKitName(event.target.value)} className="flex-1 rounded-lg border px-3 py-2" />
          <button onClick={() => act(() => request("/api/v1/brand-kits", { method: "POST", body: JSON.stringify({ name: kitName }) }), "Brand Kit을 만들었습니다.")} className="rounded-lg bg-slate-900 px-4 py-2 text-white">Kit 만들기</button></div>
        <div className="mt-5 grid gap-4 md:grid-cols-2"><label className="text-sm">대상 Kit<select aria-label="대상 Brand Kit" value={selectedKit} onChange={(e) => setSelectedKit(e.target.value)} className="mt-1 w-full rounded-lg border p-2"><option value="">선택</option>{kits.map((kit) => <option key={kit.id} value={kit.id}>{kit.name}</option>)}</select></label>
          <label className="text-sm">프로젝트 override 대상<select aria-label="프로젝트" value={selectedProject} onChange={(e) => setSelectedProject(e.target.value)} className="mt-1 w-full rounded-lg border p-2"><option value="">선택</option>{projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}</select></label>
          <label className="text-sm">Primary color<input aria-label="Primary color" value={primaryColor} onChange={(e) => setPrimaryColor(e.target.value)} className="mt-1 w-full rounded-lg border p-2" /></label>
          <label className="text-sm">Secondary color<input aria-label="Secondary color" value={secondaryColor} onChange={(e) => setSecondaryColor(e.target.value)} className="mt-1 w-full rounded-lg border p-2" /></label></div>
        <label className="mt-4 block text-sm">말투·톤<input aria-label="말투와 톤" value={tone} onChange={(e) => setTone(e.target.value)} className="mt-1 w-full rounded-lg border p-2" /></label>
        <div className="mt-4 grid gap-4 md:grid-cols-2">
          <label className="text-sm">금지어(쉼표 구분)<input aria-label="금지어" value={forbiddenTerms} onChange={(event) => setForbiddenTerms(event.target.value)} className="mt-1 w-full rounded-lg border p-2" /></label>
          <label className="text-sm">CTA 규칙<input aria-label="CTA 규칙" value={ctaRule} onChange={(event) => setCtaRule(event.target.value)} className="mt-1 w-full rounded-lg border p-2" /></label>
          <label className="text-sm">이미지 스타일<input aria-label="이미지 스타일" value={imageDirection} onChange={(event) => setImageDirection(event.target.value)} className="mt-1 w-full rounded-lg border p-2" /></label>
          <label className="text-sm">레이아웃 규칙<input aria-label="레이아웃 규칙" value={layoutDirection} onChange={(event) => setLayoutDirection(event.target.value)} className="mt-1 w-full rounded-lg border p-2" /></label>
          <label className="text-sm">배경 규칙<input aria-label="배경 규칙" value={backgroundDirection} onChange={(event) => setBackgroundDirection(event.target.value)} className="mt-1 w-full rounded-lg border p-2" /></label>
          <label className="text-sm">워터마크 정책<select aria-label="워터마크 정책" value={watermarkPolicy} onChange={(event) => setWatermarkPolicy(event.target.value)} className="mt-1 w-full rounded-lg border p-2"><option value="disabled">사용 안 함</option><option value="logo_subtle">로고를 은은하게</option><option value="required">항상 표시</option></select></label>
        </div>
        <fieldset className="mt-5"><legend className="text-sm font-semibold">권리가 확인된 로고·서체 파일 선택</legend>
          <div className="mt-2 grid gap-2 md:grid-cols-2">{assets.length === 0 && <p className="text-sm text-slate-500">선택 가능한 판매자 보유 파일이 없습니다. 프로젝트에서 권리 보유 이미지로 업로드해 주세요.</p>}
            {assets.map((asset) => <div key={asset.id} className="rounded-lg border p-3 text-sm"><div className="flex items-center"><b>{asset.filename}</b><span className="ml-auto text-xs text-emerald-700">{asset.usage_status}</span></div><div className="mt-2 flex gap-4">
              <label className="flex items-center gap-2"><input aria-label={`${asset.filename} 로고로 사용`} type="checkbox" checked={logoIds.includes(asset.id)} onChange={(e) => setLogoIds((current) => e.target.checked ? Array.from(new Set([...current, asset.id])) : current.filter((id) => id !== asset.id))} />로고</label>
              <label className="flex items-center gap-2"><input aria-label={`${asset.filename} 폰트로 사용`} type="checkbox" checked={fontIds.includes(asset.id)} onChange={(e) => setFontIds((current) => e.target.checked ? Array.from(new Set([...current, asset.id])) : current.filter((id) => id !== asset.id))} />폰트</label>
            </div></div>)}</div></fieldset>
        <div className="mt-5 flex flex-wrap gap-2"><button disabled={!selectedKit || busy} onClick={() => act(() => request(`/api/v1/brand-kits/${selectedKit}/versions`, { method: "POST", body: JSON.stringify(versionPayload) }), "불변 workspace draft 버전을 만들었습니다.")} className="rounded-lg border px-4 py-2 text-sm">Workspace 버전 만들기</button>
          <button disabled={!selectedKit || !selectedProject || busy} onClick={() => act(() => request(`/api/v1/brand-kits/projects/${selectedProject}/overrides`, { method: "POST", body: JSON.stringify({ brand_kit_id: selectedKit, activate: true, ...versionPayload }) }), "프로젝트 override 버전을 만들고 활성화했습니다.")} className="rounded-lg bg-violet-700 px-4 py-2 text-sm text-white">프로젝트 override 만들기</button></div>
        <div className="mt-5 space-y-2">{versions.map((version) => <div key={version.id} className="flex flex-wrap items-center gap-2 rounded-lg bg-slate-50 p-3 text-sm"><b>v{version.version}</b><span>{version.scope}</span><span>{version.status}</span><code className="min-w-0 flex-1 truncate text-xs">{version.content_hash}</code>
          {version.scope === "workspace" && version.status === "draft" && <button onClick={() => act(() => request(`/api/v1/brand-kits/versions/${version.id}/activate`, { method: "POST" }), "Workspace Brand Kit을 활성화했습니다.")} className="rounded bg-emerald-700 px-3 py-1 text-white">활성화</button>}</div>)}</div>
        {activeVersions.length === 0 && <p className="mt-4 text-sm text-amber-700">활성 Brand Kit이 없어도 기존 프로젝트는 안전한 기본값으로 계속 동작합니다.</p>}
      </section>
    </main>
  );
}

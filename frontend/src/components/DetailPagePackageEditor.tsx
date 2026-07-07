'use client';

import React, { useState, useEffect, useCallback } from 'react';
import AiEditCommandPanel from './AiEditCommandPanel';
import SalesPackageExportPanel from './SalesPackageExportPanel';

export interface DetailPagePackageEditorProps {
  projectId: string;
  backendUrl: string;
  headers: Record<string, string>;
  onSwitchToEditTab?: () => void;
}

export interface CopySection {
  id: string;
  section_type: string;
  title: string | null;
  body_copy: string | null;
  associated_fact_ids: string[];
  image_asset_id: string | null;
  sort_order: number;
  is_visible: boolean;
}

export interface VisualSlot {
  kind: string;
  role: string;
  asset_id?: string;
  filename?: string;
  file_path?: string;
  fallback_label: string;
}

export interface PageSectionRendered {
  key: string;
  layout: string;
  eyebrow: string;
  headline: string;
  subcopy: string;
  visual_slot: VisualSlot;
  image_asset_id?: string | null;
  style?: {
    style_key: string;
    background_tone: string;
  };
}

export interface DetailPagePackageData {
  sales_strategy?: {
    target_customer: string;
    buyer_problem: string;
    main_selling_point: string;
    supporting_points: string[];
    tone: string;
  };
  copy_sections: CopySection[];
  visual_plan?: {
    selected_style: string;
    selected_background: string;
    jobs_count: number;
  };
  page_sections: PageSectionRendered[];
  marketplace_copy: {
    title: string;
    description: string;
    bullet_points: string[];
  };
  export_targets: string[];
}

export default function DetailPagePackageEditor({
  projectId,
  backendUrl,
  headers,
  onSwitchToEditTab,
}: DetailPagePackageEditorProps) {
  const [pkg, setPkg] = useState<DetailPagePackageData | null>(null);
  const [loading, setLoading] = useState(true);
  const [selectedSectionId, setSelectedSectionId] = useState<string | null>(null);
  const [isProcessing, setIsProcessing] = useState(false);
  const [directTitle, setDirectTitle] = useState('');
  const [directBody, setDirectBody] = useState('');

  // 1. Fetch package
  const loadPackage = useCallback(async () => {
    try {
      setLoading(true);
      const res = await fetch(`${backendUrl}/projects/${projectId}/detail-page-package`, {
        headers,
      });
      if (res.ok) {
        const data = await res.json();
        setPkg(data);
        if (data.copy_sections && data.copy_sections.length > 0) {
          // Select first section by default if none selected
          setSelectedSectionId((prev) => prev || data.copy_sections[0].id);
        }
      }
    } catch (err) {
      console.error('Failed to load detail page package:', err);
    } finally {
      setLoading(false);
    }
  }, [backendUrl, projectId, headers]);

  useEffect(() => {
    loadPackage();
  }, [loadPackage]);

  // Sync direct edit form when selection changes
  useEffect(() => {
    if (pkg && selectedSectionId) {
      const sec = pkg.copy_sections.find((s: CopySection) => s.id === selectedSectionId);
      if (sec) {
        setDirectTitle(sec.title || '');
        setDirectBody(sec.body_copy || '');
      }
    }
  }, [selectedSectionId, pkg]);

  // 2. Direct edit submit
  const handleDirectSave = async () => {
    if (!selectedSectionId || !pkg) return;
    try {
      setIsProcessing(true);
      const sectionsUpdated = pkg.copy_sections.map((section: CopySection) =>
        section.id === selectedSectionId
          ? { ...section, title: directTitle, body_copy: directBody }
          : section
      );
      const response = await fetch(`${backendUrl}/projects/${projectId}/page`, {
        method: 'PATCH',
        headers: {
          ...headers,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          sections: sectionsUpdated.map((section: CopySection) => ({
            id: section.id,
            title: section.title,
            body_copy: section.body_copy,
            sort_order: section.sort_order,
            is_visible: section.is_visible,
            image_asset_id: section.image_asset_id || '',
          })),
        }),
      });
      if (!response.ok) {
        throw new Error(`Failed to save section: ${response.status}`);
      }
      await loadPackage();
    } catch (err) {
      console.error('Failed to save changes directly:', err);
    } finally {
      setIsProcessing(false);
    }
  };

  // 3. Apply AI preview proposal after user confirms the compare modal.
  // Sprint 77 contract: preview is read-only; only this apply action persists via PATCH.
  const handleApplyAiProposal = async (title: string, bodyCopy: string) => {
    if (!selectedSectionId || !pkg) return;
    try {
      setIsProcessing(true);
      const sectionsUpdated = pkg.copy_sections.map((section: CopySection) =>
        section.id === selectedSectionId
          ? { ...section, title, body_copy: bodyCopy }
          : section
      );
      const response = await fetch(`${backendUrl}/projects/${projectId}/page`, {
        method: 'PATCH',
        headers: {
          ...headers,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          sections: sectionsUpdated.map((section: CopySection) => ({
            id: section.id,
            title: section.title,
            body_copy: section.body_copy,
            sort_order: section.sort_order,
            is_visible: section.is_visible,
            image_asset_id: section.image_asset_id || '',
          })),
        }),
      });
      if (!response.ok) {
        throw new Error(`Failed to apply AI proposal: ${response.status}`);
      }
      setPkg({ ...pkg, copy_sections: sectionsUpdated });
      setDirectTitle(title);
      setDirectBody(bodyCopy);
    } catch (err) {
      console.error('Failed to apply AI proposal:', err);
      throw err;
    } finally {
      setIsProcessing(false);
    }
  };

  if (loading && !pkg) {
    return (
      <div className="flex items-center justify-center min-h-[600px] text-slate-400">
        <svg className="animate-spin h-8 w-8 mr-3 text-blue-500" fill="none" viewBox="0 0 24 24">
          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
        </svg>
        <span>Loading detail page package...</span>
      </div>
    );
  }

  const selectedSection = pkg?.copy_sections?.find((s: CopySection) => s.id === selectedSectionId);

  return (
    <div className="space-y-8">
      <div className="grid grid-cols-12 gap-6 min-h-[800px] bg-slate-950 p-6 text-slate-100 rounded-2xl border border-slate-900 shadow-3xl">
        {/* ================= LEFT PANE: Sales Strategy & Outline ================= */}
        <div className="col-span-12 lg:col-span-3 space-y-6">
          <div className="bg-slate-900 border border-slate-850 rounded-xl p-5 shadow-md">
            <h4 className="text-sm font-bold text-slate-400 uppercase tracking-wider mb-3">🎯 Sales Strategy</h4>
            {pkg?.sales_strategy ? (
              <div className="space-y-4 text-xs">
                <div>
                  <span className="text-slate-500 block font-semibold mb-1">Target Customer</span>
                  <p className="text-slate-200 bg-slate-950/60 p-2.5 rounded border border-slate-850/60 leading-relaxed">
                    {pkg.sales_strategy.target_customer}
                  </p>
                </div>
                <div>
                  <span className="text-slate-500 block font-semibold mb-1">Buyer Pain Point</span>
                  <p className="text-slate-200 bg-slate-950/60 p-2.5 rounded border border-slate-850/60 leading-relaxed">
                    {pkg.sales_strategy.buyer_problem}
                  </p>
                </div>
                <div>
                  <span className="text-slate-500 block font-semibold mb-1">Main Selling Point</span>
                  <p className="text-slate-200 bg-slate-950/60 p-2.5 rounded border border-slate-850/60 leading-relaxed">
                    {pkg.sales_strategy.main_selling_point}
                  </p>
                </div>
              </div>
            ) : (
              <p className="text-xs text-slate-500 italic">No sales strategy available.</p>
            )}
          </div>

          <div className="bg-slate-900 border border-slate-850 rounded-xl p-5 shadow-md">
            <h4 className="text-sm font-bold text-slate-400 uppercase tracking-wider mb-3">📋 Section Outline</h4>
            <div className="space-y-2">
              {pkg?.copy_sections?.map((sec: CopySection) => {
                const isSelected = sec.id === selectedSectionId;
                return (
                  <button
                    key={sec.id}
                    onClick={() => setSelectedSectionId(sec.id)}
                    className={`w-full text-left p-3 rounded-lg border transition-all ${
                      isSelected
                        ? 'bg-blue-600/10 border-blue-500 text-blue-200 font-semibold'
                        : 'bg-slate-950/40 border-slate-850 text-slate-400 hover:bg-slate-900 hover:text-slate-300'
                    }`}
                  >
                    <div className="flex justify-between items-center">
                      <span className="text-xs font-mono text-slate-500 truncate mr-2">{sec.section_type}</span>
                      {!sec.is_visible && (
                        <span className="text-[10px] bg-slate-800 text-slate-500 px-1.5 py-0.5 rounded border border-slate-700">
                          Hidden
                        </span>
                      )}
                    </div>
                    <h5 className="text-xs truncate mt-1 text-slate-200">{sec.title || 'Untitled Section'}</h5>
                  </button>
                );
              })}
            </div>
          </div>
        </div>

        {/* ================= CENTER PANE: Mobile Preview ================= */}
        <div className="col-span-12 lg:col-span-5 flex justify-center items-start">
          <div className="relative mx-auto w-[375px] h-[800px] bg-slate-950 rounded-[40px] shadow-[0_0_0_12px_#1e293b,0_20px_50px_rgba(0,0,0,0.8)] border border-slate-800 flex flex-col overflow-hidden">
            {/* Status bar mock */}
            <div className="w-full h-8 bg-slate-950 flex justify-between items-center px-6 text-[10px] text-slate-400 font-medium">
              <span>09:41</span>
              <div className="w-16 h-4 bg-slate-900 rounded-full mx-auto" />
              <div className="flex gap-1 items-center">
                <span>5G</span>
                <div className="w-4 h-2 bg-slate-400 rounded-sm" />
              </div>
            </div>

            {/* Mobile frame scroll viewport */}
            <div className="flex-1 overflow-y-auto px-4 py-2 space-y-4 scrollbar-thin scrollbar-thumb-slate-800">
              {pkg?.page_sections?.map((sec: PageSectionRendered) => {
                const matchingCopySec = pkg.copy_sections.find((cs: CopySection) => cs.section_type === sec.key);
                const isSelected = matchingCopySec?.id === selectedSectionId;

                return (
                  <div
                    key={sec.key}
                    onClick={() => matchingCopySec && setSelectedSectionId(matchingCopySec.id)}
                    className={`cursor-pointer rounded-xl overflow-hidden border transition-all ${
                      isSelected
                        ? 'border-blue-500 ring-2 ring-blue-500/20 shadow-lg'
                        : 'border-slate-800 bg-slate-900 hover:border-slate-700'
                    }`}
                  >
                    {/* Visual Slot Box */}
                    <div className="relative aspect-[16/9] w-full bg-slate-950 flex items-center justify-center text-center overflow-hidden">
                      {sec.visual_slot?.kind === 'product_image' && sec.visual_slot.filename ? (
                        <img
                          src={`${backendUrl.replace(/\/api\/v1\/?$/, '')}/uploads/${sec.visual_slot.filename}`}
                          alt={sec.headline || sec.visual_slot.role}
                          className="h-full w-full object-cover"
                        />
                      ) : (
                        // "image needed" state with high visibility
                        <div className="w-full h-full flex flex-col justify-center items-center border-2 border-dashed border-amber-600/40 bg-amber-950/10 p-4">
                          <div className="w-8 h-8 rounded-full bg-amber-500/10 border border-amber-500/30 flex items-center justify-center text-amber-500 mb-2 animate-pulse">
                            ⚠️
                          </div>
                          <span className="text-[10px] font-bold text-amber-500 uppercase tracking-widest">
                            image needed
                          </span>
                          <span className="text-[9px] text-slate-500 mt-1 text-center leading-normal">
                            Requires approved Sprint 44.5 visual asset
                          </span>
                        </div>
                      )}
                    </div>

                    {/* Text Content */}
                    <div className="p-4 space-y-2 bg-slate-900/60 backdrop-blur-sm border-t border-slate-900">
                      <span className="text-[9px] font-mono text-slate-500 uppercase block tracking-wider">
                        {sec.key}
                      </span>
                      <h4 className="text-xs font-bold text-slate-200">{sec.headline}</h4>
                      <p className="text-[10px] text-slate-400 leading-relaxed whitespace-pre-wrap">{sec.subcopy}</p>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>

        {/* ================= RIGHT PANE: Edit Form & AI Commands ================= */}
        <div className="col-span-12 lg:col-span-4 space-y-6">
          {selectedSection ? (
            <>
              {/* Direct Edit Form */}
              <div className="bg-slate-900 border border-slate-850 rounded-xl p-5 shadow-md space-y-4">
                <div className="flex items-center justify-between">
                  <h4 className="text-sm font-bold text-slate-200">✍️ Direct Section Editor</h4>
                  <span className="text-[10px] bg-slate-800 text-slate-400 px-2 py-0.5 rounded font-mono border border-slate-750">
                    {selectedSection.section_type}
                  </span>
                </div>

                <div className="space-y-3">
                  <div>
                    <label className="block text-xs font-semibold text-slate-400 mb-1">Title</label>
                    <input
                      type="text"
                      value={directTitle}
                      onChange={(e) => setDirectTitle(e.target.value)}
                      className="w-full bg-slate-950 border border-slate-800 rounded p-2.5 text-xs text-slate-100 placeholder-slate-600 focus:outline-none focus:ring-1 focus:ring-blue-500"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-semibold text-slate-400 mb-1">Body Copy</label>
                    <textarea
                      value={directBody}
                      onChange={(e) => setDirectBody(e.target.value)}
                      rows={4}
                      className="w-full bg-slate-950 border border-slate-800 rounded p-2.5 text-xs text-slate-100 placeholder-slate-600 focus:outline-none focus:ring-1 focus:ring-blue-500 leading-normal"
                    />
                  </div>
                  <button
                    onClick={handleDirectSave}
                    disabled={isProcessing}
                    className="w-full bg-slate-800 hover:bg-slate-700 text-slate-200 font-semibold py-2 px-3 rounded text-xs transition border border-slate-700 disabled:opacity-40"
                  >
                    Save Section Text
                  </button>
                </div>
              </div>

              {/* AI Command Panel */}
              <AiEditCommandPanel
                projectId={projectId}
                sectionId={selectedSection.id}
                backendUrl={backendUrl}
                headers={headers}
                onApplyProposal={handleApplyAiProposal}
                onUpdateSuccess={loadPackage}
                isProcessing={isProcessing}
              />
            </>
          ) : (
            <div className="bg-slate-900 border border-slate-850 rounded-xl p-6 shadow-md text-center text-slate-500 text-xs italic">
              Please select a section from outline or preview to edit.
            </div>
          )}
        </div>
      </div>

      <SalesPackageExportPanel
        projectId={projectId}
        backendUrl={backendUrl}
        headers={headers}
        onSwitchToEditTab={onSwitchToEditTab}
      />
    </div>
  );
}

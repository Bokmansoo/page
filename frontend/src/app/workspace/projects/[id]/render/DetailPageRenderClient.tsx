"use client";

import React, { useEffect, useState } from "react";
import { useParams, useSearchParams } from "next/navigation";
import DetailPageDocument, {
  DetailPageAsset,
  DetailPageData,
} from "@/components/DetailPageDocument";
import { apiUrl } from "@/lib/api";

const SESSION_HEADERS: Record<string, string> = {};

interface FinalPageResponse {
  sections_json: DetailPageData & {
    commerce_renderer?: {
      theme_color?: string;
      font_family?: string;
      sections?: DetailPageData["sections"];
    };
  };
}

export default function DetailPageRenderClient() {
  const params = useParams();
  const searchParams = useSearchParams();
  const projectId = params.id as string;
  const [page, setPage] = useState<DetailPageData | null>(null);
  const [assets, setAssets] = useState<DetailPageAsset[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const loadFinalPage = async () => {
      try {
        const versionId = searchParams.get("version_id");
        const headers = SESSION_HEADERS;
        const versionQuery = versionId ? `?version_id=${encodeURIComponent(versionId)}` : "";
        const [finalRes, assetsRes] = await Promise.all([
          fetch(apiUrl(`/api/v1/projects/${projectId}/page/final${versionQuery}`), { headers, credentials: "include" }),
          fetch(apiUrl(`/api/v1/projects/${projectId}/assets`), { headers, credentials: "include" }),
        ]);
        if (!finalRes.ok) {
          throw new Error("Final detail page version is not ready.");
        }
        const finalPage = (await finalRes.json()) as FinalPageResponse;
        // Sprint 6 parity rule: an export always uses the renderer snapshot
        // that was frozen when the page was finalized.  The regular snapshot
        // remains as a backward-compatible fallback for older versions.
        const rendererSnapshot = finalPage.sections_json.commerce_renderer;
        setPage({
          project_id: projectId,
          theme_color: rendererSnapshot?.theme_color || finalPage.sections_json.theme_color,
          font_family: rendererSnapshot?.font_family || finalPage.sections_json.font_family,
          sections: rendererSnapshot?.sections || finalPage.sections_json.sections || [],
        });
        setAssets(assetsRes.ok ? await assetsRes.json() : []);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load final detail page.");
        document.documentElement.dataset.exportReady = "error";
      }
    };

    loadFinalPage();
  }, [projectId, searchParams]);

  if (error) {
    return <main className="p-8 text-sm text-rose-700">{error}</main>;
  }

  if (!page) {
    return <main className="p-8 text-sm text-slate-500">Loading final detail page...</main>;
  }

  return (
    <main className="bg-white py-0">
      <DetailPageDocument page={page} assets={assets} exportMode />
    </main>
  );
}

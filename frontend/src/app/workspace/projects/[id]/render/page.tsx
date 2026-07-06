"use client";

import React, { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import DetailPageDocument, {
  DetailPageAsset,
  DetailPageData,
} from "@/components/DetailPageDocument";
import { apiUrl } from "@/lib/api";

const MOCK_HEADERS = {
  "X-Mock-User-Id": "00000000-0000-0000-0000-000000000001",
  "X-Mock-Workspace-Id": "00000000-0000-0000-0000-000000000002",
};

interface FinalPageResponse {
  sections_json: DetailPageData;
}

export default function DetailPageRenderRoute({ params }: { params: { id: string } }) {
  const searchParams = useSearchParams();
  const [page, setPage] = useState<DetailPageData | null>(null);
  const [assets, setAssets] = useState<DetailPageAsset[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const loadFinalPage = async () => {
      try {
        const versionId = searchParams.get("version_id");
        const headers = {
          "X-Mock-User-Id": searchParams.get("user_id") || MOCK_HEADERS["X-Mock-User-Id"],
          "X-Mock-Workspace-Id":
            searchParams.get("workspace_id") || MOCK_HEADERS["X-Mock-Workspace-Id"],
        };
        const versionQuery = versionId ? `?version_id=${encodeURIComponent(versionId)}` : "";
        const [finalRes, assetsRes] = await Promise.all([
          fetch(apiUrl(`/api/v1/projects/${params.id}/page/final${versionQuery}`), { headers }),
          fetch(apiUrl(`/api/v1/projects/${params.id}/assets`), { headers }),
        ]);
        if (!finalRes.ok) {
          throw new Error("Final detail page version is not ready.");
        }
        const finalPage = (await finalRes.json()) as FinalPageResponse;
        setPage({
          project_id: params.id,
          theme_color: finalPage.sections_json.theme_color,
          font_family: finalPage.sections_json.font_family,
          sections: finalPage.sections_json.sections || [],
        });
        setAssets(assetsRes.ok ? await assetsRes.json() : []);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load final detail page.");
        document.documentElement.dataset.exportReady = "error";
      }
    };

    loadFinalPage();
  }, [params.id, searchParams]);

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

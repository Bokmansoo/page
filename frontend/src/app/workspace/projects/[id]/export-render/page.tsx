import { redirect } from "next/navigation";

type PageProps = {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ version_id?: string }>;
};

export default async function LegacyExportRenderPage({ params, searchParams }: PageProps) {
  const { id } = await params;
  const { version_id: versionId } = await searchParams;
  const query = versionId ? `?version_id=${encodeURIComponent(versionId)}` : "";
  redirect(`/export-render/projects/${id}${query}`);
}

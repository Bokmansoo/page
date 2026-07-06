"use client";

import { useParams } from "next/navigation";
import GeneratedDetailPageResult from "@/components/GeneratedDetailPageResult";

export default function ProjectResultPage() {
  const params = useParams();
  const projectId = params.id as string;

  return <GeneratedDetailPageResult projectId={projectId} />;
}

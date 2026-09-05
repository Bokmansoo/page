"use client";

import { useParams } from "next/navigation";
import VideoStudioPanel from "@/components/video/VideoStudioPanel";

export default function VideoPage() {
  const params = useParams();
  return <VideoStudioPanel projectId={String(params.id)} />;
}

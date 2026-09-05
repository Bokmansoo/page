"use client";

import { useParams } from "next/navigation";
import SocialKitPanel from "@/components/social/SocialKitPanel";

export default function SocialKitPage() {
  const params = useParams();
  return <SocialKitPanel projectId={String(params.id)} />;
}

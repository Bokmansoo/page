"use client";

import React, { Suspense } from "react";
import AIDetailPageIntake from "@/components/AIDetailPageIntake";

export default function WorkspaceDashboard() {
  return (
    <Suspense fallback={<div className="min-h-screen bg-slate-50" />}>
      <AIDetailPageIntake />
    </Suspense>
  );
}

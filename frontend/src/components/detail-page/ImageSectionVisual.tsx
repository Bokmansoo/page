import React from "react";
import { DetailPageSectionVisual, VisualPayload } from "./types";

interface ImageSectionVisualProps {
  section: DetailPageSectionVisual;
  imageSrc: string | null;
  matchedAssetLabel?: string;
  exportMode?: boolean;
}

export default function ImageSectionVisual({
  section,
  imageSrc,
  matchedAssetLabel,
  exportMode = false,
}: ImageSectionVisualProps) {
  const payload = (section.visual_payload || {}) as Partial<VisualPayload>;
  const eyebrow = payload.eyebrow;
  const badges = payload.badges || [];
  const title = section.title || "";
  const body = section.body_copy || section.body || "";

  if (!imageSrc) {
    return (
      <div
        className="mt-8 flex aspect-[4/3] items-center justify-center border border-amber-200 bg-amber-50 text-sm font-bold text-amber-700"
        data-section-visual="image"
      >
        이미지 확인이 필요합니다
      </div>
    );
  }

  const sectionType = section.section_type;
  const isHero = sectionType === "hero";
  const isDarkBg =
    sectionType === "hero" ||
    sectionType === "detail_1" ||
    sectionType === "guarantee";

  return (
    <figure
      className={`relative mt-9 overflow-hidden ${isDarkBg ? (isHero ? "bg-slate-900" : "bg-slate-800") : "bg-white"}`}
      data-section-visual="image"
    >
      <img
        src={imageSrc}
        alt={section.title || ""}
        className="aspect-[4/3] w-full object-cover"
      />
      <div className="pointer-events-none absolute inset-0 bg-gradient-to-t from-slate-950/85 via-slate-950/25 to-transparent" />
      <figcaption className="absolute inset-x-0 bottom-0 p-5 text-white">
        {eyebrow ? (
          <p className="text-[10px] font-black uppercase tracking-[0.28em] text-emerald-200">
            {eyebrow}
          </p>
        ) : null}
        {title ? (
          <h4 className="mt-2 max-w-[92%] text-xl font-black leading-tight drop-shadow">
            {title}
          </h4>
        ) : null}
        {body ? (
          <p className="mt-2 max-w-[92%] text-xs font-semibold leading-relaxed text-white/85 drop-shadow">
            {body}
          </p>
        ) : null}
        {badges.length > 0 ? (
          <div className="mt-3 flex flex-wrap gap-2">
            {badges.map((badge) => (
              <span
                key={badge}
                className="rounded-full bg-white/90 px-3 py-1 text-[10px] font-black text-slate-900 shadow"
              >
                {badge}
              </span>
            ))}
          </div>
        ) : null}
      </figcaption>
      {!exportMode && matchedAssetLabel ? (
        <div className="absolute right-3 top-3 rounded-full bg-emerald-700 px-3 py-1 text-[10px] font-bold text-white">
          {matchedAssetLabel}
        </div>
      ) : null}
    </figure>
  );
}

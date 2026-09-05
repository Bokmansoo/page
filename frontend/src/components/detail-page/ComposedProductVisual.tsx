import React from "react";
import { DetailPageSectionVisual, VisualPayload } from "./types";

interface ComposedProductVisualProps {
  section: DetailPageSectionVisual;
  imageSrc: string | null;
  matchedAssetLabel?: string;
  exportMode?: boolean;
}

const backgroundClasses: Record<string, string> = {
  surface_mint: "bg-[#e9f8f2] text-slate-950",
  surface_ink: "bg-slate-950 text-white",
  surface_sand: "bg-[#f7f0e6] text-slate-950",
};

export default function ComposedProductVisual({
  section,
  imageSrc,
  matchedAssetLabel,
  exportMode = false,
}: ComposedProductVisualProps) {
  const payload = (section.visual_payload || {}) as Partial<VisualPayload>;
  const layout = payload.layout_variant === "hero_product_center" ? "hero_product_center" : "hero_product_right";
  const isCenterLayout = layout === "hero_product_center";
  const background = backgroundClasses[payload.background_token || "surface_mint"] || backgroundClasses.surface_mint;
  const isInk = payload.background_token === "surface_ink";
  const badges = payload.badges || [];
  const title = section.title || "";
  const body = section.body_copy || section.body || "";
  const isAiRedesignRequired = payload.missing_state === "ai_redesign_required";

  return (
    <figure
      className={`relative mt-5 isolate overflow-hidden ${background} ${
        isCenterLayout ? "min-h-[520px] px-6 pb-7 pt-10" : "min-h-[430px] px-6 py-10 sm:px-10"
      }`}
      data-section-visual="composed_product"
      data-composed-product-layout={layout}
    >
      <svg className="pointer-events-none absolute inset-0 -z-10 h-full w-full" aria-hidden="true" viewBox="0 0 760 520" preserveAspectRatio="none">
        <circle cx="625" cy="152" r="168" fill={isInk ? "#14532d" : "#b9ead8"} opacity="0.68" />
        <circle cx="680" cy="122" r="98" fill={isInk ? "#0f766e" : "#d8f3e7"} opacity="0.85" />
        <path d="M42 442 C188 390 262 504 418 440" fill="none" stroke={isInk ? "#6ee7b7" : "#059669"} strokeWidth="4" opacity="0.72" />
      </svg>

      <div className={isCenterLayout ? "flex h-full flex-col" : "grid h-full items-center gap-5 sm:grid-cols-[0.92fr_1.08fr]"}>
        <div className={isCenterLayout ? "order-2 mt-5 text-center" : "relative z-10 max-w-sm text-left"}>
          <p className={`text-[10px] font-black uppercase tracking-[0.24em] ${isInk ? "text-emerald-200" : "text-emerald-700"}`}>
            {payload.eyebrow || "PRODUCT HIGHLIGHT"}
          </p>
          {title ? (
            <h4 className="mt-3 text-2xl font-black leading-tight tracking-[-0.035em] sm:text-3xl">{title}</h4>
          ) : null}
          {body ? <p className={`mt-4 whitespace-pre-line text-sm font-medium leading-6 ${isInk ? "text-slate-200" : "text-slate-600"}`}>{body}</p> : null}
          {badges.length > 0 ? (
            <div className={`mt-5 flex flex-wrap gap-2 ${isCenterLayout ? "justify-center" : "justify-start"}`}>
              {badges.map((badge) => (
                <span key={badge} className={`rounded-full px-3 py-1 text-[10px] font-black shadow-sm ${isInk ? "bg-white text-slate-950" : "bg-white/90 text-emerald-800"}`}>
                  {badge}
                </span>
              ))}
            </div>
          ) : null}
        </div>

        <div className={isCenterLayout ? "order-1 mx-auto flex h-[280px] w-full max-w-md items-center justify-center" : "relative flex h-[350px] items-center justify-center sm:h-[380px]"}>
          <div className={`absolute inset-x-[12%] bottom-[7%] h-[17%] rounded-[999px] blur-2xl ${isInk ? "bg-black/40" : "bg-emerald-900/20"}`} />
          {imageSrc ? (
            <img
              src={imageSrc}
              alt={title || "상품 사진"}
              className="relative z-10 h-full w-full object-contain drop-shadow-[0_24px_28px_rgba(15,23,42,0.22)]"
              data-composed-product-image="true"
            />
          ) : (
            <div className="relative z-10 flex h-[72%] w-[72%] items-center justify-center rounded-3xl border border-dashed border-emerald-700/30 bg-white/40 text-sm font-bold text-emerald-800">
              {isAiRedesignRequired
                ? "AI 리디자인 이미지 생성 및 검토가 필요합니다"
                : "대표 상품 사진을 추가해 주세요"}
            </div>
          )}
        </div>
      </div>
      {!exportMode && matchedAssetLabel ? (
        <span className="absolute right-4 top-4 rounded-full bg-emerald-700 px-3 py-1 text-[10px] font-bold text-white">
          {matchedAssetLabel}
        </span>
      ) : null}
    </figure>
  );
}

"use client";

import { useState } from "react";
import type { StructuredIntakeDraft } from "@/lib/api";

type Props = {
  draft: StructuredIntakeDraft;
  onBack: () => void;
  onConfirm: (draft: StructuredIntakeDraft) => void;
};

export default function StructuredIntakeReview({ draft, onBack, onConfirm }: Props) {
  const [productName, setProductName] = useState(draft.product_name.value);
  const [price, setPrice] = useState(draft.price?.value ?? "");
  const [shipping, setShipping] = useState(draft.shipping?.value ?? "");
  const [mood, setMood] = useState(draft.desired_mood.join(", "));
  const [sellingPoints, setSellingPoints] = useState(
    draft.selling_points.map((point) => ({ ...point, enabled: true }))
  );

  const confirm = () =>
    onConfirm({
      ...draft,
      product_name: { ...draft.product_name, value: productName.trim() },
      selling_points: sellingPoints
        .filter((point) => point.enabled && point.text.trim())
        .map((point) => ({
          source: point.source,
          confidence: "confirmed",
          text: point.text.trim(),
        })),
      price: { value: price.trim(), source: draft.price?.source ?? "seller_review", confidence: "confirmed" },
      shipping: { value: shipping.trim(), source: draft.shipping?.source ?? "seller_review", confidence: "confirmed" },
      desired_mood: mood.split(",").map((value) => value.trim()).filter(Boolean),
    });

  return (
    <section className="w-full max-w-3xl rounded-2xl border border-emerald-100 bg-white p-6 shadow-sm">
      <div className="mb-5">
        <p className="text-sm font-semibold text-emerald-700">AI가 이렇게 이해했어요</p>
        <h2 className="mt-1 text-2xl font-bold text-slate-950">생성 전에 상품 정보를 확인해주세요</h2>
      </div>

      <label className="block text-sm font-semibold text-slate-700">
        상품명
        <input
          aria-label="확인 상품명"
          className="mt-2 w-full rounded-xl border border-slate-200 px-4 py-3 text-sm"
          value={productName}
          onChange={(event) => setProductName(event.target.value)}
        />
      </label>

      <div className="mt-5">
        <p className="text-sm font-semibold text-slate-700">핵심 특징</p>
        <div className="mt-2 space-y-2">
          {sellingPoints.map((point, index) => (
            <label
              key={`${point.source}-${index}`}
              className="flex items-center gap-3 rounded-xl border border-slate-200 px-4 py-3 text-sm"
            >
              <input
                aria-label={`핵심 특징 ${index + 1} 사용`}
                type="checkbox"
                checked={point.enabled}
                onChange={(event) =>
                  setSellingPoints((current) =>
                    current.map((item, itemIndex) =>
                      itemIndex === index ? { ...item, enabled: event.target.checked } : item
                    )
                  )
                }
                className="h-4 w-4 accent-emerald-600"
              />
              <input
                aria-label={`핵심 특징 ${index + 1}`}
                className="min-w-0 flex-1 border-0 font-medium text-slate-900 outline-none"
                value={point.text}
                onChange={(event) =>
                  setSellingPoints((current) =>
                    current.map((item, itemIndex) =>
                      itemIndex === index ? { ...item, text: event.target.value } : item
                    )
                  )
                }
              />
              <span className="ml-auto text-xs text-slate-500">
                {point.confidence === "confirmed" ? "확정" : "확인 필요"}
              </span>
            </label>
          ))}
        </div>
      </div>

      <div className="mt-5 grid grid-cols-1 gap-3 sm:grid-cols-2">
        <label className="block text-sm font-semibold text-slate-700">
          가격
          <input
            aria-label="확인 가격"
            className="mt-2 w-full rounded-xl border border-slate-200 px-4 py-3 text-sm"
            value={price}
            onChange={(event) => setPrice(event.target.value)}
          />
        </label>
        <label className="block text-sm font-semibold text-slate-700">
          배송
          <input
            aria-label="확인 배송"
            className="mt-2 w-full rounded-xl border border-slate-200 px-4 py-3 text-sm"
            value={shipping}
            onChange={(event) => setShipping(event.target.value)}
          />
        </label>
      </div>

      <label className="mt-5 block text-sm font-semibold text-slate-700">
        원하는 분위기
        <input
          aria-label="확인 분위기"
          className="mt-2 w-full rounded-xl border border-slate-200 px-4 py-3 text-sm"
          value={mood}
          onChange={(event) => setMood(event.target.value)}
        />
      </label>

      {draft.desired_mood.length > 0 ? (
        <div className="mt-5">
          <p className="text-sm font-semibold text-slate-700">분위기</p>
          <div className="mt-2 flex flex-wrap gap-2">
            {draft.desired_mood.map((mood) => (
              <span key={mood} className="rounded-full bg-emerald-50 px-3 py-1 text-xs font-bold text-emerald-700">
                {mood}
              </span>
            ))}
          </div>
        </div>
      ) : null}

      <div className="mt-6 flex justify-end gap-3">
        <button
          type="button"
          onClick={onBack}
          className="rounded-xl border border-slate-200 px-5 py-3 text-sm font-semibold text-slate-700"
        >
          다시 입력
        </button>
        <button
          type="button"
          onClick={confirm}
          className="rounded-xl bg-emerald-600 px-5 py-3 text-sm font-bold text-white"
        >
          이 정보로 상세페이지 만들기
        </button>
      </div>
    </section>
  );
}

"use client";

import React, { useState } from "react";

export interface UnderstandingField {
  value: string;
  is_suggestion: boolean;
}

export interface ProductUnderstanding {
  product_type: UnderstandingField;
  target_customer: UnderstandingField;
  buyer_problem: UnderstandingField;
  main_angle_candidates: string[];
  tone_candidates: string[];
  image_candidates: string[];
  unknowns: string[];
}

export interface ConfirmationRowData {
  field_key: string;
  field_label: string;
  suggested_value: string;
  confidence: string;
  edit_options: string[];
}

export interface DirectionVariantData {
  key: string;
  name: string;
  is_recommended: boolean;
  headline: string;
  reason: string;
  section_flow: string[];
  target: string;
  recommended_visual_mood: string;
}

export interface SalesStrategyData {
  target_customer: string;
  buyer_problem: string;
  main_selling_point: string;
  supporting_points: string[];
  tone: string;
  price_strategy: string;
  image_selection: string[];
  risk_notes: string[];
  confirmation_rows: ConfirmationRowData[];
  directions: DirectionVariantData[];
}

export interface SalesStrategyConfirmationPayload {
  target_customer: string;
  buyer_problem: string;
  main_selling_point: string;
  supporting_points: string[];
  tone: string;
  price_strategy: string;
  image_selection: string[];
  risk_notes: string[];
  selected_direction: string;
}

interface ProductUnderstandingCardProps {
  initialData: ProductUnderstanding;
  onConfirm: (confirmedData: ProductUnderstanding) => void;
  // Sprint 43 expanded props
  salesStrategyData: SalesStrategyData | null;
  onConfirmSalesStrategy: (payload: SalesStrategyConfirmationPayload) => void;
  isSubmitting?: boolean;
}

export default function ProductUnderstandingCard({
  initialData,
  onConfirm,
  salesStrategyData,
  onConfirmSalesStrategy,
  isSubmitting = false,
}: ProductUnderstandingCardProps) {
  // Local state for step transition
  const [subStep, setSubStep] = useState<"understanding" | "strategy">("understanding");

  // Step 1 (Understanding) States
  const [productType, setProductType] = useState<string>(initialData.product_type.value);
  const [isProductTypeEditing, setIsProductTypeEditing] = useState(false);
  const [productTypeConfirmed, setProductTypeConfirmed] = useState(false);

  const [targetCustomer, setTargetCustomer] = useState<string>(initialData.target_customer.value);
  const [isTargetCustomerEditing, setIsTargetCustomerEditing] = useState(false);
  const [targetCustomerConfirmed, setTargetCustomerConfirmed] = useState(false);

  const [buyerProblem, setBuyerProblem] = useState<string>(initialData.buyer_problem.value);
  const [isBuyerProblemEditing, setIsBuyerProblemEditing] = useState(false);
  const [buyerProblemConfirmed, setBuyerProblemConfirmed] = useState(false);

  // Cycling indexes for Step 1
  const productTypeAlts = [initialData.product_type.value, "주방 테이블 웨어", "생활용품 식탁 매트", "다목적 실리콘/대나무 매트"].filter(Boolean);
  const [ptAltIdx, setPtAltIdx] = useState(0);

  const targetCustomerAlts = [initialData.target_customer.value, "자연 친화적 라이프스타일과 인테리어를 중시하는 스마트 홈쿡족", "아이가 있어 위생과 친환경 소재를 최우선으로 생각하는 주부층"].filter(Boolean);
  const [tcAltIdx, setTcAltIdx] = useState(0);

  const buyerProblemAlts = [initialData.buyer_problem.value, "식탁 매트에 김치 국물이 배거나 곰팡이가 피어 위생 관리가 번거로운 애로사항", "뜨거운 냄비나 식기를 놓았을 때 테이블 상판이 손상되거나 변색될 우려"].filter(Boolean);
  const [bpAltIdx, setBpAltIdx] = useState(0);

  const cycleProductType = () => {
    const nextIdx = (ptAltIdx + 1) % productTypeAlts.length;
    setPtAltIdx(nextIdx);
    setProductType(productTypeAlts[nextIdx]);
    setProductTypeConfirmed(false);
  };

  const cycleTargetCustomer = () => {
    const nextIdx = (tcAltIdx + 1) % targetCustomerAlts.length;
    setTcAltIdx(nextIdx);
    setTargetCustomer(targetCustomerAlts[nextIdx]);
    setTargetCustomerConfirmed(false);
  };

  const cycleBuyerProblem = () => {
    const nextIdx = (bpAltIdx + 1) % buyerProblemAlts.length;
    setBpAltIdx(nextIdx);
    setBuyerProblem(buyerProblemAlts[nextIdx]);
    setBuyerProblemConfirmed(false);
  };

  // Step 2 (Sales Strategy Confirmation & Direction Variants) States
  const defaultRecDirection = salesStrategyData?.directions.find(d => d.is_recommended)?.key || "persuasion";
  const [selectedDirection, setSelectedDirection] = useState<string>(defaultRecDirection);
  
  // Local state for modified strategy fields
  const [strategyFields, setStrategyFields] = useState<Record<string, string>>({});
  const [editingField, setEditingField] = useState<string | null>(null);
  const [confirmedFields, setConfirmedFields] = useState<Record<string, boolean>>({});
  const [rowAltIndices, setRowAltIndices] = useState<Record<string, number>>({});

  // Initialize strategy fields if available
  React.useEffect(() => {
    if (salesStrategyData) {
      const fields: Record<string, string> = {};
      salesStrategyData.confirmation_rows.forEach(row => {
        fields[row.field_key] = row.suggested_value;
      });
      setStrategyFields(fields);
      
      const recDir = salesStrategyData.directions.find(d => d.is_recommended)?.key || "persuasion";
      setSelectedDirection(recDir);
      setSubStep("strategy");
    }
  }, [salesStrategyData]);

  const cycleStrategyRow = (key: string, options: string[]) => {
    const currentIdx = rowAltIndices[key] || 0;
    const nextIdx = (currentIdx + 1) % (options.length + 1);
    
    setRowAltIndices(prev => ({ ...prev, [key]: nextIdx }));
    setConfirmedFields(prev => ({ ...prev, [key]: false }));
    
    if (nextIdx === 0) {
      // Back to original suggested
      const orig = salesStrategyData?.confirmation_rows.find(r => r.field_key === key)?.suggested_value || "";
      setStrategyFields(prev => ({ ...prev, [key]: orig }));
    } else {
      setStrategyFields(prev => ({ ...prev, [key]: options[nextIdx - 1] }));
    }
  };

  const handleNextStep = () => {
    const finalUnderstanding: ProductUnderstanding = {
      product_type: { value: productType, is_suggestion: !productTypeConfirmed },
      target_customer: { value: targetCustomer, is_suggestion: !targetCustomerConfirmed },
      buyer_problem: { value: buyerProblem, is_suggestion: !buyerProblemConfirmed },
      main_angle_candidates: initialData.main_angle_candidates,
      tone_candidates: initialData.tone_candidates,
      image_candidates: initialData.image_candidates,
      unknowns: initialData.unknowns,
    };
    onConfirm(finalUnderstanding);
  };

  const handleStrategySubmit = (direction = selectedDirection) => {
    if (!salesStrategyData) return;

    const selectedImages = (strategyFields.image_selection || "")
      .split(",")
      .map((name) => name.trim())
      .filter((name) => salesStrategyData.image_selection.includes(name));
    const priceValue = strategyFields.price_strategy || salesStrategyData.price_strategy;

    onConfirmSalesStrategy({
      target_customer: strategyFields.target_customer || salesStrategyData.target_customer,
      buyer_problem: salesStrategyData.buyer_problem,
      main_selling_point: strategyFields.main_selling_point || salesStrategyData.main_selling_point,
      supporting_points: salesStrategyData.supporting_points,
      tone: strategyFields.tone || salesStrategyData.tone,
      price_strategy: priceValue.includes("등록된 가격 전략") ? "N/A" : priceValue,
      image_selection: selectedImages,
      risk_notes: salesStrategyData.risk_notes,
      selected_direction: direction,
    });
  };

  return (
    <div className="space-y-6 w-full text-slate-800">
      
      {subStep === "understanding" && (
        <div className="bg-white border border-slate-200 shadow-sm p-6 rounded-2xl space-y-6">
          {/* Header */}
          <div className="border-b border-slate-100 pb-4">
            <h2 className="text-lg font-bold text-slate-900 flex items-center space-x-2">
              <span className="text-indigo-600">✨</span>
              <span>1단계: AI가 이해한 상품 분석 카드</span>
            </h2>
            <p className="text-slate-500 text-xs mt-1">
              입력하신 자료를 바탕으로 AI가 요약한 분석입니다. 잘못된 정보는 직접 수정하거나 추천 항목을 변경해보세요.
            </p>
          </div>

          {/* Row-level specifications */}
          <div className="space-y-4">
            {/* 1. Product Type */}
            <div className={`p-4 rounded-xl border transition-all duration-200 ${
              productTypeConfirmed ? "bg-emerald-50/30 border-emerald-200" : "bg-slate-50/50 border-slate-200"
            }`}>
              <div className="flex justify-between items-center mb-1.5">
                <span className="text-xs font-bold text-slate-500 block">상품 분류 (Product Type)</span>
                <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full border ${
                  productTypeConfirmed 
                    ? "bg-emerald-100/60 border-emerald-300 text-emerald-800" 
                    : "bg-indigo-50 border-indigo-155 text-indigo-700"
                }`}>
                  {productTypeConfirmed ? "확인 완료" : "AI 추천"}
                </span>
              </div>

              {isProductTypeEditing ? (
                <div className="flex space-x-2 mt-2">
                  <input
                    type="text"
                    value={productType}
                    onChange={(e) => setProductType(e.target.value)}
                    className="flex-1 bg-white border border-slate-300 rounded-lg px-3 py-1.5 text-xs text-slate-800 focus:outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500"
                  />
                  <button
                    onClick={() => {
                      setIsProductTypeEditing(false);
                      setProductTypeConfirmed(true);
                    }}
                    className="px-3.5 py-1.5 bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg text-xs font-semibold shadow-sm transition"
                  >
                    완료
                  </button>
                </div>
              ) : (
                <div className="flex justify-between items-start space-x-4">
                  <p className="text-sm font-semibold text-slate-900 mt-1">{productType}</p>
                  <div className="flex space-x-1.5 flex-shrink-0">
                    <button
                      onClick={() => setProductTypeConfirmed(true)}
                      className="px-2.5 py-1 bg-white hover:bg-slate-50 text-slate-700 rounded-lg text-xs font-semibold border border-slate-200 shadow-sm transition"
                    >
                      이걸로 하기
                    </button>
                    <button
                      onClick={cycleProductType}
                      className="px-2.5 py-1 bg-white hover:bg-slate-50 text-slate-700 rounded-lg text-xs font-semibold border border-slate-200 shadow-sm transition"
                    >
                      다른 추천
                    </button>
                    <button
                      onClick={() => setIsProductTypeEditing(true)}
                      className="px-2.5 py-1 bg-white hover:bg-slate-50 text-slate-700 rounded-lg text-xs font-semibold border border-slate-200 shadow-sm transition"
                    >
                      직접 수정
                    </button>
                  </div>
                </div>
              )}
            </div>

            {/* 2. Target Customer */}
            <div className={`p-4 rounded-xl border transition-all duration-200 ${
              targetCustomerConfirmed ? "bg-emerald-50/30 border-emerald-200" : "bg-slate-50/50 border-slate-200"
            }`}>
              <div className="flex justify-between items-center mb-1.5">
                <span className="text-xs font-bold text-slate-500 block">핵심 타겟 고객 (Target Customer)</span>
                <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full border ${
                  targetCustomerConfirmed 
                    ? "bg-emerald-100/60 border-emerald-300 text-emerald-800" 
                    : "bg-indigo-50 border-indigo-155 text-indigo-700"
                }`}>
                  {targetCustomerConfirmed ? "확인 완료" : "AI 추천"}
                </span>
              </div>

              {isTargetCustomerEditing ? (
                <div className="flex space-x-2 mt-2">
                  <textarea
                    value={targetCustomer}
                    onChange={(e) => setTargetCustomer(e.target.value)}
                    rows={2}
                    className="flex-1 bg-white border border-slate-300 rounded-lg px-3 py-1.5 text-xs text-slate-800 focus:outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500 resize-none"
                  ></textarea>
                  <button
                    onClick={() => {
                      setIsTargetCustomerEditing(false);
                      setTargetCustomerConfirmed(true);
                    }}
                    className="px-3.5 py-1.5 bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg text-xs font-semibold shadow-sm transition self-end"
                  >
                    완료
                  </button>
                </div>
              ) : (
                <div className="flex justify-between items-start space-x-4">
                  <p className="text-xs text-slate-700 leading-relaxed mt-1">{targetCustomer}</p>
                  <div className="flex space-x-1.5 flex-shrink-0">
                    <button
                      onClick={() => setTargetCustomerConfirmed(true)}
                      className="px-2.5 py-1 bg-white hover:bg-slate-50 text-slate-700 rounded-lg text-xs font-semibold border border-slate-200 shadow-sm transition"
                    >
                      이걸로 하기
                    </button>
                    <button
                      onClick={cycleTargetCustomer}
                      className="px-2.5 py-1 bg-white hover:bg-slate-50 text-slate-700 rounded-lg text-xs font-semibold border border-slate-200 shadow-sm transition"
                    >
                      다른 추천
                    </button>
                    <button
                      onClick={() => setIsTargetCustomerEditing(true)}
                      className="px-2.5 py-1 bg-white hover:bg-slate-50 text-slate-700 rounded-lg text-xs font-semibold border border-slate-200 shadow-sm transition"
                    >
                      직접 수정
                    </button>
                  </div>
                </div>
              )}
            </div>

            {/* 3. Buyer Problem */}
            <div className={`p-4 rounded-xl border transition-all duration-200 ${
              buyerProblemConfirmed ? "bg-emerald-50/30 border-emerald-200" : "bg-slate-50/50 border-slate-200"
            }`}>
              <div className="flex justify-between items-center mb-1.5">
                <span className="text-xs font-bold text-slate-500 block">해결하고자 하는 문제 (Buyer Problem)</span>
                <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full border ${
                  buyerProblemConfirmed 
                    ? "bg-emerald-100/60 border-emerald-300 text-emerald-800" 
                    : "bg-indigo-50 border-indigo-155 text-indigo-700"
                }`}>
                  {buyerProblemConfirmed ? "확인 완료" : "AI 추천"}
                </span>
              </div>

              {isBuyerProblemEditing ? (
                <div className="flex space-x-2 mt-2">
                  <textarea
                    value={buyerProblem}
                    onChange={(e) => setBuyerProblem(e.target.value)}
                    rows={2}
                    className="flex-1 bg-white border border-slate-300 rounded-lg px-3 py-1.5 text-xs text-slate-800 focus:outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500 resize-none"
                  ></textarea>
                  <button
                    onClick={() => {
                      setIsBuyerProblemEditing(false);
                      setBuyerProblemConfirmed(true);
                    }}
                    className="px-3.5 py-1.5 bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg text-xs font-semibold shadow-sm transition self-end"
                  >
                    완료
                  </button>
                </div>
              ) : (
                <div className="flex justify-between items-start space-x-4">
                  <p className="text-xs text-slate-700 leading-relaxed mt-1">{buyerProblem}</p>
                  <div className="flex space-x-1.5 flex-shrink-0">
                    <button
                      onClick={() => setBuyerProblemConfirmed(true)}
                      className="px-2.5 py-1 bg-white hover:bg-slate-50 text-slate-700 rounded-lg text-xs font-semibold border border-slate-200 shadow-sm transition"
                    >
                      이걸로 하기
                    </button>
                    <button
                      onClick={cycleBuyerProblem}
                      className="px-2.5 py-1 bg-white hover:bg-slate-50 text-slate-700 rounded-lg text-xs font-semibold border border-slate-200 shadow-sm transition"
                    >
                      다른 추천
                    </button>
                    <button
                      onClick={() => setIsBuyerProblemEditing(true)}
                      className="px-2.5 py-1 bg-white hover:bg-slate-50 text-slate-700 rounded-lg text-xs font-semibold border border-slate-200 shadow-sm transition"
                    >
                      직접 수정
                    </button>
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* Unknowns (Missing info) */}
          {initialData.unknowns.length > 0 && (
            <div className="border-t border-slate-100 pt-5 space-y-2.5">
              <h3 className="text-xs font-bold text-amber-600 uppercase tracking-wider flex items-center space-x-1.5">
                <span>⚠️</span>
                <span>추가 보완이 필요한 정보</span>
              </h3>
              <div className="bg-amber-50 border border-amber-200 rounded-xl p-3.5 space-y-1.5 text-xs text-amber-900">
                <p className="font-semibold leading-relaxed">
                  상세페이지 기획 전에 다음 부족한 정보들을 참고하세요:
                </p>
                <ul className="list-disc list-inside space-y-1 text-[11px] text-amber-800">
                  {initialData.unknowns.map((unk, idx) => (
                    <li key={idx}>{unk}</li>
                  ))}
                </ul>
              </div>
            </div>
          )}

          {/* Next Action Button */}
          <div className="border-t border-slate-100 pt-5 flex justify-end">
            <button
              onClick={handleNextStep}
              className="bg-emerald-600 hover:bg-emerald-700 text-white font-semibold px-6 py-2.5 rounded-xl text-sm shadow-sm transition flex items-center space-x-2"
            >
              <span>분석 확인 및 세일즈 전략 확인</span>
              <span>→</span>
            </button>
          </div>
        </div>
      )}

      {subStep === "strategy" && salesStrategyData && (
        <div className="space-y-6">
          {/* 2. Sales Strategy Confirmation Rows */}
          <div className="bg-white border border-slate-200 shadow-sm p-6 rounded-2xl space-y-6">
            <div className="border-b border-slate-100 pb-4">
              <h2 className="text-lg font-bold text-slate-900 flex items-center space-x-2">
                <span className="text-indigo-600">🎯</span>
                <span>AI가 이렇게 이해했어요. 맞나요?</span>
              </h2>
              <p className="text-slate-500 text-xs mt-1">
                기획에 필요한 5가지 핵심 항목입니다. 틀린 내용이 있다면 변경하거나 직접 수정해보세요.
              </p>
            </div>

            {/* Rows List */}
            <div className="space-y-4">
              {salesStrategyData.confirmation_rows.map((row) => {
                const isEditing = editingField === row.field_key;
                const isConfirmed = confirmedFields[row.field_key];
                const val = strategyFields[row.field_key] || "";
                
                return (
                  <div key={row.field_key} className={`p-4 rounded-xl border transition-all duration-200 ${
                    isConfirmed ? "bg-emerald-50/30 border-emerald-200" : "bg-slate-50/50 border-slate-200"
                  }`}>
                    <div className="flex justify-between items-center mb-1.5">
                      <span className="text-xs font-bold text-slate-500 block">{row.field_label}</span>
                      <div className="flex items-center space-x-1.5">
                        {row.confidence === "low" && !isConfirmed && (
                          <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded bg-amber-50 border border-amber-200 text-amber-800">
                            정보 부족 / 직접 확인 요망
                          </span>
                        )}
                        <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full border ${
                          isConfirmed 
                            ? "bg-emerald-100/60 border-emerald-300 text-emerald-800" 
                            : row.confidence === "high" 
                              ? "bg-indigo-50 border-indigo-200 text-indigo-700"
                              : "bg-slate-100 border-slate-200 text-slate-600"
                        }`}>
                          {isConfirmed ? "확인 완료" : `정밀도: ${row.confidence === "high" ? "높음" : row.confidence === "medium" ? "보통" : "낮음"}`}
                        </span>
                      </div>
                    </div>

                    {isEditing ? (
                      <div className="flex space-x-2 mt-2">
                        <textarea
                          value={val}
                          onChange={(e) => setStrategyFields(prev => ({ ...prev, [row.field_key]: e.target.value }))}
                          rows={2}
                          className="flex-1 bg-white border border-slate-300 rounded-lg px-3 py-1.5 text-xs text-slate-800 focus:outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500 resize-none"
                        ></textarea>
                        <button
                          onClick={() => {
                            setEditingField(null);
                            setConfirmedFields(prev => ({ ...prev, [row.field_key]: true }));
                          }}
                          className="px-3.5 py-1.5 bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg text-xs font-semibold shadow-sm transition self-end"
                        >
                          완료
                        </button>
                      </div>
                    ) : (
                      <div className="flex justify-between items-start space-x-4">
                        <p className="text-xs font-semibold text-slate-800 leading-relaxed mt-1">{val}</p>
                        <div className="flex space-x-1.5 flex-shrink-0">
                          <button
                            onClick={() => setConfirmedFields(prev => ({ ...prev, [row.field_key]: true }))}
                            className="px-2.5 py-1 bg-white hover:bg-slate-50 text-slate-700 rounded-lg text-xs font-semibold border border-slate-200 shadow-sm transition"
                          >
                            이걸로 하기
                          </button>
                          <button
                            onClick={() => cycleStrategyRow(row.field_key, row.edit_options)}
                            className="px-2.5 py-1 bg-white hover:bg-slate-50 text-slate-700 rounded-lg text-xs font-semibold border border-slate-200 shadow-sm transition"
                          >
                            다른 추천
                          </button>
                          <button
                            onClick={() => setEditingField(row.field_key)}
                            className="px-2.5 py-1 bg-white hover:bg-slate-50 text-slate-700 rounded-lg text-xs font-semibold border border-slate-200 shadow-sm transition"
                          >
                            직접 수정
                          </button>
                        </div>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>

          {/* 3. Direction Selector */}
          <div className="bg-white border border-slate-200 shadow-sm p-6 rounded-2xl space-y-6">
            <div>
              <h2 className="text-base font-bold text-slate-900">상세페이지 기획/컨셉 방향 선택</h2>
              <p className="text-slate-500 text-xs mt-1">
                AI가 추천하는 핵심 세일즈 방향입니다. 원하시는 컨셉 카드를 터치하여 선택해보세요.
              </p>
            </div>

            {/* Direction Cards Grid */}
            <div className="space-y-4">
              {salesStrategyData.directions.map((dir) => {
                const isSelected = selectedDirection === dir.key;
                
                return (
                  <div
                    key={dir.key}
                    onClick={() => setSelectedDirection(dir.key)}
                    className={`${dir.is_recommended ? "p-6" : "p-4 md:mx-6"} rounded-xl border transition-all duration-300 cursor-pointer ${
                      isSelected
                        ? "bg-emerald-50/20 border-emerald-500 shadow-sm shadow-emerald-500/5 ring-1 ring-emerald-500/20"
                        : "bg-slate-50/40 border-slate-200 hover:border-slate-350"
                    }`}
                  >
                    <div className="flex justify-between items-start mb-2">
                      <div className="flex items-center space-x-2">
                        <span className="text-base">
                          {dir.key === "persuasion" ? "💡" : dir.key === "emotional" ? "☕" : "📊"}
                        </span>
                        <h4 className="text-sm font-bold text-slate-900">{dir.name}</h4>
                        {dir.is_recommended && (
                          <span className="text-[10px] font-bold bg-emerald-100 text-emerald-800 border border-emerald-300/40 px-2 py-0.5 rounded-full">
                            ★ AI 최적 추천
                          </span>
                        )}
                      </div>
                      <div className={`w-5 h-5 rounded-full border flex items-center justify-center ${
                        isSelected ? "border-emerald-600 bg-emerald-600 text-white" : "border-slate-300 bg-white"
                      }`}>
                        {isSelected && <span className="text-[10px] font-bold">✓</span>}
                      </div>
                    </div>

                    <div className="space-y-3">
                      <div>
                        <p className="text-xs font-semibold text-indigo-700 leading-snug">
                          {dir.headline}
                        </p>
                        <p className="text-[11px] text-slate-500 leading-relaxed mt-1">
                          {dir.reason}
                        </p>
                      </div>

                      <div className="grid grid-cols-1 md:grid-cols-2 gap-3 pt-2 border-t border-slate-200/50 text-[11px]">
                        <div>
                          <span className="font-bold text-slate-500 block">타겟 소구</span>
                          <span className="text-slate-700">{dir.target}</span>
                        </div>
                        <div>
                          <span className="font-bold text-slate-500 block">추천 디자인 톤</span>
                          <span className="text-slate-700">{dir.recommended_visual_mood}</span>
                        </div>
                      </div>

                      <div className="pt-1.5">
                        <span className="text-[11px] font-bold text-slate-500 block mb-1">상세페이지 기획 단락 흐름</span>
                        <div className="flex flex-wrap gap-1">
                          {dir.section_flow.map((section, idx) => (
                            <span key={idx} className="text-[10px] bg-slate-100 text-slate-600 border border-slate-200 px-2 py-0.5 rounded">
                              {idx + 1}. {section}
                            </span>
                          ))}
                        </div>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>

            {/* Actions */}
            <div className="border-t border-slate-100 pt-5 flex justify-between items-center">
              <button
                onClick={() => setSubStep("understanding")}
                className="px-4 py-2 border border-slate-200 text-slate-600 rounded-xl text-sm font-semibold hover:bg-slate-50 transition"
              >
                이전 단계 (상품 이해)
              </button>
              
              <div className="flex space-x-2">
                <button
                  onClick={() => setEditingField("target_customer")}
                  className="px-4 py-2.5 border border-slate-200 text-slate-700 rounded-xl text-sm font-semibold hover:bg-slate-50 transition"
                >
                  조금 수정하기
                </button>
                <button
                  onClick={() => handleStrategySubmit(defaultRecDirection)}
                  className="px-4 py-2.5 border border-slate-200 text-slate-700 rounded-xl text-sm font-semibold hover:bg-slate-50 transition"
                >
                  기본 추천으로 바로 생성
                </button>
                <button
                  onClick={() => handleStrategySubmit()}
                  disabled={isSubmitting}
                  className="bg-emerald-600 hover:bg-emerald-700 text-white font-semibold px-6 py-2.5 rounded-xl text-sm shadow-sm transition flex items-center space-x-2"
                >
                  {isSubmitting ? (
                    <>
                      <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin"></div>
                      <span>기획 생성 중...</span>
                    </>
                  ) : (
                    <span>맞아요, 생성하기</span>
                  )}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

"use client";

import { useMemo, useState } from "react";
import DetailPageDocument from "@/components/DetailPageDocument";
import { detailPagePreviewFixtures } from "@/fixtures/detailPagePreview";

export default function DetailPagePreviewSandbox() {
  const [fixtureId, setFixtureId] = useState(detailPagePreviewFixtures[0].id);
  const activeFixture = useMemo(
    () =>
      detailPagePreviewFixtures.find((fixture) => fixture.id === fixtureId) ||
      detailPagePreviewFixtures[0],
    [fixtureId]
  );

  return (
    <main className="min-h-screen bg-slate-50 px-6 py-10 text-slate-950">
      <div className="mx-auto max-w-6xl">
        <div className="rounded-3xl border border-emerald-100 bg-white p-8 shadow-sm">
          <p className="text-xs font-extrabold uppercase tracking-[0.35em] text-emerald-700">
            Dev sandbox
          </p>
          <div className="mt-3 flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
            <div>
              <h1 className="text-4xl font-black tracking-tight">
                API 없는 상세페이지 미리보기
              </h1>
              <p className="mt-3 max-w-2xl text-base leading-7 text-slate-600">
                실제 OpenAI, 이미지 생성, 백엔드 API를 호출하지 않고 로컬 fixture만으로
                상세페이지 카피와 섹션 구성을 빠르게 확인하는 테스트 화면입니다.
              </p>
            </div>
            <div className="inline-flex rounded-2xl bg-emerald-50 p-1">
              {detailPagePreviewFixtures.map((fixture) => (
                <button
                  key={fixture.id}
                  type="button"
                  onClick={() => setFixtureId(fixture.id)}
                  className={`rounded-xl px-4 py-2 text-sm font-extrabold transition ${
                    activeFixture.id === fixture.id
                      ? "bg-emerald-600 text-white shadow-sm"
                      : "text-emerald-900 hover:bg-white"
                  }`}
                >
                  {fixture.label}
                </button>
              ))}
            </div>
          </div>

          <div className="mt-6 grid gap-4 lg:grid-cols-3">
            <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
              <p className="text-xs font-bold text-slate-500">현재 상품</p>
              <p className="mt-1 text-lg font-black">{activeFixture.productName}</p>
            </div>
            <div className="rounded-2xl border border-emerald-200 bg-emerald-50 p-4">
              <p className="text-xs font-bold text-emerald-700">실행 모드</p>
              <p className="mt-1 text-lg font-black text-emerald-900">
                {activeFixture.badge}
              </p>
            </div>
            <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
              <p className="text-xs font-bold text-slate-500">API 호출</p>
              <p className="mt-1 text-lg font-black">0회로 유지</p>
            </div>
          </div>

          <p className="mt-5 text-sm leading-6 text-slate-600">
            {activeFixture.description}
          </p>
        </div>

        <div className="mt-10 grid gap-8 lg:grid-cols-[minmax(0,760px)_1fr]">
          <DetailPageDocument page={activeFixture.page} assets={[]} />
          <aside className="h-fit rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
            <h2 className="text-xl font-black">테스트 체크리스트</h2>
            <ul className="mt-4 space-y-3 text-sm leading-6 text-slate-600">
              <li>• 백엔드와 이미지 생성 API를 호출하지 않는지 확인</li>
              <li>• 내부 지시문이 고객 노출 문구로 새지 않는지 확인</li>
              <li>• 상품군별 카피 구조가 자연스럽게 바뀌는지 확인</li>
              <li>• Sprint 76의 누끼/장면 합성 결과를 붙이기 전 레이아웃을 검증</li>
            </ul>
          </aside>
        </div>
      </div>
    </main>
  );
}

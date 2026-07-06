'use client';

import React, { useEffect, useMemo, useState } from 'react';
import { useParams } from 'next/navigation';

interface Section {
  section_type: string;
  title: string | null;
  body_copy: string | null;
  image_asset_id: string | null;
  sort_order: number;
}

interface PublicPageData {
  id: string;
  theme_color: string;
  font_family: string;
  external_store_url: string | null;
  config: {
    show_faq?: boolean;
    before_after_slider?: {
      enabled: boolean;
      before_image_id: string;
      after_image_id: string;
    };
    video_url?: string;
  } | null;
  sections: Section[];
  assets: Record<string, string>;
}

const BACKEND_URL = 'http://localhost:8001';
const API_URL = `${BACKEND_URL}/api/v1`;

function resolveAssetUrl(path: string): string {
  return path.startsWith('http') ? path : `${BACKEND_URL}${path}`;
}

export default function PublicLandingPage() {
  const params = useParams();
  const pageIdOrSlug = params.id as string;

  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState<PublicPageData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [openFaqIndexes, setOpenFaqIndexes] = useState<Record<number, boolean>>({});
  const [sliderPos, setSliderPos] = useState(50);
  const [galleryIndex, setGalleryIndex] = useState(0);

  const loadPublicPage = async () => {
    try {
      setLoading(true);
      setError(null);

      const res = await fetch(`${API_URL}/public/pages/${pageIdOrSlug}`);
      if (res.status === 403) {
        setError('현재 비공개로 전환된 페이지입니다.');
        return;
      }
      if (!res.ok) {
        setError('요청하신 공개 상세페이지를 찾을 수 없습니다.');
        return;
      }

      const data: PublicPageData = await res.json();
      setPage(data);
    } catch (err) {
      console.error(err);
      setError('서버 연결에 실패했습니다. 잠시 후 다시 시도해 주세요.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadPublicPage();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pageIdOrSlug]);

  const galleryImages = useMemo(() => {
    if (!page) return [];
    return Object.entries(page.assets).map(([assetId, path]) => ({
      assetId,
      url: resolveAssetUrl(path),
    }));
  }, [page]);

  const hasSlider = Boolean(
    page?.config?.before_after_slider?.enabled &&
      page.config.before_after_slider.before_image_id &&
      page.config.before_after_slider.after_image_id &&
      page.assets[page.config.before_after_slider.before_image_id] &&
      page.assets[page.config.before_after_slider.after_image_id],
  );

  const toggleFaq = (index: number) => {
    setOpenFaqIndexes(prev => ({
      ...prev,
      [index]: !prev[index],
    }));
  };

  const handleBuy = () => {
    if (!page?.external_store_url) {
      alert('아직 연결된 구매 링크가 없습니다.');
      return;
    }
    window.open(page.external_store_url, '_blank', 'noopener,noreferrer');
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-slate-50 text-slate-800 flex flex-col items-center justify-center gap-4 font-sans">
        <div className="w-10 h-10 border-4 border-emerald-500 border-t-transparent rounded-full animate-spin" />
        <p className="text-slate-500 text-sm">공개 상세페이지를 불러오는 중입니다.</p>
      </div>
    );
  }

  if (error || !page) {
    return (
      <div className="min-h-screen bg-slate-900 text-slate-100 flex flex-col items-center justify-center p-6 text-center max-w-md mx-auto gap-6 font-sans">
        <div className="text-4xl">⚠️</div>
        <h2 className="text-lg font-bold tracking-tight text-rose-400">
          {error || '페이지를 불러올 수 없습니다.'}
        </h2>
        <p className="text-slate-400 text-xs leading-relaxed">
          주소가 올바른지 확인하거나 판매자에게 발행 상태를 문의해 주세요.
        </p>
      </div>
    );
  }

  return (
    <div
      className="min-h-screen bg-[#FAFAFA] text-slate-900 flex flex-col items-center pb-24 selection:bg-slate-200"
      style={{ fontFamily: page.font_family }}
    >
      <main className="w-full max-w-[480px] bg-white min-h-screen shadow-lg border-x border-slate-100 flex flex-col overflow-x-hidden">
        <section className="p-5 border-b border-slate-100 bg-slate-50/40">
          {galleryImages.length > 0 ? (
            <div className="space-y-3" aria-label="상품 이미지 갤러리">
              <div className="relative w-full aspect-square overflow-hidden rounded-2xl bg-slate-100 border border-slate-200">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={galleryImages[galleryIndex]?.url}
                  alt={`상품 이미지 ${galleryIndex + 1}`}
                  className="w-full h-full object-cover"
                  loading="lazy"
                />
              </div>
              {galleryImages.length > 1 && (
                <div className="flex items-center justify-center gap-2">
                  {galleryImages.map((image, index) => (
                    <button
                      key={image.assetId}
                      type="button"
                      aria-label={`상품 이미지 ${index + 1} 보기`}
                      onClick={() => setGalleryIndex(index)}
                      className={`h-2 rounded-full transition-all ${
                        galleryIndex === index ? 'w-6 bg-slate-900' : 'w-2 bg-slate-300'
                      }`}
                    />
                  ))}
                </div>
              )}
            </div>
          ) : (
            <div className="rounded-2xl bg-slate-100 border border-dashed border-slate-300 p-8 text-center">
              <p className="text-sm font-bold text-slate-700">상품 이미지 준비 중</p>
              <p className="mt-2 text-xs text-slate-500">
                등록된 이미지가 없어 텍스트 중심 페이지로 표시합니다.
              </p>
            </div>
          )}
        </section>

        {page.sections.map((sec, idx) => {
          const isFaq = sec.section_type === 'faq' && page.config?.show_faq;
          const isFaqOpen = openFaqIndexes[idx] ?? false;
          const sectionImageUrl =
            sec.image_asset_id && page.assets[sec.image_asset_id]
              ? resolveAssetUrl(page.assets[sec.image_asset_id])
              : '';

          if (isFaq) {
            return (
              <div key={`${sec.section_type}-${idx}`} className="border-b border-slate-100 bg-slate-50/50">
                <button
                  type="button"
                  onClick={() => toggleFaq(idx)}
                  aria-expanded={isFaqOpen}
                  className="w-full px-6 py-4 flex items-center justify-between text-left hover:bg-slate-50 transition-colors"
                >
                  <span className="text-xs font-extrabold text-slate-800 flex items-center gap-2">
                    <span style={{ color: page.theme_color }}>Q.</span>
                    <span>{sec.title}</span>
                  </span>
                  <span
                    aria-hidden="true"
                    className={`text-slate-400 text-xs transition-transform duration-200 ${isFaqOpen ? 'rotate-180' : ''}`}
                  >
                    ▼
                  </span>
                </button>
                <div
                  className={`overflow-hidden transition-all duration-300 ${
                    isFaqOpen ? 'max-h-96 border-t border-slate-100/50 p-6' : 'max-h-0'
                  }`}
                >
                  <p className="text-xs text-slate-600 leading-relaxed whitespace-pre-line">
                    {sec.body_copy}
                  </p>
                </div>
              </div>
            );
          }

          return (
            <section
              key={`${sec.section_type}-${idx}`}
              className={`p-6 border-b border-slate-100 relative ${
                sec.section_type === 'header' ? 'text-center py-10 bg-slate-50/30' : ''
              }`}
            >
              {sec.section_type === 'header' ? (
                <div>
                  <h1 className="text-2xl font-black tracking-tight mb-4" style={{ color: page.theme_color }}>
                    {sec.title}
                  </h1>
                  <p className="text-xs text-slate-600 leading-relaxed whitespace-pre-line">
                    {sec.body_copy}
                  </p>
                </div>
              ) : (
                <div className="space-y-3">
                  <h2
                    className="text-base font-extrabold text-slate-800 border-l-4 pl-3"
                    style={{ borderColor: page.theme_color }}
                  >
                    {sec.title}
                  </h2>
                  <p className="text-xs text-slate-600 leading-relaxed whitespace-pre-line">
                    {sec.body_copy}
                  </p>
                </div>
              )}

              {sectionImageUrl && (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={sectionImageUrl}
                  alt={sec.title || '상세 섹션 이미지'}
                  className="w-full h-auto mt-4 rounded-xl shadow-sm border border-slate-100 object-cover"
                  loading="lazy"
                />
              )}

              {sec.section_type === 'features' && hasSlider && page.config?.before_after_slider && (
                <div className="mt-6 space-y-3">
                  <span className="text-[10px] uppercase font-bold tracking-wider text-slate-400 block text-center">
                    슬라이더를 움직여 전후 이미지를 비교해 보세요
                  </span>
                  <div className="relative w-full aspect-video rounded-xl border border-slate-200 overflow-hidden select-none">
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img
                      src={resolveAssetUrl(page.assets[page.config.before_after_slider.before_image_id])}
                      alt="Before"
                      className="absolute inset-0 w-full h-full object-cover"
                      loading="lazy"
                    />
                    <div className="absolute inset-0 h-full overflow-hidden" style={{ width: `${sliderPos}%` }}>
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img
                        src={resolveAssetUrl(page.assets[page.config.before_after_slider.after_image_id])}
                        alt="After"
                        className="absolute inset-0 w-[480px] max-w-none h-full object-cover"
                        loading="lazy"
                      />
                    </div>
                    <div
                      className="absolute top-0 bottom-0 w-1 bg-white shadow-md flex items-center justify-center"
                      style={{ left: `${sliderPos}%` }}
                      aria-hidden="true"
                    >
                      <div className="w-6 h-6 rounded-full bg-white border-2 border-slate-300 shadow text-[10px] text-slate-400 flex items-center justify-center">
                        ↔
                      </div>
                    </div>
                    <input
                      aria-label="전후 이미지 비교 슬라이더"
                      type="range"
                      min="0"
                      max="100"
                      value={sliderPos}
                      onChange={e => setSliderPos(Number(e.target.value))}
                      className="absolute inset-0 w-full h-full opacity-0 cursor-ew-resize z-20"
                    />
                  </div>
                </div>
              )}
            </section>
          );
        })}

        {page.config?.video_url && (
          <section className="p-6 border-b border-slate-100 space-y-3">
            <h2
              className="text-base font-extrabold text-slate-800 border-l-4 pl-3"
              style={{ borderColor: page.theme_color }}
            >
              영상으로 더 자세히 보기
            </h2>
            <div className="relative w-full aspect-video rounded-xl border border-slate-150 overflow-hidden shadow-sm">
              <iframe
                src={page.config.video_url}
                title="상품 소개 영상"
                allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
                allowFullScreen
                className="absolute inset-0 w-full h-full border-0"
              />
            </div>
          </section>
        )}
      </main>

      <footer className="w-full max-w-[480px] fixed bottom-0 z-40 bg-white/90 backdrop-blur-md border-t border-slate-100 px-4 py-3">
        <button
          type="button"
          onClick={handleBuy}
          disabled={!page.external_store_url}
          className="w-full py-3.5 text-white font-bold text-sm tracking-wide rounded-xl shadow-lg transition-transform duration-200 active:scale-95 disabled:opacity-50 disabled:cursor-not-allowed"
          style={{
            backgroundColor: page.external_store_url ? page.theme_color : '#94A3B8',
            boxShadow: page.external_store_url ? `0 10px 15px -3px ${page.theme_color}30` : undefined,
          }}
        >
          {page.external_store_url ? '구매하기' : '구매 링크 준비 중'}
        </button>
      </footer>
    </div>
  );
}

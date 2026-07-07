import type { DetailPageData } from "@/components/DetailPageDocument";

export interface DetailPagePreviewFixture {
  id: string;
  label: string;
  badge: string;
  productName: string;
  description: string;
  page: DetailPageData;
}

export const detailPagePreviewFixtures: DetailPagePreviewFixture[] = [
  {
    id: "fan",
    label: "선풍기 예시",
    badge: "fixture 데이터만 사용",
    productName: "루메나 휴대용 무선 냉각선풍기",
    description:
      "상품 링크나 실제 API 없이, 판매 카피와 HTML/CSS 그래픽 구성을 빠르게 확인하는 예시입니다.",
    page: {
      id: "dev-preview-fan",
      project_id: "dev-preview",
      theme_color: "#3f8f68",
      font_family:
        "Pretendard, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif",
      sections: [
        {
          id: "fan-hero",
          section_type: "hero",
          title: "콘센트 없이도 더운 순간 바로 꺼내 쓰는 휴대용 냉각 선풍기",
          body_copy:
            "책상, 차량, 캠핑, 침대 옆까지. 손이 닿는 곳에 두고 더운 순간 바로 시원함을 더하세요.",
          visual_kind: "html_graphic",
          visual_payload: {
            layout_variant: "benefit_cards",
            cards: [
              {
                icon_key: "🌬️",
                title: "무선 사용",
                body: "전원 위치에 덜 묶여 실내와 야외에서 가볍게 사용할 수 있습니다.",
                tone: "positive",
              },
              {
                icon_key: "🧊",
                title: "냉각 체감",
                body: "더운 순간 바람과 냉각감을 함께 기대하는 고객에게 핵심 장점을 바로 보여줍니다.",
                tone: "positive",
              },
              {
                icon_key: "👜",
                title: "휴대 중심",
                body: "차량, 사무실, 캠핑처럼 이동이 많은 상황을 자연스럽게 연결합니다.",
                tone: "muted",
              },
            ],
          },
          sort_order: 1,
        },
        {
          id: "fan-problem",
          section_type: "comparison",
          title: "선풍기는 있는데, 더위는 계속 남아있을 때",
          body_copy:
            "전원이나 설치 위치가 애매하면 시원함을 느끼기 전에 불편함이 먼저 커집니다. 휴대용 냉각 선풍기는 필요한 순간 바로 손에 잡히는 선택지가 됩니다.",
          visual_kind: "html_graphic",
          visual_payload: {
            layout_variant: "comparison_cards",
            cards: [
              {
                title: "일반 선풍기",
                body: "전원 위치와 설치 공간을 먼저 확인해야 해서 이동 중 사용이 어렵습니다.",
                tone: "muted",
              },
              {
                title: "휴대용 냉각 선풍기",
                body: "책상, 차량, 야외처럼 장소가 바뀌어도 바로 꺼내 쓸 수 있습니다.",
                tone: "positive",
              },
            ],
          },
          sort_order: 2,
        },
        {
          id: "fan-check",
          section_type: "product_information",
          title: "구매 전 꼭 확인할 내용",
          body_copy:
            "충전 방식, 사용 시간, 풍속 단계, 소음, 구성품처럼 구매 전에 확인해야 할 정보를 상세페이지 하단에서 한 번 더 정리하세요.",
          visual_kind: "html_graphic",
          visual_payload: {
            layout_variant: "spec_table",
            table_rows: [
              { label: "사용 장소", value: "책상, 차량, 침대 옆, 야외" },
              { label: "구매 전 확인", value: "충전 방식, 사용 시간, 풍속 단계, 구성품" },
              { label: "표현 기준", value: "확인된 정보만 노출하고 과장 표현은 제외" },
            ],
          },
          sort_order: 3,
        },
      ],
    },
  },
  {
    id: "beauty",
    label: "화장품 예시",
    badge: "fixture 데이터만 사용",
    productName: "저자극 진정 수분 크림",
    description:
      "제품군이 바뀌어도 같은 레이아웃 계약으로 판매 카피와 섹션 흐름을 검증합니다.",
    page: {
      id: "dev-preview-beauty",
      project_id: "dev-preview",
      theme_color: "#8f6a55",
      font_family:
        "Pretendard, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif",
      sections: [
        {
          id: "beauty-hero",
          section_type: "hero",
          title: "피부가 예민한 날에도 가볍게 시작하는 진정 루틴",
          body_copy:
            "끈적임은 줄이고 수분감은 남겨, 아침과 밤 모두 부담 없이 바르기 좋은 데일리 크림입니다.",
          visual_kind: "html_graphic",
          visual_payload: {
            layout_variant: "benefit_cards",
            cards: [
              {
                icon_key: "💧",
                title: "수분감",
                body: "건조함이 느껴지는 피부에 촉촉한 마무리감을 전달합니다.",
                tone: "positive",
              },
              {
                icon_key: "🌿",
                title: "진정 루틴",
                body: "자극받은 날에도 부담 없는 사용 장면을 먼저 보여줍니다.",
                tone: "positive",
              },
              {
                icon_key: "☁️",
                title: "가벼운 사용감",
                body: "매일 쓰는 제품답게 흡수감과 마무리감을 쉽게 설명합니다.",
                tone: "muted",
              },
            ],
          },
          sort_order: 1,
        },
        {
          id: "beauty-check",
          section_type: "guarantee",
          title: "구매 전 성분과 사용감을 함께 확인하세요",
          body_copy:
            "피부 타입, 주요 성분, 사용 순서, 향 유무처럼 구매자가 걱정하는 정보를 짧고 분명하게 정리합니다.",
          visual_kind: "html_graphic",
          visual_payload: {
            layout_variant: "spec_table",
            table_rows: [
              { label: "추천 상황", value: "건조함, 예민함, 데일리 보습" },
              { label: "확인 항목", value: "성분, 향, 제형, 사용 순서" },
              { label: "표현 기준", value: "효능 단정 대신 사용감 중심으로 설명" },
            ],
          },
          sort_order: 2,
        },
      ],
    },
  },
];

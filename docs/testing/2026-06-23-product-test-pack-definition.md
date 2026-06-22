# 테스트 팩 정의: 4대 카테고리별 가상 상품 테스트 데이터셋

본 문서는 셀폼 상세페이지 AI 파이프라인의 번역, 사실 추출, 필수 정보 검수, 금지 표현 필터링 기능을 회귀 테스트하기 위해 정상·누락·위험 시나리오별로 정의한 가상 상품 테스트 데이터셋 명세입니다.

---

## 1. 테스트 데이터셋 구조 개요

모든 테스트 케이스는 다음 스키마를 따릅니다:
- `project_id`: 테스트용 고유 식별자
- `category`: 상품 카테고리 (Fashion, Beauty, Food, Living)
- `scenario_type`: 시나리오 구분 (normal, missing_required, high_risk)
- `raw_input`: 공급처 링크 또는 입력 텍스트
- `expected_facts`: 정규화 단계에서 추출 및 검증되어야 하는 기대 속성 목록
- `expected_issues`: 품질/규제 검수 단계에서 검출되어야 하는 오류 또는 경고 목록

---

## 2. 카테고리별 세부 테스트 팩 (JSON 명세)

### 2.1 패션·잡화 (Fashion)
```json
[
  {
    "project_id": "TEST-FASHION-01-NORMAL",
    "category": "Fashion",
    "scenario_type": "normal",
    "raw_input": "상품명: 오버핏 코튼 라운드 티셔츠 / 소재: 면 100% / 색상: 블랙, 화이트, 멜란지 / 사이즈: M, L, XL / 제조국: 한국 / 세탁법: 찬물 단독 손세탁 권장",
    "expected_facts": {
      "product_name": "오버핏 코튼 라운드 티셔츠",
      "material": "면 100%",
      "colors": ["블랙", "화이트", "멜란지"],
      "sizes": ["M", "L", "XL"],
      "origin": "대한민국"
    },
    "expected_issues": []
  },
  {
    "project_id": "TEST-FASHION-02-MISSING",
    "category": "Fashion",
    "scenario_type": "missing_required",
    "raw_input": "상품명: 가죽 로퍼 / 색상: 브라운 / 사이즈: 250~280",
    "expected_facts": {
      "product_name": "가죽 로퍼",
      "colors": ["브라운"],
      "sizes": ["250", "280"]
    },
    "expected_issues": [
      {
        "severity": "Major",
        "rule": "소재 정보 누락",
        "message": "패션 카테고리의 필수 고시 사항인 섬유의 조성/혼용률(소재) 정보가 누락되었습니다."
      }
    ]
  }
]
```

### 2.2 뷰티·화장품 (Beauty)
```json
[
  {
    "project_id": "TEST-BEAUTY-01-NORMAL",
    "category": "Beauty",
    "scenario_type": "normal",
    "raw_input": "상품명: 히알루론산 수분 크림 / 용량: 50ml / 주요성분: 히알루론산 5,000ppm, 판테놀 / 효능: 피부 수분 공급 및 장벽 개선 도움 / 식약처 보고완료 주름개선 기능성 화장품 / 사용시 주의사항 기재됨",
    "expected_facts": {
      "product_name": "히알루론산 수분 크림",
      "volume": "50ml",
      "key_ingredients": ["히알루론산", "판테놀"],
      "functional_type": "주름개선 기능성"
    },
    "expected_issues": []
  },
  {
    "project_id": "TEST-BEAUTY-02-RISK",
    "category": "Beauty",
    "scenario_type": "high_risk",
    "raw_input": "상품명: 티트리 진정 에센스 / 이 에센스는 아토피 환자들의 가려움증을 완벽히 치료하고, 여드름 균을 100% 사멸시켜 피부 세포를 재생해줍니다.",
    "expected_facts": {
      "product_name": "티트리 진정 에센스"
    },
    "expected_issues": [
      {
        "severity": "Blocker",
        "rule": "의학적 효능 오인 표현 금지",
        "message": "'아토피 치료', '여드름 균 사멸' 등 질병 치료/예방 관련 의학적 오인 표현이 감지되었습니다."
      },
      {
        "severity": "Blocker",
        "rule": "화장품 절대적 표현 사용 금지",
        "message": "'완벽히 치료', '100% 사멸'과 같은 효능 보장성 절대적 표현은 사용할 수 없습니다."
      },
      {
        "severity": "Blocker",
        "rule": "화장품 재생 표현 사용 금지",
        "message": "화장품법상 금지된 의약품 오인성 '세포 재생' 표현이 사용되었습니다."
      }
    ]
  }
]
```

### 2.3 식품·건강기능식품 (Food)
```json
[
  {
    "project_id": "TEST-FOOD-01-NORMAL",
    "category": "Food",
    "scenario_type": "normal",
    "raw_input": "상품명: 국내산 유기농 사과즙 / 식품유형: 과채주스 / 용량: 100ml x 30포 / 원재료: 유기농 사과 99.9%(국산), 비타민C / 알레르기: 메밀, 밀 혼유 시설 제조 / 보관법: 실온 보관",
    "expected_facts": {
      "product_name": "국내산 유기농 사과즙",
      "food_type": "과채주스",
      "ingredients": "유기농 사과 99.9%(국산), 비타민C",
      "allergens": ["메밀", "밀"]
    },
    "expected_issues": []
  },
  {
    "project_id": "TEST-FOOD-02-RISK",
    "category": "Food",
    "scenario_type": "high_risk",
    "raw_input": "상품명: 빨간양파즙 / 고혈압과 당뇨 환자에게 특효약이며, 암 예방과 피로회복에 직빵인 만병통치약 양파즙입니다.",
    "expected_facts": {
      "product_name": "빨간양파즙"
    },
    "expected_issues": [
      {
        "severity": "Blocker",
        "rule": "식품 의약품 오인 광고 금지",
        "message": "'고혈압 당뇨 특효약', '암 예방' 등 식품을 질병 치료용 의약품으로 혼동케 하는 표현이 사용되었습니다."
      },
      {
        "severity": "Major",
        "rule": "식품 효능 과장 금지",
        "message": "'피로회복 직빵', '만병통치약' 등 객관적 근거 없는 기만적 표현이 감지되었습니다."
      }
    ]
  }
]
```

### 2.4 생활·리빙 (Living)
```json
[
  {
    "project_id": "TEST-LIVING-01-NORMAL",
    "category": "Living",
    "scenario_type": "normal",
    "raw_input": "상품명: 원목 접이식 노트북 테이블 / 규격: 가로 60cm, 세로 40cm, 높이 28cm / 재질: 대나무 원목, 스틸 / KC안전인증번호: SU07123-21001 / 수입판매원: (주)리빙앤코",
    "expected_facts": {
      "product_name": "원목 접이식 노트북 테이블",
      "dimensions": "60cm x 40cm x 28cm",
      "materials": ["대나무 원목", "스틸"],
      "kc_cert_number": "SU07123-21001"
    },
    "expected_issues": []
  },
  {
    "project_id": "TEST-LIVING-02-MISSING",
    "category": "Living",
    "scenario_type": "missing_required",
    "raw_input": "상품명: 아동용 캐릭터 수저 세트 / 재질: 스테인리스 / 규격: 15cm / 원산지: 중국",
    "expected_facts": {
      "product_name": "아동용 캐릭터 수저 세트",
      "materials": ["스테인리스"],
      "dimensions": "15cm"
    },
    "expected_issues": [
      {
        "severity": "Blocker",
        "rule": "어린이제품 KC 인증번호 누락",
        "message": "아동용 제품은 어린이제품 안전 특별법에 따른 KC안전인증 또는 적합성인증 번호 표기가 필수적이나 누락되었습니다."
      }
    ]
  }
]
```

---

## 3. 테스트 팩 활용 및 검증 방법

1. **자동화 테스트 연동 (Sprint 7 반영)**
   - 백엔드 테스트 코드(`tests/test_compliance_engine.py`)가 위 JSON 테스트 데이터를 파싱하여, 추출 모듈과 검수 필터 모듈을 순차 호출하도록 구성한다.
   - `high_risk` 및 `missing_required` 데이터 입력 시, 실제로 기대했던 `expected_issues` 목록(동일한 규칙 및 심각도)이 정확하게 탐지되는지 단언(Assert)하여 확인한다.
2. **품질 모니터링 대시보드 검증**
   - 개발 프로세스 중 새로운 AI 프롬프트가 적용될 때마다 위 테스트 팩을 수행하여 오탐율(False Positive) 및 미탐율(False Negative)을 측정하는 회귀 테스트 기준으로 활용한다.

## 4. Sprint 0 보강 시나리오

각 카테고리에 정상·필수 정보 누락·위험 표현이 모두 있어야 카테고리 엔진의 필수 필드와 검수 규칙을 함께 검증할 수 있다. 아래 네 시나리오를 추가해 총 12개 케이스로 운영한다.

| 프로젝트 ID | 카테고리 | 시나리오 | 기대 이슈 |
|---|---|---|---|
| TEST-FASHION-03-RISK | Fashion | “모든 피부에 100% 안전한 천연가죽”처럼 근거 없는 절대·안전 표현 | 과장·근거 없는 안전성 표현 경고 |
| TEST-BEAUTY-03-MISSING | Beauty | 용량만 있고 전성분·사용상 주의사항·사용기한 정보가 없음 | 필수 고시 정보 누락 차단 |
| TEST-FOOD-03-MISSING | Food | 원재료·알레르기·보관법이 없는 식품 | 필수 표시 정보 누락 차단 |
| TEST-LIVING-03-RISK | Living | 근거·호환 목록 없이 “어떤 제품에도 100% 호환, 절대 파손 없음” | 안전·호환성 단정 표현 경고 |

### 4.1 추가 JSON fixture

```json
[
  {
    "project_id": "TEST-FASHION-03-RISK",
    "category": "Fashion",
    "scenario_type": "high_risk",
    "raw_input": "상품명: 천연가죽 지갑 / 모든 피부에 100% 안전하고 절대 변색되지 않습니다.",
    "expected_facts": {"product_name": "천연가죽 지갑"},
    "expected_issues": [{"severity": "Major", "rule": "근거 없는 절대·안전 표현", "message": "100% 안전, 절대 변색 등의 근거 없는 단정 표현이 감지되었습니다."}]
  },
  {
    "project_id": "TEST-BEAUTY-03-MISSING",
    "category": "Beauty",
    "scenario_type": "missing_required",
    "raw_input": "상품명: 데일리 수분 로션 / 용량: 200ml",
    "expected_facts": {"product_name": "데일리 수분 로션", "volume": "200ml"},
    "expected_issues": [{"severity": "Blocker", "rule": "화장품 필수 고시 정보 누락", "message": "전성분, 사용상 주의사항, 사용기한 또는 제조번호 정보가 누락되었습니다."}]
  },
  {
    "project_id": "TEST-FOOD-03-MISSING",
    "category": "Food",
    "scenario_type": "missing_required",
    "raw_input": "상품명: 과일 혼합 젤리 / 용량: 300g",
    "expected_facts": {"product_name": "과일 혼합 젤리", "volume": "300g"},
    "expected_issues": [{"severity": "Blocker", "rule": "식품 필수 표시 정보 누락", "message": "원재료, 알레르기 정보, 보관방법이 누락되었습니다."}]
  },
  {
    "project_id": "TEST-LIVING-03-RISK",
    "category": "Living",
    "scenario_type": "high_risk",
    "raw_input": "상품명: 범용 휴대폰 거치대 / 어떤 제품에도 100% 호환되고 절대 파손되지 않습니다.",
    "expected_facts": {"product_name": "범용 휴대폰 거치대"},
    "expected_issues": [{"severity": "Major", "rule": "안전·호환성 단정 표현", "message": "호환 목록과 근거 없이 100% 호환 또는 절대 파손을 단정할 수 없습니다."}]
  }
]
```

Sprint 3의 모델 평가는 12개 케이스 전부를 사용한다.

import pytest
from src.services.compliance import check_compliance, ComplianceIssue
from src.services.compliance_checker import build_qa_warning_issue

# 12개 테스트 팩 데이터셋 정의
TEST_CASES = [
    # Fashion
    {
        "project_id": "TEST-FASHION-01-NORMAL",
        "category": "Fashion",
        "product_name": "오버핏 코튼 라운드 티셔츠",
        "raw_input": "소재: 면 100% / 색상: 블랙, 화이트, 멜란지 / 사이즈: M, L, XL / 제조국: 한국 / 세탁법: 찬물 단독 손세탁 권장",
        "expected_issues": []
    },
    {
        "project_id": "TEST-FASHION-02-MISSING",
        "category": "Fashion",
        "product_name": "가죽 로퍼",
        "raw_input": "색상: 브라운 / 사이즈: 250~280",
        "expected_issues": [
            {"severity": "Major", "rule": "소재 정보 누락"}
        ]
    },
    {
        "project_id": "TEST-FASHION-03-RISK",
        "category": "Fashion",
        "product_name": "천연가죽 지갑",
        "raw_input": "모든 피부에 100% 안전하고 절대 변색되지 않습니다.",
        "expected_issues": [
            {"severity": "Major", "rule": "근거 없는 절대·안전 표현"}
        ]
    },
    # Beauty
    {
        "project_id": "TEST-BEAUTY-01-NORMAL",
        "category": "Beauty",
        "product_name": "히알루론산 수분 크림",
        "raw_input": "용량: 50ml / 주요성분: 히알루론산 5,000ppm, 판테놀 / 효능: 피부 수분 공급 및 장벽 개선 도움 / 식약처 보고완료 주름개선 기능성 화장품 / 사용시 주의사항 기재됨",
        "expected_issues": []
    },
    {
        "project_id": "TEST-BEAUTY-02-RISK",
        "category": "Beauty",
        "product_name": "티트리 진정 에센스",
        "raw_input": "이 에센스는 아토피 환자들의 가려움증을 완벽히 치료하고, 여드름 균을 100% 사멸시켜 피부 세포를 재생해줍니다.",
        "expected_issues": [
            {"severity": "Blocker", "rule": "의학적 효능 오인 표현 금지"},
            {"severity": "Blocker", "rule": "화장품 절대적 표현 사용 금지"},
            {"severity": "Blocker", "rule": "화장품 재생 표현 사용 금지"}
        ]
    },
    {
        "project_id": "TEST-BEAUTY-03-MISSING",
        "category": "Beauty",
        "product_name": "데일리 수분 로션",
        "raw_input": "용량: 200ml",
        "expected_issues": [
            {"severity": "Blocker", "rule": "화장품 필수 고시 정보 누락"}
        ]
    },
    # Food
    {
        "project_id": "TEST-FOOD-01-NORMAL",
        "category": "Food",
        "product_name": "국내산 유기농 사과즙",
        "raw_input": "식품유형: 과채주스 / 용량: 100ml x 30포 / 원재료: 유기농 사과 99.9%(국산), 비타민C / 알레르기: 메밀, 밀 혼유 시설 제조 / 보관법: 실온 보관",
        "expected_issues": []
    },
    {
        "project_id": "TEST-FOOD-02-RISK",
        "category": "Food",
        "product_name": "빨간양파즙",
        "raw_input": "고혈압과 당뇨 환자에게 특효약이며, 암 예방과 피로회복에 직빵인 만병통치약 양파즙입니다.",
        "expected_issues": [
            {"severity": "Blocker", "rule": "식품 의약품 오인 광고 금지"},
            {"severity": "Major", "rule": "식품 효능 과장 금지"}
        ]
    },
    {
        "project_id": "TEST-FOOD-03-MISSING",
        "category": "Food",
        "product_name": "과일 혼합 젤리",
        "raw_input": "용량: 300g",
        "expected_issues": [
            {"severity": "Blocker", "rule": "식품 필수 표시 정보 누락"}
        ]
    },
    # Living
    {
        "project_id": "TEST-LIVING-01-NORMAL",
        "category": "Living",
        "product_name": "원목 접이식 노트북 테이블",
        "raw_input": "규격: 가로 60cm, 세로 40cm, 높이 28cm / 재질: 대나무 원목, 스틸 / KC안전인증번호: SU07123-21001 / 수입판매원: (주)리빙앤코",
        "expected_issues": []
    },
    {
        "project_id": "TEST-LIVING-02-MISSING",
        "category": "Living",
        "product_name": "아동용 캐릭터 수저 세트",
        "raw_input": "재질: 스테인리스 / 규격: 15cm / 원산지: 중국",
        "expected_issues": [
            {"severity": "Blocker", "rule": "어린이제품 KC 인증번호 누락"}
        ]
    },
    {
        "project_id": "TEST-LIVING-03-RISK",
        "category": "Living",
        "product_name": "범용 휴대폰 거치대",
        "raw_input": "어떤 제품에도 100% 호환되고 절대 파손되지 않습니다.",
        "expected_issues": [
            {"severity": "Major", "rule": "안전·호환성 단정 표현"}
        ]
    }
]

@pytest.mark.parametrize("case", TEST_CASES)
def test_compliance_rules(case):
    category = case["category"]
    product_name = case["product_name"]
    raw_input = case["raw_input"]
    expected_issues = case["expected_issues"]

    # 검수 엔진 호출
    issues = check_compliance(
        category=category,
        product_name=product_name,
        raw_input=raw_input
    )

    # 개수 확인
    assert len(issues) == len(expected_issues), f"테스트 케이스 {case['project_id']} 실패: 검출 개수 불일치"

    # 세부 룰 확인
    for exp in expected_issues:
        matched = False
        for issue in issues:
            if issue.severity == exp["severity"] and issue.rule == exp["rule"]:
                matched = True
                break
        assert matched, f"테스트 케이스 {case['project_id']} 실패: 기대한 이슈(severity={exp['severity']}, rule={exp['rule']})가 검출되지 않음."


def test_build_qa_warning_issue_accepts_string_warning():
    assert build_qa_warning_issue("상품 이미지 정체성을 확인해 주세요.") == {
        "severity": "Blocker",
        "rule": "IMAGE_QUALITY_CHECK",
        "message": "상품 이미지 정체성을 확인해 주세요.",
        "section_id": None,
    }


def test_build_qa_warning_issue_preserves_structured_warning():
    assert build_qa_warning_issue(
        {
            "code": "REQUIRED_IMAGE_MISSING",
            "message": "hero 이미지가 필요합니다.",
            "section_id": "hero",
        }
    ) == {
        "severity": "Blocker",
        "rule": "REQUIRED_IMAGE_MISSING",
        "message": "hero 이미지가 필요합니다.",
        "section_id": "hero",
    }

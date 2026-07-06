from src.services.bulk_fact_parser import parse_bulk_fact_text


def test_parse_bulk_fact_text_splits_lines_and_colon_specs():
    text = '''
    모델명: FAN JET ULTRA
    배터리: 4,800mAh
    최대 18시간 무선 사용 가능
    USB-C 충전 지원
    '''

    facts = parse_bulk_fact_text(text)

    assert "모델명: FAN JET ULTRA" in facts
    assert "배터리: 4,800mAh" in facts
    assert "최대 18시간 무선 사용 가능" in facts
    assert "USB-C 충전 지원" in facts


def test_parse_bulk_fact_text_filters_common_commerce_noise_and_duplicates():
    text = '''
    1. 모델명: FAN JET ULTRA
    2. 배터리: 4,800mAh
    무료배송
    구매후기 1,234개
    2. 배터리: 4,800mAh
    쿠팡 추천 상품
    최대 18시간 무선 사용 가능
    '''

    facts = parse_bulk_fact_text(text)

    assert facts == [
        "모델명: FAN JET ULTRA",
        "배터리: 4,800mAh",
        "최대 18시간 무선 사용 가능",
    ]

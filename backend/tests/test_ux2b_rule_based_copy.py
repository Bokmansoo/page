from src.services.rule_based_copy_service import build_rule_based_copy, display_label, unsupported_claims


def test_rule_copy_uses_korean_fact_labels_and_only_fact_values():
    copy = build_rule_based_copy(
        "경추 마사지 베개",
        category="리빙·소형 가전",
        facts=[
            {"id": "f1", "field_key": "battery_capacity", "normalized_value": "2000", "normalized_unit": "mAh"},
            {"id": "f2", "field_key": "rated_power", "normalized_value": "8", "normalized_unit": "W"},
            {"id": "f3", "field_key": "rated_input", "normalized_value": "DC 5V 2A"},
        ],
    )

    assert copy["hero_title"] == "목과 어깨 사용을 고려한 경추 마사지 베개"
    assert copy["feature_1_title"] == "배터리 용량"
    assert copy["feature_1_body"] == "배터리 용량은 2000mAh입니다."
    assert copy["usage_title"] == "전원·사용 정보 확인"
    assert "battery_capacity" not in " ".join(value for value in copy.values() if isinstance(value, str))
    assert "피로 회복" not in " ".join(value for value in copy.values() if isinstance(value, str))


def test_rule_copy_does_not_invent_charging_or_components():
    copy = build_rule_based_copy(
        "마사지기",
        facts=[{"id": "f1", "field_key": "product_size", "normalized_value": "40 × 17 × 15", "normalized_unit": "cm"}],
    )

    assert copy["usage_title"] == "사용 전 안내"
    assert "충전식" not in copy["usage_body"]
    assert copy["details_title"] == "제품 사양과 옵션 확인"


def test_display_and_claim_guard():
    assert display_label("rated_input") == "정격 입력"
    assert unsupported_claims("통증 완화와 무상 A/S를 제공합니다") == ["통증 완화", "무상 a/s"]
    assert unsupported_claims("안전한 치료 기기이며 보증을 제공합니다") == ["안전", "치료", "보증"]


def test_plain_english_words_do_not_trigger_the_as_claim_guard():
    assert unsupported_claims("Neck massage pillow") == []


def test_scope_model_and_unknown_key_never_leak_internal_field_names():
    copy = build_rule_based_copy(
        "마사지기",
        facts=[
            {"id": "body", "field_key": "product_size", "value": "40 × 17 × 15", "unit": "cm", "scope": "product", "model_option": "YL-T02"},
            {"id": "carton", "field_key": "product_size", "value": "53 × 41.5 × 32", "unit": "cm", "scope": "master_carton", "model_option": "YL-T02"},
            {"id": "unknown", "field_key": "heating_mode", "value": "3단계"},
        ],
    )

    assert copy["feature_1_title"] == "제품 크기 · YL-T02"
    assert copy["feature_2_title"] == "외박스 크기 · YL-T02"
    assert copy["feature_3_title"] == "확인된 상품 정보"
    assert "heating mode" not in " ".join(value for value in copy.values() if isinstance(value, str))
    assert copy["section_fact_ids"]["feature_2"] == ["carton"]


def test_unverified_seller_claim_is_not_reused_as_hero_copy():
    copy = build_rule_based_copy("마사지기", description="KC 인증 완료로 통증 완화에 도움")

    assert copy["hero_subtitle"] == "판매자가 확인한 제품 사양을 한눈에 정리했습니다."
    assert "kc 인증" in unsupported_claims("KC 인증 완료")


def test_numeric_description_stays_out_of_unlinked_hero_copy_and_caution_is_linked():
    copy = build_rule_based_copy(
        "마사지기",
        description="배터리 2000mAh, 10분 사용",
        facts=[{"id": "caution-1", "field_key": "cautions", "value": "사용 전 사용 설명서를 확인해 주세요."}],
    )

    assert copy["hero_subtitle"] == "판매자가 확인한 제품 사양을 한눈에 정리했습니다."
    assert "사용 설명서" in copy["details_body"]
    assert copy["section_fact_ids"]["details_components"] == ["caution-1"]

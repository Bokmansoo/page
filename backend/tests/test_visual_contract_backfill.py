import pytest
from src.db.models import Asset, Brand, PageSection, ProductFact, ProductPage, ProductProject, User, Workspace
from src.services.visual_contract_backfill import backfill_page_visuals


@pytest.fixture
def db_session_with_project(db_session):
    user = User(id="backfill-user", email="backfill@test.com", name="Backfill User")
    workspace = Workspace(id="backfill-ws", name="Backfill WS", owner_id=user.id)
    brand = Brand(id="backfill-brand", workspace_id=workspace.id, name="Backfill Brand")
    project = ProductProject(
        id="legacy-project",
        workspace_id=workspace.id,
        brand_id=brand.id,
        name="Legacy page",
    )
    page = ProductPage(id="legacy-page", project_id=project.id)
    sections = [
        PageSection(page_id=page.id, section_type="hero", image_asset_id="hero-asset", sort_order=0),
        PageSection(page_id=page.id, section_type="comparison", image_asset_id=None, sort_order=1),
        PageSection(page_id=page.id, section_type="detail_1", image_asset_id=None, sort_order=2),
        PageSection(page_id=page.id, section_type="detail_2", image_asset_id="detail-asset", sort_order=3),
        PageSection(page_id=page.id, section_type="guarantee", image_asset_id=None, sort_order=4),
    ]
    confirmed_fact = ProductFact(
        project_id=project.id,
        fact_text="Confirmed product information",
        source_text="Verified seller-provided product information",
        verification_status="confirmed",
    )
    db_session.add_all([user, workspace, brand, project, page, *sections, confirmed_fact])
    db_session.commit()
    return db_session, project, page


def test_backfill_maps_images_and_html_graphics(db_session_with_project):
    db_session, project, page = db_session_with_project
    report = backfill_page_visuals(db_session, project.id)
    assert report.updated == 5

    kinds = [section.visual_kind for section in page.sections]
    assert kinds == ["image", "html_graphic", "html_graphic", "image", "html_graphic"]

    # Idempotent: second call does nothing
    second = backfill_page_visuals(db_session, project.id)
    assert second.updated == 0


def test_backfill_skips_already_backfilled(db_session_with_project):
    db_session, project, page = db_session_with_project
    # First pass
    backfill_page_visuals(db_session, project.id)
    # Mark one section as already having a visual_kind
    page.sections[0].visual_kind = "image"
    db_session.commit()

    report = backfill_page_visuals(db_session, project.id)
    # All sections already have visual_kind, so 0 updates
    assert report.updated == 0


def test_backfill_uses_confirmed_facts_for_html(db_session_with_project):
    db_session, project, page = db_session_with_project
    db_session.add(
        ProductFact(
            project_id=project.id,
            fact_text="무선으로 사용 가능",
            source_text="제품 설명서",
            verification_status="confirmed",
        )
    )
    db_session.commit()

    report = backfill_page_visuals(db_session, project.id)
    assert report.updated == 5

    comparison = next(s for s in page.sections if s.section_type == "comparison")
    assert comparison.visual_kind == "html_graphic"
    assert comparison.visual_payload["layout_variant"] == "comparison_cards"
    assert any(card["title"] == "무선으로 사용 가능" for card in comparison.visual_payload["cards"])


def test_backfill_fills_incomplete_comparison_cards(db_session_with_project):
    db_session, project, page = db_session_with_project
    # First fully backfill all sections
    backfill_page_visuals(db_session, project.id)
    # Then break one section's payload
    comparison = next(s for s in page.sections if s.section_type == "comparison")
    comparison.visual_payload = {"layout_variant": "comparison_cards"}  # no cards
    db_session.commit()

    report = backfill_page_visuals(db_session, project.id)
    assert report.updated == 1
    db_session.refresh(comparison)
    assert comparison.visual_payload.get("cards") is not None
    assert len(comparison.visual_payload["cards"]) > 0


def test_backfill_fills_incomplete_benefit_cards(db_session_with_project):
    db_session, project, page = db_session_with_project
    backfill_page_visuals(db_session, project.id)
    detail = next(s for s in page.sections if s.section_type == "detail_1")
    detail.visual_payload = {"layout_variant": "benefit_cards"}  # no cards
    db_session.commit()

    report = backfill_page_visuals(db_session, project.id)
    assert report.updated == 1
    db_session.refresh(detail)
    assert detail.visual_payload.get("cards") is not None
    assert len(detail.visual_payload["cards"]) > 0


def test_backfill_fills_incomplete_spec_table(db_session_with_project):
    db_session, project, page = db_session_with_project
    backfill_page_visuals(db_session, project.id)
    guarantee = next(s for s in page.sections if s.section_type == "guarantee")
    guarantee.visual_payload = {"layout_variant": "spec_table"}  # no table_rows
    db_session.commit()

    report = backfill_page_visuals(db_session, project.id)
    assert report.updated == 1
    db_session.refresh(guarantee)
    assert guarantee.visual_payload.get("table_rows") is not None
    assert len(guarantee.visual_payload["table_rows"]) > 0


def test_backfill_does_not_overwrite_complete_payload(db_session_with_project):
    db_session, project, page = db_session_with_project
    backfill_page_visuals(db_session, project.id)
    comparison = next(s for s in page.sections if s.section_type == "comparison")
    original_cards = list(comparison.visual_payload.get("cards", []))
    db_session.commit()

    report = backfill_page_visuals(db_session, project.id)
    assert report.updated == 0, "Should not overwrite complete payload"
    assert comparison.visual_payload["cards"] == original_cards


def test_backfill_hides_graphic_section_when_no_confirmed_facts(db_session_with_project):
    db_session, project, page = db_session_with_project
    db_session.query(ProductFact).filter(ProductFact.project_id == project.id).delete()
    db_session.commit()

    backfill_page_visuals(db_session, project.id)

    comparison = next(s for s in page.sections if s.section_type == "comparison")
    assert comparison.is_visible is False
    assert comparison.visual_kind is None
    seller_checklist = next(s for s in page.sections if s.section_type == "pre_purchase")
    assert seller_checklist.is_visible is True
    assert seller_checklist.visual_payload["layout_variant"] == "checklist"
    assert seller_checklist.visual_payload["items"][0]["kind"] == "seller_action"
    assert seller_checklist.visual_payload["items"][0]["source_fact_ids"] == []

    # When a seller later supplies confirmed facts, the previously automatic
    # checklist is no longer relevant and the section becomes visible again.
    db_session.add(
        ProductFact(
            project_id=project.id,
            fact_text="이 상품의 무게는 260g입니다.",
            source_text="260g",
            verification_status="confirmed",
        )
    )
    db_session.commit()
    backfill_page_visuals(db_session, project.id)
    db_session.refresh(comparison)
    db_session.refresh(seller_checklist)

    assert comparison.is_visible is True
    assert seller_checklist.is_visible is False


def test_backfill_maps_product_info_to_grounded_spec_table(db_session_with_project):
    db_session, project, page = db_session_with_project
    product_info = PageSection(page_id=page.id, section_type="product_info", sort_order=10)
    db_session.add(product_info)
    db_session.commit()

    backfill_page_visuals(db_session, project.id)
    db_session.refresh(product_info)

    assert product_info.visual_kind == "html_graphic"
    assert product_info.visual_payload["layout_variant"] == "spec_table"
    assert product_info.visual_payload["table_rows"][0]["verification_status"] == "confirmed"


def test_backfill_uses_numeric_highlights_only_for_confirmed_numeric_facts(db_session_with_project):
    db_session, project, page = db_session_with_project
    db_session.add(
        ProductFact(
            project_id=project.id,
            fact_text="최대 40분 사용 가능",
            source_text="연속 사용 시간은 최대 40분입니다.",
            verification_status="confirmed",
        )
    )
    summary = PageSection(page_id=page.id, section_type="benefits_summary", sort_order=11)
    db_session.add(summary)
    db_session.commit()

    backfill_page_visuals(db_session, project.id)
    db_session.refresh(summary)

    assert summary.visual_payload["layout_variant"] == "numeric_highlights"
    assert summary.visual_payload["highlights"][0]["value"] == "40분"
    assert summary.visual_payload["highlights"][0]["source_fact_ids"]


def test_backfill_rewrites_ambiguous_hero_numeric_list_with_labeled_units(db_session_with_project):
    db_session, project, page = db_session_with_project
    hero = next(section for section in page.sections if section.section_type == "hero")
    hero.body_copy = "- 260g, 800mAh, 10\n- 언제 어디서나 편리하게 사용하세요."
    db_session.add_all(
        [
            ProductFact(
                project_id=project.id,
                fact_text="이 상품의 무게는 260g입니다.",
                source_text="260g",
                verification_status="confirmed",
                extraction_source="seller_input",
            ),
            ProductFact(
                project_id=project.id,
                fact_text="이 상품의 배터리 용량은 800mAh입니다.",
                source_text="800mAh",
                verification_status="confirmed",
                extraction_source="seller_input",
            ),
            ProductFact(
                project_id=project.id,
                fact_text="이 상품의 사용 시간은 10분입니다.",
                source_text="10분",
                verification_status="confirmed",
            ),
        ]
    )
    db_session.commit()

    backfill_page_visuals(db_session, project.id)
    db_session.refresh(hero)

    assert hero.body_copy.splitlines()[0] == "- 무게 260g · 배터리 800mAh · 사용 시간 10분"


def test_backfill_hides_repeated_narrative_cards_when_only_numeric_seller_specs_exist(db_session_with_project):
    db_session, project, page = db_session_with_project
    db_session.query(ProductFact).filter(ProductFact.project_id == project.id).delete()
    summary = PageSection(page_id=page.id, section_type="benefits_summary", sort_order=10)
    product_info = PageSection(page_id=page.id, section_type="product_info", sort_order=11)
    db_session.add_all(
        [
            summary,
            product_info,
            ProductFact(
                project_id=project.id,
                fact_text="이 상품의 무게는 260g입니다.",
                source_text="260g",
                verification_status="confirmed",
                extraction_source="seller_input",
            ),
            ProductFact(
                project_id=project.id,
                fact_text="이 상품의 사용 시간은 10분입니다.",
                source_text="10분",
                verification_status="confirmed",
                extraction_source="seller_input",
            ),
        ]
    )
    db_session.commit()

    backfill_page_visuals(db_session, project.id)
    db_session.refresh(summary)
    db_session.refresh(product_info)

    narrative_sections = [
        section
        for section in page.sections
        if section.section_type in {"comparison", "detail_1"}
    ]
    assert all(section.is_visible is False for section in narrative_sections)
    assert summary.is_visible is True
    assert summary.visual_payload["layout_variant"] == "numeric_highlights"
    assert product_info.is_visible is True
    assert product_info.visual_payload["layout_variant"] == "spec_table"


def test_backfill_replaces_repeated_product_photo_with_grounded_html_graphic(db_session_with_project):
    db_session, project, page = db_session_with_project
    fact = db_session.query(ProductFact).filter(ProductFact.project_id == project.id).first()
    repeated_photo = Asset(
        id="repeated-main-photo",
        project_id=project.id,
        source_type="uploaded",
        filename="main-product.jpg",
        file_path="https://cdn.example.com/main-product.jpg",
        mime_type="image/jpeg",
        file_size=1,
        asset_role="product_main",
    )
    detail = next(s for s in page.sections if s.section_type == "detail_1")
    detail.image_asset_id = repeated_photo.id
    detail.visual_kind = "image"
    detail.visual_payload = {"layout_variant": "image_text"}
    detail.associated_fact_ids = [fact.id]
    db_session.add(repeated_photo)
    db_session.commit()

    backfill_page_visuals(db_session, project.id)
    db_session.refresh(detail)

    assert detail.image_asset_id is None
    assert detail.visual_kind == "html_graphic"
    assert detail.visual_payload["layout_variant"] == "benefit_cards"
    assert detail.visual_payload["cards"][0]["source_fact_ids"] == [fact.id]


def test_backfill_returns_zero_for_missing_page(db_session_with_project):
    db_session, project, page = db_session_with_project
    report = backfill_page_visuals(db_session, "nonexistent")
    assert report.updated == 0


def test_spec_table_uses_canonical_values_not_supplier_ocr(db_session_with_project):
    db_session, project, page = db_session_with_project
    db_session.query(ProductFact).filter(ProductFact.project_id == project.id).delete()
    fact = ProductFact(
        project_id=project.id,
        fact_text="사용 가능 시간: 2시간",
        field_key="total_use_time",
        normalized_value="2",
        normalized_unit="시간",
        source_text="使用时间：2小时",
        verification_status="seller_confirmed",
    )
    section = PageSection(
        page_id=page.id,
        section_type="specifications",
        associated_fact_ids=[],
        sort_order=20,
    )
    db_session.add_all([fact, section])
    db_session.commit()
    section.associated_fact_ids = [fact.id]
    db_session.commit()

    backfill_page_visuals(db_session, project.id)
    db_session.refresh(section)

    row = section.visual_payload["table_rows"][0]
    assert row["label"] == "사용 가능 시간"
    assert row["value"] == "2시간"
    assert "使用时间" not in str(section.visual_payload)


def test_intentionally_empty_narrative_section_does_not_inherit_all_facts(db_session_with_project):
    db_session, project, page = db_session_with_project
    caution = PageSection(
        page_id=page.id,
        section_type="caution",
        associated_fact_ids=[],
        visual_kind="html_graphic",
        visual_payload={"strategy": "text_only", "facts_intentionally_empty": True},
        sort_order=21,
    )
    db_session.add(caution)
    db_session.commit()

    backfill_page_visuals(db_session, project.id)
    db_session.refresh(caution)

    assert caution.is_visible is True
    assert caution.visual_payload["facts_intentionally_empty"] is True
    assert caution.visual_payload["layout_variant"] == "image_text"
    assert caution.visual_kind == "html_graphic"
    assert "items" not in caution.visual_payload


def test_unmapped_text_only_problem_section_gets_valid_layout(db_session_with_project):
    db_session, project, page = db_session_with_project
    problem = PageSection(
        page_id=page.id,
        section_type="problem",
        associated_fact_ids=[],
        visual_kind="html_graphic",
        visual_payload={"strategy": "text_only", "facts_intentionally_empty": True},
        sort_order=22,
    )
    db_session.add(problem)
    db_session.commit()

    backfill_page_visuals(db_session, project.id)
    db_session.refresh(problem)

    assert problem.is_visible is True
    assert problem.visual_payload["layout_variant"] == "image_text"


def test_backfill_keeps_seller_checklist_before_final_specifications(db_session_with_project):
    db_session, project, page = db_session_with_project
    fact = db_session.query(ProductFact).filter(ProductFact.project_id == project.id).first()
    specifications = PageSection(
        page_id=page.id,
        section_type="specifications",
        title="확인된 제품 사양·고지",
        associated_fact_ids=[fact.id],
        sort_order=30,
    )
    checklist = PageSection(
        page_id=page.id,
        section_type="pre_purchase",
        title="판매자 확인 체크리스트",
        visual_kind="html_graphic",
        visual_payload={
            "layout_variant": "checklist",
            "items": [{
                "kind": "seller_action",
                "text": "사진을 추가해 주세요.",
                "verification_status": "action_required",
                "source_fact_ids": [],
            }],
        },
        sort_order=31,
    )
    db_session.add_all([specifications, checklist])
    db_session.commit()

    backfill_page_visuals(db_session, project.id)
    db_session.refresh(specifications)
    db_session.refresh(checklist)

    assert checklist.sort_order < specifications.sort_order


def test_features_keeps_every_explicitly_linked_numeric_fact(db_session_with_project):
    db_session, project, page = db_session_with_project
    db_session.query(ProductFact).filter(ProductFact.project_id == project.id).delete()
    battery = ProductFact(
        project_id=project.id,
        fact_text="배터리 용량: 2000mAh",
        field_key="battery_capacity",
        normalized_value="2000",
        normalized_unit="mAh",
        extraction_source="seller_input",
        verification_status="seller_confirmed",
    )
    features = PageSection(
        page_id=page.id,
        section_type="features",
        title="확인된 핵심 기능을 한눈에",
        sort_order=40,
    )
    db_session.add_all([battery, features])
    db_session.commit()
    features.associated_fact_ids = [battery.id]
    db_session.commit()

    backfill_page_visuals(db_session, project.id)
    db_session.refresh(features)

    assert features.is_visible is True
    assert features.visual_payload["cards"][0]["title"] == "배터리 용량"
    assert features.visual_payload["cards"][0]["body"] == "2000mAh"

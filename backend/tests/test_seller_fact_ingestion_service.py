from src.db.models import AgentRun, Brand, ProductProject
from src.services.seller_fact_ingestion_service import (
    extract_confirmed_seller_specs,
    persist_confirmed_seller_specs,
    persist_saved_agent_run_seller_specs,
)


def test_extracts_direct_numeric_seller_specs_without_losing_korean_units():
    specs = extract_confirmed_seller_specs(["260g, 10분, 800mAh"])

    assert specs == [
        ("판매자 제공 사양: 무게는 260g입니다.", "260g"),
        ("판매자 제공 사양: 사용 시간은 10분입니다.", "10분"),
        ("판매자 제공 사양: 배터리 용량은 800mAh입니다.", "800mAh"),
    ]


def test_persists_direct_numeric_seller_specs_as_confirmed_facts(db_session):
    created = persist_confirmed_seller_specs(
        db_session,
        "seller-spec-project",
        ["260g, 10분, 800mAh"],
    )
    db_session.commit()

    assert len(created) == 3
    assert {fact.verification_status for fact in created} == {"seller_confirmed"}
    assert {fact.extraction_source for fact in created} == {"seller_input"}
    assert {fact.source_text for fact in created} == {"260g", "10분", "800mAh"}


def test_deduplicates_seller_specs_between_retries(db_session):
    first = persist_confirmed_seller_specs(db_session, "seller-spec-project", ["260g, 10분"])
    db_session.commit()
    second = persist_confirmed_seller_specs(db_session, "seller-spec-project", ["260g, 10분"])

    assert len(first) == 2
    assert second == []


def test_backfills_specs_from_an_existing_agent_run_snapshot(db_session):
    brand = Brand(id="seller-compat-brand", workspace_id="seller-compat-workspace", name="Seller Brand")
    project = ProductProject(
        id="seller-compat-project",
        workspace_id=brand.workspace_id,
        brand_id=brand.id,
        name="Seller Product",
    )
    run = AgentRun(
        id="seller-compat-run",
        workspace_id=brand.workspace_id,
        project_id=project.id,
        mode="mock",
        status="completed",
        current_stage="review_editor",
        input_snapshot={"description": "260g, 10분, 800mAh"},
        outputs_json={},
        cost_approval_status="not_required",
        created_by="seller-compat-user",
    )
    db_session.add_all([brand, project, run])
    db_session.commit()

    created = persist_saved_agent_run_seller_specs(db_session, project.id)
    db_session.commit()

    assert {fact.source_text for fact in created} == {"260g", "10분", "800mAh"}
    assert all(fact.verification_status == "seller_confirmed" for fact in created)

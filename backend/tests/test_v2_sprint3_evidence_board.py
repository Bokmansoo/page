from src.db.models import (
    AgentRun,
    Brand,
    FactHistory,
    PageSection,
    PageVersion,
    ProductFact,
    ProductPage,
    ProductProject,
    User,
    Workspace,
)
from src.services.fact_evidence_service import (
    approved_fact_snapshot,
    apply_conflicts,
    fact_board_blockers,
    fact_impact_summary,
    mark_fact_dependents_stale,
    normalize_candidates,
    refresh_evidence_board,
    upsert_candidate,
)

HEADERS = {
    "X-Mock-User-Id": "user-s3",
    "X-Mock-Workspace-Id": "workspace-s3",
}


def _project(db_session):
    user = User(id="user-s3", email="s3@example.com", name="Sprint 3")
    workspace = Workspace(id="workspace-s3", name="Sprint 3", owner_id=user.id)
    brand = Brand(id="brand-s3", workspace_id=workspace.id, name="Brand")
    project = ProductProject(id="project-s3", workspace_id=workspace.id, brand_id=brand.id, name="YL-T02")
    db_session.add_all([user, workspace, brand, project])
    db_session.commit()
    return project, user


def _candidate(text: str, field_key: str):
    return next(item for item in normalize_candidates(text) if item.field_key == field_key)


def test_normalization_canonicalizes_units_and_preserves_source_scope_and_model():
    one_kg = _candidate("YL-T02 제품 무게 1kg", "weight")
    thousand_g = _candidate("YL-T02 제품 무게 1000g", "weight")
    carton = _candidate("외박스 6개입 순중량 6kg", "weight")
    t01 = _candidate("YL-T01 제품 무게 950g", "weight")

    assert (one_kg.value, one_kg.unit) == ("1000", "g")
    assert (thousand_g.value, thousand_g.unit) == ("1000", "g")
    assert thousand_g.source_text == "무게 1000g"
    assert carton.scope == "master_carton"
    assert (carton.value, carton.unit) == ("6000", "g")
    assert t01.model_option == "YL-T01"
    assert thousand_g.model_option == "YL-T02"


def test_yl_t02_time_meanings_and_temperature_review_are_separate():
    candidates = normalize_candidates("YL-T02 작동 시간 10분, 충전 시간 3.5시간, 사용 가능 시간 2시간, 약 42℃")
    keyed = {item.field_key: item for item in candidates}
    assert keyed["single_operation_time"].value == "10"
    assert keyed["charge_time"].value == "3.5"
    assert keyed["total_use_time"].value == "2"
    assert keyed["heating_temperature"].needs_review is True


def test_plain_korean_use_time_is_normalized_as_total_use_time():
    candidate = _candidate("YL-T02 사용 시간 2시간", "total_use_time")
    assert candidate.value == "2"
    assert candidate.unit == "시간"


def test_equivalent_units_merge_but_models_and_cartons_do_not(db_session):
    project, user = _project(db_session)
    first = upsert_candidate(db_session, project.id, _candidate("YL-T02 무게 1kg", "weight"), source_type="seller_input", user_id=user.id)
    same = upsert_candidate(db_session, project.id, _candidate("YL-T02 무게 1000g", "weight"), source_type="asset_ocr", user_id=user.id)
    t01 = upsert_candidate(db_session, project.id, _candidate("YL-T01 무게 950g", "weight"), source_type="asset_ocr", user_id=user.id)
    carton = upsert_candidate(db_session, project.id, _candidate("외박스 순중량 6kg", "weight"), source_type="asset_ocr", user_id=user.id)
    db_session.commit()

    assert first.id == same.id
    assert len(first.evidences) == 2
    assert t01.id != first.id and t01.conflict_group_key != first.conflict_group_key
    assert carton.scope == "master_carton" and carton.conflict_group_key != first.conflict_group_key


def test_four_and_six_plus_are_conflicted_and_resolved_with_history(client, db_session):
    project, user = _project(db_session)
    four = upsert_candidate(db_session, project.id, _candidate("YL-T02 마사지 헤드 4개", "massage_head_count"), source_type="asset_ocr", user_id=user.id)
    six = upsert_candidate(db_session, project.id, _candidate("YL-T02 마사지 헤드 6개 이상", "massage_head_count"), source_type="asset_ocr", user_id=user.id)
    apply_conflicts(db_session, project.id)
    db_session.commit()
    assert four.verification_status == six.verification_status == "conflicted"

    response = client.post(
        f"/api/v1/projects/{project.id}/facts/evidence-board/conflicts/resolve",
        headers=HEADERS,
        json={"selected_fact_id": four.id, "note": "전용 상세 이미지 기준"},
    )
    assert response.status_code == 200
    db_session.refresh(four); db_session.refresh(six)
    assert four.verification_status == "seller_confirmed"
    assert six.verification_status == "rejected"
    assert db_session.query(FactHistory).filter(FactHistory.fact_id.in_([four.id, six.id])).count() == 2


def test_single_model_project_assigns_generic_marketplace_specs_to_selected_model(db_session):
    project, user = _project(db_session)
    project.raw_input_text = "마사지 헤드 4개, 상품 속성 마사지 헤드 6개 이상"
    refresh_evidence_board(db_session, project, user.id)
    db_session.commit()
    facts = db_session.query(ProductFact).filter(ProductFact.project_id == project.id, ProductFact.field_key == "massage_head_count").all()
    assert {fact.model_option for fact in facts} == {"YL-T02"}
    assert {fact.normalized_value for fact in facts} == {"4", "6+"}
    assert {fact.verification_status for fact in facts} == {"conflicted"}


def test_risky_fact_requires_explicit_acknowledgement(client, db_session):
    project, user = _project(db_session)
    temperature = upsert_candidate(db_session, project.id, _candidate("YL-T02 약 42℃", "heating_temperature"), source_type="seller_input", user_id=user.id)
    db_session.commit()

    rejected = client.post(
        f"/api/v1/projects/{project.id}/facts/evidence-board/confirm",
        headers=HEADERS,
        json={"fact_ids": [temperature.id]},
    )
    assert rejected.status_code == 409
    confirmed = client.post(
        f"/api/v1/projects/{project.id}/facts/evidence-board/confirm",
        headers=HEADERS,
        json={"fact_ids": [temperature.id], "risk_acknowledged": True, "note": "공급처 표기 확인"},
    )
    assert confirmed.status_code == 200
    db_session.refresh(temperature)
    assert temperature.verification_status == "seller_confirmed"
    assert temperature.needs_review is False

    project.raw_input_text = "약 42℃"
    refresh_evidence_board(db_session, project, user.id)
    db_session.commit(); db_session.refresh(temperature)
    assert temperature.verification_status == "seller_confirmed"
    assert any(history.event_type == "risk_acknowledged" for history in temperature.histories)


def test_refresh_downgrades_legacy_auto_confirmed_risk_without_acknowledgement(db_session):
    project, user = _project(db_session)
    project.raw_input_text = "약 42℃, 친환경 소재"
    temperature = upsert_candidate(db_session, project.id, _candidate("YL-T02 약 42℃", "heating_temperature"), source_type="seller_input", user_id=user.id)
    temperature.verification_status = "seller_confirmed"
    temperature.needs_review = False
    temperature.risk_flags = []
    db_session.commit()

    refresh_evidence_board(db_session, project, user.id)
    db_session.commit(); db_session.refresh(temperature)
    assert temperature.verification_status == "needs_review"
    assert temperature.needs_review is True
    assert "requires_claim_review" in temperature.risk_flags


def test_refresh_reclassifies_legacy_bare_carton_dimension_and_labels_scope(db_session):
    project, user = _project(db_session)
    legacy = upsert_candidate(db_session, project.id, _candidate("YL-T02 53 × 41.5 × 32cm", "product_size"), source_type="seller_input", user_id=user.id)
    assert legacy.scope == "product"
    db_session.flush()
    db_session.refresh(legacy)
    legacy.source_text = "제품 크기 40 × 17 × 15cm, 외박스 규격 53 × 41.5 × 32cm"
    legacy.evidences[0].original_text = legacy.source_text
    project.raw_input_text = "외박스 규격 53 × 41.5 × 32cm (6개입)"
    db_session.commit()

    refresh_evidence_board(db_session, project, user.id)
    db_session.commit(); db_session.refresh(legacy)
    scoped = db_session.query(ProductFact).filter(
        ProductFact.project_id == project.id,
        ProductFact.field_key == "product_size",
        ProductFact.scope == "master_carton",
    ).one()
    assert legacy.verification_status == "rejected"
    assert scoped.fact_text == "외박스 크기: 53 × 41.5 × 32cm"


def test_manual_candidate_merge_preserves_all_evidence(client, db_session):
    project, user = _project(db_session)
    target = upsert_candidate(db_session, project.id, _candidate("YL-T02 무게 950g", "weight"), source_type="asset_ocr", user_id=user.id)
    source = upsert_candidate(db_session, project.id, _candidate("YL-T02 무게 1000g", "weight"), source_type="seller_input", user_id=user.id)
    db_session.commit()

    response = client.post(
        f"/api/v1/projects/{project.id}/facts/evidence-board/merge",
        headers=HEADERS,
        json={"target_fact_id": target.id, "source_fact_ids": [source.id], "note": "동일 항목의 근거를 판매자가 병합"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["verification_status"] == "needs_review"
    assert len(body["evidences"]) == 2
    db_session.refresh(source)
    assert source.verification_status == "rejected"


def test_rejected_and_review_facts_are_excluded_and_block_snapshot(client, db_session):
    project, user = _project(db_session)
    approved = upsert_candidate(db_session, project.id, _candidate("배터리 용량 2000mAh", "battery_capacity"), source_type="seller_input", user_id=user.id)
    review = upsert_candidate(db_session, project.id, _candidate("약 42℃", "heating_temperature"), source_type="asset_ocr", user_id=user.id)
    rejected = upsert_candidate(db_session, project.id, _candidate("정격 소비전력 8W", "rated_power"), source_type="asset_ocr", user_id=user.id)
    rejected.verification_status = "rejected"; rejected.needs_review = False
    db_session.commit()

    snapshot = approved_fact_snapshot(db_session, project.id, user.id)
    assert [item["id"] for item in snapshot.facts_json] == [approved.id]
    assert review.id in {item["fact_id"] for item in fact_board_blockers(db_session, project.id)}
    blocked = client.post(f"/api/v1/projects/{project.id}/facts/evidence-board/snapshot", headers=HEADERS)
    assert blocked.status_code == 409


def test_fact_change_marks_sections_storyboard_and_versions_as_impacted(db_session):
    project, user = _project(db_session)
    fact = upsert_candidate(db_session, project.id, _candidate("배터리 용량 2000mAh", "battery_capacity"), source_type="seller_input", user_id=user.id)
    project.planning_draft = {"cards": [{"id": "hero-card", "source_fact_ids": [fact.id]}]}
    page = ProductPage(project_id=project.id)
    db_session.add(page); db_session.flush()
    section = PageSection(page_id=page.id, section_type="specifications", associated_fact_ids=[fact.id])
    db_session.add(section); db_session.flush()
    version = PageVersion(page_id=page.id, version_number=1, page_data={"facts_snapshot": [{"id": fact.id}]}, created_by=user.id)
    db_session.add(version); db_session.commit()

    assert mark_fact_dependents_stale(db_session, project.id, [fact.id]) == [section.id]
    db_session.commit(); db_session.refresh(section); db_session.refresh(project)
    impact = fact_impact_summary(db_session, fact)
    assert section.facts_stale is True
    assert impact["page_section_ids"] == [section.id]
    assert impact["page_version_ids"] == [version.id]
    assert impact["storyboard_card_ids"] == ["hero-card"]
    assert project.planning_draft["cards"][0]["facts_stale"] is True


def test_approved_snapshot_is_reproducible_and_contains_full_evidence(db_session):
    project, user = _project(db_session)
    fact = upsert_candidate(db_session, project.id, _candidate("배터리 용량 2000mAh", "battery_capacity"), source_type="seller_input", source_url="https://example.test/item", user_id=user.id)
    db_session.commit()
    first = approved_fact_snapshot(db_session, project.id, user.id)
    second = approved_fact_snapshot(db_session, project.id, user.id)
    assert first.snapshot_hash == second.snapshot_hash
    assert first.facts_json[0]["id"] == fact.id
    assert first.facts_json[0]["evidence"][0]["source_url"] == "https://example.test/item"
    assert first.facts_json[0]["verification_status"] == "seller_confirmed"


def test_other_workspace_cannot_read_or_approve_fact_board(client, db_session):
    project, user = _project(db_session)
    fact = upsert_candidate(db_session, project.id, _candidate("배터리 용량 2000mAh", "battery_capacity"), source_type="seller_input", user_id=user.id)
    other_user = User(id="other-user", email="other@example.com", name="Other")
    other_workspace = Workspace(id="other-workspace", name="Other", owner_id=other_user.id)
    db_session.add_all([other_user, other_workspace]); db_session.commit()
    other_headers = {"X-Mock-User-Id": other_user.id, "X-Mock-Workspace-Id": other_workspace.id}

    assert client.get(f"/api/v1/projects/{project.id}/facts/evidence-board", headers=other_headers).status_code == 404
    assert client.post(
        f"/api/v1/projects/{project.id}/facts/evidence-board/confirm",
        headers=other_headers,
        json={"fact_ids": [fact.id]},
    ).status_code == 404


def test_agent_generation_returns_fact_review_gate_with_review_url(client, db_session):
    project, user = _project(db_session)
    review = upsert_candidate(db_session, project.id, _candidate("약 42℃", "heating_temperature"), source_type="asset_ocr", user_id=user.id)
    run = AgentRun(
        id="run-s3",
        workspace_id=project.workspace_id,
        project_id=project.id,
        mode="mock",
        status="created",
        current_stage="intake",
        input_snapshot={"product_name": "YL-T02"},
        outputs_json={},
        cost_approval_status="not_required",
        created_by=user.id,
    )
    db_session.add(run); db_session.commit()

    response = client.post(f"/api/agent-runs/{run.id}/run-mock", headers=HEADERS)
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "fact_evidence_not_ready"
    assert detail["review_url"] == f"/workspace/projects/{project.id}/facts"
    assert review.id in {item["fact_id"] for item in detail["blockers"]}

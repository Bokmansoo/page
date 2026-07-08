from src.db.models import Brand, ProductFact, ProductProject, User, Workspace


HEADERS = {
    "X-Mock-User-Id": "planning-draft-user",
    "X-Mock-Workspace-Id": "planning-draft-workspace",
}


def test_create_planning_draft_generates_and_persists_draft(client, db_session):
    user = User(
        id=HEADERS["X-Mock-User-Id"],
        email="planning-draft@example.com",
        name="Planning Draft User",
    )
    workspace = Workspace(
        id=HEADERS["X-Mock-Workspace-Id"],
        name="Planning Draft Workspace",
        owner_id=user.id,
    )
    brand = Brand(id="planning-draft-brand", workspace_id=workspace.id, name="Planning Draft Brand")
    project = ProductProject(
        id="planning-draft-project",
        workspace_id=workspace.id,
        brand_id=brand.id,
        name="루메나 휴대용 무선 냉각선풍기",
        category="생활용품/리빙",
        raw_input_text="무선, 휴대용, 책상과 차량에서 사용 가능한 냉각선풍기",
        status="draft",
    )
    fact = ProductFact(
        project_id=project.id,
        fact_text="무선 휴대용 냉각선풍기",
        verification_status="confirmed",
    )
    db_session.add_all([user, workspace, brand, project, fact])
    db_session.commit()

    response = client.post(
        "/api/v1/projects/planning-draft-project/planning-draft",
        headers=HEADERS,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["cards"]
    assert payload["cards"][0]["type"]

    db_session.refresh(project)
    assert project.planning_draft
    assert project.planning_draft["cards"][0]["type"] == payload["cards"][0]["type"]

    get_response = client.get(
        "/api/v1/projects/planning-draft-project/planning-draft",
        headers=HEADERS,
    )
    assert get_response.status_code == 200
    assert get_response.json()["cards"][0]["id"] == payload["cards"][0]["id"]

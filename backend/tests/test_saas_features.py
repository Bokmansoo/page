import datetime
from src.api.auth import DEFAULT_BRAND_ID
from src.db.models import WorkspaceMember, WorkspaceInvitation, AiJobLog, ExportJob, ProductProject, Brand

def test_brand_management(client):
    headers = {
        "X-Mock-User-Id": "owner-1",
        "X-Mock-Workspace-Id": "workspace-1"
    }

    # 1. List brands (should have default brand)
    res = client.get("/api/v1/brands", headers=headers)
    assert res.status_code == 200
    brands = res.json()
    assert len(brands) == 1
    assert brands[0]["name"] == "Default Brand"

    # 2. Create brand
    payload = {
        "name": "Sleek Premium Label",
        "brand_colors": {"primary": "#1E1B4B", "secondary": "#EC4899"},
        "font_tone": "classic",
        "default_disclaimer": "SaaS Test Disclaimer"
    }
    create_res = client.post("/api/v1/brands", json=payload, headers=headers)
    assert create_res.status_code == 201
    new_brand = create_res.json()
    assert new_brand["name"] == "Sleek Premium Label"
    assert new_brand["font_tone"] == "classic"
    new_brand_id = new_brand["id"]

    # 3. Update brand
    update_payload = {
        "name": "Sleek Premium Label v2",
        "font_tone": "modern"
    }
    update_res = client.patch(f"/api/v1/brands/{new_brand_id}", json=update_payload, headers=headers)
    assert update_res.status_code == 200
    updated_brand = update_res.json()
    assert updated_brand["name"] == "Sleek Premium Label v2"
    assert updated_brand["font_tone"] == "modern"

    # 4. List brands again
    res = client.get("/api/v1/brands", headers=headers)
    assert len(res.json()) == 2

    # 5. Delete brand
    delete_res = client.delete(f"/api/v1/brands/{new_brand_id}", headers=headers)
    assert delete_res.status_code == 204

    # 6. Cannot delete the last remaining brand
    default_brand_id = brands[0]["id"]
    delete_last_res = client.delete(f"/api/v1/brands/{default_brand_id}", headers=headers)
    assert delete_last_res.status_code == 400


def test_rbac_permissions(client, db_session):
    # Setup owner and viewer membership
    headers_owner = {
        "X-Mock-User-Id": "owner-1",
        "X-Mock-Workspace-Id": "workspace-1"
    }
    headers_viewer = {
        "X-Mock-User-Id": "viewer-1",
        "X-Mock-Workspace-Id": "workspace-1"
    }

    # Trigger bootstrapping workspace first
    client.get("/api/v1/brands", headers=headers_owner)

    # Insert viewer membership
    member = WorkspaceMember(
        workspace_id="workspace-1",
        user_id="viewer-1",
        role="viewer"
    )
    db_session.add(member)
    db_session.commit()

    # 1. Viewer trying to create project -> Forbidden by FastAPI auth Context (requires member, admin, owner for mutative endpoints)
    # Wait, let's verify if project creation uses roles! In projects.py, let's make sure it is protected.
    # Wait! Let's check require_roles on creation in projects.py. Wait, projects.py currently doesn't check role, but we can verify if other routes check it or we can check our new workspaces invitation router.
    # Wait, let's verify the viewer role on workspace invitations:
    # Viewer trying to send team invitation -> should return 403.
    payload = {"email": "test@test.com", "role": "member"}
    invite_res = client.post("/api/v1/workspaces/invitations", json=payload, headers=headers_viewer)
    assert invite_res.status_code == 403

    # Owner sending invitation -> Success
    invite_ok = client.post("/api/v1/workspaces/invitations", json=payload, headers=headers_owner)
    assert invite_ok.status_code == 201
    invite_id = invite_ok.json()["id"]

    # Viewer accepting invitation for another email -> Forbidden
    headers_other_email = {
        "X-Mock-User-Id": "other-user",
        "X-Mock-Workspace-Id": "workspace-1"
    }
    accept_res = client.post(f"/api/v1/workspaces/invitations/{invite_id}/accept", headers=headers_other_email)
    assert accept_res.status_code == 403


def test_viewer_cannot_create_project(client, db_session):
    headers_owner = {
        "X-Mock-User-Id": "owner-1",
        "X-Mock-Workspace-Id": "workspace-1"
    }
    headers_viewer = {
        "X-Mock-User-Id": "viewer-1",
        "X-Mock-Workspace-Id": "workspace-1"
    }

    brand_res = client.get("/api/v1/brands", headers=headers_owner)
    assert brand_res.status_code == 200
    brand_id = brand_res.json()[0]["id"]

    member = WorkspaceMember(
        workspace_id="workspace-1",
        user_id="viewer-1",
        role="viewer"
    )
    db_session.add(member)
    db_session.commit()

    create_res = client.post(
        "/api/v1/projects",
        json={
            "brand_id": brand_id,
            "name": "Viewer Forbidden Project",
            "raw_input_text": "viewer should not be able to create this project"
        },
        headers=headers_viewer
    )

    assert create_res.status_code == 403
    assert "Insufficient permissions" in create_res.json()["detail"]


def test_workspace_budget_limits(client, db_session):
    headers = {
        "X-Mock-User-Id": "owner-1",
        "X-Mock-Workspace-Id": "workspace-1"
    }

    # Bootstrap
    client.get("/api/v1/brands", headers=headers)

    # 1. Usage stats should be under limit
    usage_res = client.get("/api/v1/workspaces/usage", headers=headers)
    assert usage_res.status_code == 200
    assert usage_res.json()["is_blocked"] is False

    # 2. Add a project
    project = ProductProject(
        id="project-limit-1",
        workspace_id="workspace-1",
        brand_id=DEFAULT_BRAND_ID,
        name="Limit Test Project",
        status="draft"
    )
    db_session.add(project)
    db_session.commit()

    # 3. Simulate high AI costs exceeding $5.00
    ai_log = AiJobLog(
        project_id="project-limit-1",
        task_type="fact_extraction",
        provider="openai",
        model_name="gpt-4o",
        prompt_version="1.0.0",
        duration_ms=2000,
        estimated_cost=5.50,
        status="success"
    )
    db_session.add(ai_log)
    db_session.commit()

    # 4. Check usage (should be blocked)
    usage_res2 = client.get("/api/v1/workspaces/usage", headers=headers)
    assert usage_res2.json()["is_blocked"] is True
    assert usage_res2.json()["total_ai_cost"] == 5.50

    # 5. Running AI analysis now should return 402 Payment Required
    analyze_res = client.post("/api/v1/projects/project-limit-1/analyze", json={}, headers=headers)
    assert analyze_res.status_code == 402
    assert "AI budget limit exceeded" in analyze_res.json()["detail"]


def test_rate_limiting(client, db_session):
    headers = {
        "X-Mock-User-Id": "owner-1",
        "X-Mock-Workspace-Id": "workspace-1"
    }

    # Bootstrap
    client.get("/api/v1/brands", headers=headers)

    # Add a project
    project = ProductProject(
        id="project-rate-1",
        workspace_id="workspace-1",
        brand_id=DEFAULT_BRAND_ID,
        name="Rate Limit Test",
        status="draft"
    )
    db_session.add(project)

    # Simulate 10 recent AI jobs in last hour
    for i in range(10):
        ai_log = AiJobLog(
            project_id="project-rate-1",
            task_type="fact_extraction",
            provider="openai",
            model_name="gpt-4o",
            prompt_version="1.0.0",
            duration_ms=1000,
            estimated_cost=0.01,
            status="success",
            created_at=datetime.datetime.utcnow()
        )
        db_session.add(ai_log)

    db_session.commit()

    # Try to run AI analysis -> should return 429 Too Many Requests
    analyze_res = client.post("/api/v1/projects/project-rate-1/analyze", json={}, headers=headers)
    assert analyze_res.status_code == 429
    assert "Rate limit exceeded" in analyze_res.json()["detail"]

import datetime as dt

import pytest
from fastapi import HTTPException

from src.config import settings
from src.db.models import AuditLog, Asset, Brand, OAuthAccount, ProductProject, User, Workspace, WorkspaceMember
from src.services.auth_service import (
    create_oauth_attempt, create_session,
    consume_oauth_attempt,
    resolve_provider_identity,
)
from src.api import auth_routes


HEADERS = {
    "X-Mock-User-Id": "00000000-0000-0000-0000-000000000901",
    "X-Mock-Workspace-Id": "00000000-0000-0000-0000-000000000902",
}


def _signed_in_client(db_session, client):
    """Create a real server session; account mutation endpoints never trust headers."""
    user = User(email="account@example.test", name="Account Seller")
    db_session.add(user)
    db_session.flush()
    workspace = Workspace(name="Account workspace", owner_id=user.id)
    db_session.add(workspace)
    db_session.commit()
    _, token, csrf = create_session(db_session, user, workspace)
    client.cookies.set(settings.SELLFORM_SESSION_COOKIE_NAME, token)
    client.cookies.set(settings.SELLFORM_SESSION_CSRF_COOKIE_NAME, csrf)
    return user, workspace, {"X-CSRF-Token": csrf}


def test_session_endpoint_uses_explicit_test_context(client):
    response = client.get("/api/v1/auth/session", headers=HEADERS)
    assert response.status_code == 200
    assert response.json()["user"]["id"] == HEADERS["X-Mock-User-Id"]


def test_account_endpoint_returns_only_the_signed_in_users_account_data(client, db_session):
    """The account screen must be backed by the session context, not a URL id."""
    user, workspace, _ = _signed_in_client(db_session, client)
    response = client.get("/api/v1/auth/account")
    assert response.status_code == 200
    body = response.json()
    assert body["user"]["id"] == user.id
    assert body["active_workspace_id"] == workspace.id
    assert body["workspaces"] == [{
        "id": workspace.id,
        "name": "Account workspace",
        "role": "owner",
    }]


def test_production_ignores_mock_headers(client, monkeypatch):
    monkeypatch.setattr(settings, "SELLFORM_AUTH_MODE", "production")
    monkeypatch.setattr(settings, "SELLFORM_AUTH_ALLOW_TEST_MOCK", False)
    response = client.get("/api/v1/auth/session", headers=HEADERS)
    assert response.status_code == 401


def test_oauth_state_is_single_use_and_expiry_is_rejected(db_session):
    attempt, state = create_oauth_attempt(db_session, "google", "login", "/workspace")
    assert consume_oauth_attempt(db_session, "google", state).id == attempt.id
    with pytest.raises(Exception):
        consume_oauth_attempt(db_session, "google", state)

    expired, expired_state = create_oauth_attempt(db_session, "google", "login", "/workspace")
    expired.expires_at = dt.datetime.utcnow() - dt.timedelta(seconds=1)
    db_session.commit()
    with pytest.raises(Exception):
        consume_oauth_attempt(db_session, "google", expired_state)


def test_same_email_does_not_auto_merge_provider_accounts(db_session):
    attempt_one, _ = create_oauth_attempt(db_session, "google", "login", "/workspace")
    user_one, _ = resolve_provider_identity(
        db_session, provider="google", provider_account_id="google-subject-one",
        email="same@example.test", display_name="One", attempt=attempt_one,
    )
    attempt_two, _ = create_oauth_attempt(db_session, "kakao", "login", "/workspace")
    user_two, _ = resolve_provider_identity(
        db_session, provider="kakao", provider_account_id="kakao-subject-two",
        email="same@example.test", display_name="Two", attempt=attempt_two,
    )
    assert user_one.id != user_two.id
    assert db_session.query(OAuthAccount).filter_by(provider="google").one().user_id == user_one.id
    assert db_session.query(OAuthAccount).filter_by(provider="kakao").one().user_id == user_two.id
    owner_membership = db_session.query(WorkspaceMember).filter_by(user_id=user_one.id).one()
    assert owner_membership.role == "owner"


def test_cross_workspace_project_request_is_denied(client, db_session):
    """A session/header identity cannot choose another workspace through request data."""
    owner = User(email="other@example.test", name="Other")
    db_session.add(owner)
    db_session.flush()
    workspace = Workspace(name="Other workspace", owner_id=owner.id)
    db_session.add(workspace)
    db_session.commit()
    response = client.get("/api/v1/projects", headers={**HEADERS, "X-Mock-Workspace-Id": workspace.id})
    assert response.status_code in {403, 404}


def test_cannot_unlink_the_last_social_login_method(client, db_session):
    user, _, csrf_headers = _signed_in_client(db_session, client)
    db_session.add_all([
        OAuthAccount(user_id=user.id, provider="google", provider_account_id="google-sub"),
        OAuthAccount(user_id=user.id, provider="kakao", provider_account_id="kakao-sub"),
    ])
    db_session.commit()

    removed = client.delete("/api/v1/auth/accounts/google", headers=csrf_headers)
    assert removed.status_code == 200
    blocked = client.delete("/api/v1/auth/accounts/kakao", headers=csrf_headers)
    assert blocked.status_code == 409
    assert db_session.query(OAuthAccount).filter_by(user_id=user.id).count() == 1
    assert db_session.query(AuditLog).filter_by(action="oauth_account_unlinked").count() == 1


def test_withdrawal_requires_explicit_confirmation_and_revokes_the_account(client, db_session):
    user, _, csrf_headers = _signed_in_client(db_session, client)
    rejected = client.request(
        "DELETE", "/api/v1/auth/account", headers=csrf_headers, json={"confirmation": "cancel"}
    )
    assert rejected.status_code == 400

    withdrawn = client.request(
        "DELETE", "/api/v1/auth/account", headers=csrf_headers, json={"confirmation": "DELETE"}
    )
    assert withdrawn.status_code == 200
    user = db_session.get(User, user.id)
    assert user.is_active is False
    assert user.email.endswith("@deleted.sellform.local")
    assert db_session.query(AuditLog).filter_by(action="account_withdrawn").count() == 1


class _ProviderResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


def test_google_profile_requires_signed_id_token(monkeypatch):
    monkeypatch.setattr(auth_routes.httpx, "post", lambda *args, **kwargs: _ProviderResponse({"access_token": "token"}))
    monkeypatch.setattr(auth_routes.httpx, "get", lambda *args, **kwargs: _ProviderResponse({"sub": "userinfo-only"}))
    attempt = type("Attempt", (), {"code_verifier": "verifier", "nonce": "nonce"})()
    config = {"client_id": "client", "client_secret": "secret", "token_url": "https://token", "userinfo_url": "https://userinfo"}
    with pytest.raises(HTTPException) as exc:
        auth_routes._provider_profile("google", config, "code", attempt)
    assert exc.value.status_code == 401


def test_google_profile_uses_verified_id_token_subject(monkeypatch):
    monkeypatch.setattr(auth_routes.httpx, "post", lambda *args, **kwargs: _ProviderResponse({"access_token": "token", "id_token": "signed"}))
    monkeypatch.setattr(auth_routes.httpx, "get", lambda *args, **kwargs: _ProviderResponse({"sub": "userinfo-sub", "email": "profile@example.test"}))
    monkeypatch.setattr(auth_routes, "_verified_google_claims", lambda *args: {"sub": "verified-sub", "email": "verified@example.test", "name": "Verified"})
    attempt = type("Attempt", (), {"code_verifier": "verifier", "nonce": "nonce"})()
    config = {"client_id": "client", "client_secret": "secret", "token_url": "https://token", "userinfo_url": "https://userinfo"}
    assert auth_routes._provider_profile("google", config, "code", attempt) == ("verified-sub", "verified@example.test", "Verified")


def test_oauth_callback_uses_api_origin_not_browser_origin(monkeypatch):
    monkeypatch.setattr(settings, "SELLFORM_PUBLIC_APP_URL", "https://app.sellform.example")
    monkeypatch.setattr(settings, "SELLFORM_PUBLIC_API_URL", "https://api.sellform.example")
    assert auth_routes._callback_url("google") == "https://api.sellform.example/api/v1/auth/callback/google"


@pytest.mark.parametrize(
    ("provider", "profile_payload", "expected"),
    [
        ("kakao", {"id": 1234, "kakao_account": {"email": "kakao@example.test"}, "properties": {"nickname": "Kakao"}}, ("1234", "kakao@example.test", "Kakao")),
        ("naver", {"response": {"id": "naver-id", "email": "naver@example.test", "nickname": "Naver"}}, ("naver-id", "naver@example.test", "Naver")),
    ],
)
def test_non_google_provider_profiles_use_stable_provider_ids(monkeypatch, provider, profile_payload, expected):
    monkeypatch.setattr(auth_routes.httpx, "post", lambda *args, **kwargs: _ProviderResponse({"access_token": "token"}))
    monkeypatch.setattr(auth_routes.httpx, "get", lambda *args, **kwargs: _ProviderResponse(profile_payload))
    attempt = type("Attempt", (), {"code_verifier": "verifier", "nonce": "nonce"})()
    config = {"client_id": "client", "client_secret": "secret", "token_url": "https://token", "userinfo_url": "https://userinfo"}
    assert auth_routes._provider_profile(provider, config, "code", attempt) == expected


def test_workspace_activation_rotates_the_session(client, db_session):
    user, workspace, csrf_headers = _signed_in_client(db_session, client)
    second = Workspace(name="Shared workspace", owner_id=user.id)
    db_session.add(second)
    db_session.flush()
    db_session.add(WorkspaceMember(workspace_id=second.id, user_id=user.id, role="owner"))
    db_session.commit()
    original = db_session.query(__import__("src.db.models", fromlist=["UserSession"]).UserSession).filter_by(user_id=user.id, revoked_at=None).one()

    response = client.post(f"/api/v1/auth/workspaces/{second.id}/activate", headers=csrf_headers)
    assert response.status_code == 200
    db_session.refresh(original)
    assert original.revoked_at is not None
    replacement = db_session.query(__import__("src.db.models", fromlist=["UserSession"]).UserSession).filter_by(user_id=user.id, revoked_at=None).one()
    assert replacement.id != original.id
    assert replacement.active_workspace_id == second.id


def test_real_session_cannot_read_another_workspaces_project_or_asset(client, db_session):
    user, workspace, _ = _signed_in_client(db_session, client)
    brand = Brand(workspace_id=workspace.id, name="Owner brand")
    other_user = User(email="asset-owner@example.test", name="Other")
    db_session.add_all([brand, other_user])
    db_session.flush()
    other_workspace = Workspace(name="Other workspace", owner_id=other_user.id)
    db_session.add(other_workspace)
    db_session.flush()
    other_brand = Brand(workspace_id=other_workspace.id, name="Other brand")
    db_session.add(other_brand)
    db_session.flush()
    project = ProductProject(workspace_id=other_workspace.id, brand_id=other_brand.id, name="Private project")
    db_session.add(project)
    db_session.flush()
    asset = Asset(project_id=project.id, source_type="uploaded", filename="private.png", file_path="missing.png", mime_type="image/png", file_size=1)
    db_session.add(asset)
    db_session.commit()

    assert client.get(f"/api/v1/projects/{project.id}").status_code == 404
    assert client.get(f"/api/v1/files/assets/{asset.id}").status_code == 404

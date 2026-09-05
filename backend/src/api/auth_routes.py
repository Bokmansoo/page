"""Session, social account, and workspace-auth endpoints (Sprint 9)."""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.config import settings
from src.db.database import get_db
from src.db.models import OAuthAccount, User, UserSession, Workspace, WorkspaceMember
from src.services.auth_service import (
    SUPPORTED_PROVIDERS, _audit, _set_session_cookies, clear_session_cookies,
    consume_oauth_attempt, create_oauth_attempt, create_session, get_auth_context,
    provider_settings, require_csrf, resolve_provider_identity, safe_redirect_path,
    session_from_request, session_payload, rotate_session,
)

router = APIRouter(prefix="/auth", tags=["authentication"])


class AccountWithdrawalRequest(BaseModel):
    """Explicit confirmation prevents an accidental destructive account action."""

    confirmation: str


def _callback_url(provider: str) -> str:
    return f"{settings.SELLFORM_PUBLIC_API_URL.rstrip('/')}/api/v1/auth/callback/{provider}"


def _pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def _verified_google_claims(id_token: str, config: dict, nonce: str) -> dict:
    """Verify Google's signed OIDC token before trusting the subject.

    Userinfo is useful for profile fields, but it is not a replacement for
    validating the signed ID token's issuer, audience and one-time nonce.
    """
    try:
        import jwt
    except ImportError as exc:  # pragma: no cover - dependency is declared
        raise HTTPException(status_code=503, detail="Google OIDC verification dependency is unavailable.") from exc
    try:
        signing_key = jwt.PyJWKClient("https://www.googleapis.com/oauth2/v3/certs").get_signing_key_from_jwt(id_token)
        claims = jwt.decode(
            id_token,
            signing_key.key,
            algorithms=["RS256"],
            audience=config["client_id"],
            issuer=["https://accounts.google.com", "accounts.google.com"],
        )
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Google ID token verification failed.") from exc
    if claims.get("nonce") != nonce or not claims.get("sub"):
        raise HTTPException(status_code=401, detail="Google login nonce verification failed.")
    return claims


def _provider_public(provider: str) -> dict:
    config = provider_settings(provider)
    return {"provider": provider, "configured": bool(config["client_id"] and config["client_secret"]), "display_name": {"google": "Google", "kakao": "카카오", "naver": "네이버"}[provider]}


@router.get("/providers")
def providers():
    return {"providers": [_provider_public(provider) for provider in SUPPORTED_PROVIDERS], "development_mode": settings.SELLFORM_AUTH_MODE.lower() == "development"}


@router.get("/session")
def read_session(
    request: Request,
    response: Response,
    x_mock_user_id: str | None = Header(default=None, alias="X-Mock-User-Id"),
    x_mock_workspace_id: str | None = Header(default=None, alias="X-Mock-Workspace-Id"),
    db: Session = Depends(get_db),
):
    context = get_auth_context(db, request, response, x_mock_user_id, x_mock_workspace_id)
    csrf = request.cookies.get(settings.SELLFORM_SESSION_CSRF_COOKIE_NAME)
    return session_payload(context, csrf)


@router.post("/development-login")
def development_login(request: Request, response: Response, db: Session = Depends(get_db)):
    if settings.SELLFORM_AUTH_MODE.lower() != "development":
        raise HTTPException(status_code=404, detail="개발 로그인은 운영 환경에서 사용할 수 없습니다.")
    context = get_auth_context(db, request, response)
    return session_payload(context, request.cookies.get(settings.SELLFORM_SESSION_CSRF_COOKIE_NAME))


@router.get("/login/{provider}")
def start_login(provider: str, redirect_path: str = "/workspace", db: Session = Depends(get_db)):
    config = provider_settings(provider)
    if not config["client_id"] or not config["client_secret"]:
        raise HTTPException(status_code=503, detail=f"{provider} 로그인 앱이 아직 설정되지 않았습니다.")
    attempt, state = create_oauth_attempt(db, provider, "login", safe_redirect_path(redirect_path))
    query = {
        "response_type": "code", "client_id": config["client_id"], "redirect_uri": _callback_url(provider),
        "state": state, "code_challenge": _pkce_challenge(attempt.code_verifier), "code_challenge_method": "S256",
    }
    if provider == "google":
        query.update({"scope": "openid email profile", "nonce": attempt.nonce, "access_type": "offline", "prompt": "select_account"})
    elif provider == "kakao":
        query.update({"scope": "profile_nickname account_email"})
    else:
        query.update({"response_type": "code", "state": state})
    return {"authorization_url": f"{config['authorize_url']}?{urlencode(query)}", "expires_in": settings.SELLFORM_AUTH_STATE_TTL_SECONDS}


@router.get("/link/{provider}")
def start_link(provider: str, request: Request, response: Response, redirect_path: str = "/workspace", db: Session = Depends(get_db)):
    context = get_auth_context(db, request, response)
    config = provider_settings(provider)
    if not config["client_id"] or not config["client_secret"]:
        raise HTTPException(status_code=503, detail=f"{provider} 로그인 앱이 아직 설정되지 않았습니다.")
    attempt, state = create_oauth_attempt(db, provider, "link", safe_redirect_path(redirect_path), context["user"].id)
    query = {"response_type": "code", "client_id": config["client_id"], "redirect_uri": _callback_url(provider), "state": state, "code_challenge": _pkce_challenge(attempt.code_verifier), "code_challenge_method": "S256"}
    if provider == "google":
        query.update({"scope": "openid email profile", "nonce": attempt.nonce, "prompt": "select_account"})
    elif provider == "kakao":
        query["scope"] = "profile_nickname account_email"
    return {"authorization_url": f"{config['authorize_url']}?{urlencode(query)}"}


def _provider_profile(provider: str, config: dict, code: str, attempt) -> tuple[str, str | None, str | None]:
    token_payload = {"grant_type": "authorization_code", "client_id": config["client_id"], "client_secret": config["client_secret"], "redirect_uri": _callback_url(provider), "code": code}
    if provider != "naver":
        token_payload["code_verifier"] = attempt.code_verifier
    token_response = httpx.post(str(config["token_url"]), data=token_payload, timeout=15)
    if token_response.status_code >= 400:
        raise HTTPException(status_code=401, detail="소셜 로그인 토큰 검증에 실패했습니다.")
    token_data = token_response.json()
    access_token = token_data.get("access_token")
    if not access_token:
        raise HTTPException(status_code=401, detail="소셜 로그인 토큰이 없습니다.")
    profile_response = httpx.get(str(config["userinfo_url"]), headers={"Authorization": f"Bearer {access_token}"}, timeout=15)
    if profile_response.status_code >= 400:
        raise HTTPException(status_code=401, detail="소셜 계정 정보를 확인하지 못했습니다.")
    data = profile_response.json()
    if provider == "google":
        id_token = token_data.get("id_token")
        if not id_token:
            raise HTTPException(status_code=401, detail="Google login response did not include an ID token.")
        claims = _verified_google_claims(id_token, config, attempt.nonce)
        # The signed subject is the identity key. Profile fields are taken from
        # the verified claims first, then userinfo only as a display fallback.
        return str(claims["sub"]), claims.get("email") or data.get("email"), claims.get("name") or data.get("name")
    if provider == "kakao":
        account = data.get("kakao_account") or {}
        return str(data.get("id") or ""), account.get("email"), (data.get("properties") or {}).get("nickname")
    profile = data.get("response") or {}
    return str(profile.get("id") or ""), profile.get("email"), profile.get("name") or profile.get("nickname")


@router.get("/callback/{provider}")
def oauth_callback(provider: str, request: Request, state: str, code: str | None = None, error: str | None = None, error_description: str | None = None, db: Session = Depends(get_db)):
    if error:
        raise HTTPException(status_code=400, detail=f"소셜 로그인이 취소되었거나 실패했습니다: {error_description or error}")
    if not code:
        raise HTTPException(status_code=400, detail="소셜 로그인 코드가 없습니다.")
    attempt = consume_oauth_attempt(db, provider, state)
    config = provider_settings(provider)
    if not config["client_id"] or not config["client_secret"]:
        raise HTTPException(status_code=503, detail="소셜 로그인 앱 설정이 없습니다.")
    provider_account_id, email, name = _provider_profile(provider, config, code, attempt)
    if not provider_account_id:
        raise HTTPException(status_code=401, detail="소셜 계정의 고유 식별자를 확인하지 못했습니다.")
    user, workspace = resolve_provider_identity(db, provider=provider, provider_account_id=provider_account_id, email=email, display_name=name, attempt=attempt)
    response = RedirectResponse(url=f"{settings.SELLFORM_PUBLIC_APP_URL.rstrip('/')}{attempt.redirect_path}", status_code=303)
    _, token, csrf = create_session(db, user, workspace, request)
    _set_session_cookies(response, token, csrf)
    return response


@router.post("/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    active = session_from_request(db, request)
    require_csrf(request, active)
    if active:
        active.revoked_at = dt.datetime.utcnow()
        workspace = db.get(Workspace, active.active_workspace_id)
        if workspace:
            _audit(db, workspace.id, active.user_id, "logout", "session", active.id)
        db.commit()
    clear_session_cookies(response)
    return {"ok": True}


@router.post("/logout-all")
def logout_all(request: Request, response: Response, db: Session = Depends(get_db)):
    context = get_auth_context(db, request, response)
    require_csrf(request, context.get("session"))
    db.query(UserSession).filter_by(user_id=context["user"].id, revoked_at=None).update({"revoked_at": dt.datetime.utcnow()})
    _audit(db, context["workspace"].id, context["user"].id, "logout_all_devices", "user", context["user"].id)
    db.commit()
    clear_session_cookies(response)
    return {"ok": True}


@router.get("/sessions")
def list_sessions(request: Request, response: Response, db: Session = Depends(get_db)):
    context = get_auth_context(db, request, response)
    current_id = context.get("session").id if context.get("session") else None
    sessions = db.query(UserSession).filter_by(user_id=context["user"].id, revoked_at=None).order_by(UserSession.last_seen_at.desc()).all()
    return {"sessions": [{"id": row.id, "current": row.id == current_id, "user_agent": row.user_agent, "ip_address": row.ip_address, "created_at": row.created_at, "last_seen_at": row.last_seen_at, "expires_at": row.expires_at} for row in sessions]}


@router.get("/account")
def read_account(request: Request, response: Response, db: Session = Depends(get_db)):
    """Return account, linked providers and every accessible workspace.

    Provider e-mails are intentionally omitted from this compact response.  The
    signed-in user only needs to see which login methods are connected.
    """
    context = get_auth_context(db, request, response)
    user = context["user"]
    accounts = db.query(OAuthAccount).filter_by(user_id=user.id).order_by(OAuthAccount.linked_at.asc()).all()
    memberships = db.query(WorkspaceMember).filter_by(user_id=user.id).all()
    workspaces: dict[str, dict] = {}
    for membership in memberships:
        workspace = db.get(Workspace, membership.workspace_id)
        if workspace:
            workspaces[workspace.id] = {"id": workspace.id, "name": workspace.name, "role": membership.role}
    owned = db.query(Workspace).filter_by(owner_id=user.id).all()
    for workspace in owned:
        workspaces[workspace.id] = {"id": workspace.id, "name": workspace.name, "role": "owner"}
    return {
        "user": {"id": user.id, "email": user.email, "name": user.name, "created_at": user.created_at},
        "providers": [{"provider": account.provider, "display_name": account.display_name, "linked_at": account.linked_at, "last_login_at": account.last_login_at} for account in accounts],
        "workspaces": list(workspaces.values()),
        "active_workspace_id": context["workspace"].id,
    }


@router.delete("/sessions/{session_id}")
def revoke_session(session_id: str, request: Request, response: Response, db: Session = Depends(get_db)):
    context = get_auth_context(db, request, response)
    require_csrf(request, context.get("session"))
    target = db.query(UserSession).filter_by(id=session_id, user_id=context["user"].id).first()
    if not target:
        raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다.")
    target.revoked_at = dt.datetime.utcnow()
    _audit(db, context["workspace"].id, context["user"].id, "session_revoked", "session", target.id)
    db.commit()
    if context.get("session") and target.id == context["session"].id:
        clear_session_cookies(response)
    return {"ok": True}


@router.post("/workspaces/{workspace_id}/activate")
def activate_workspace(workspace_id: str, request: Request, response: Response, db: Session = Depends(get_db)):
    context = get_auth_context(db, request, response)
    active = context.get("session")
    require_csrf(request, active)
    workspace = db.get(Workspace, workspace_id)
    if not workspace:
        raise HTTPException(status_code=404, detail="워크스페이스를 찾을 수 없습니다.")
    if workspace.owner_id != context["user"].id and not db.query(WorkspaceMember).filter_by(workspace_id=workspace_id, user_id=context["user"].id).first():
        raise HTTPException(status_code=403, detail="다른 워크스페이스는 선택할 수 없습니다.")
    if active:
        _, token, csrf = rotate_session(db, active, workspace, request)
        _set_session_cookies(response, token, csrf)
        _audit(db, workspace.id, context["user"].id, "workspace_activated", "workspace", workspace.id)
        db.commit()
    return {"workspace": {"id": workspace.id, "name": workspace.name}}


@router.delete("/accounts/{provider}")
def unlink_account(provider: str, request: Request, response: Response, db: Session = Depends(get_db)):
    context = get_auth_context(db, request, response)
    require_csrf(request, context.get("session"))
    account = db.query(OAuthAccount).filter_by(user_id=context["user"].id, provider=provider).first()
    if not account:
        raise HTTPException(status_code=404, detail="연결된 소셜 계정이 없습니다.")
    if db.query(OAuthAccount).filter_by(user_id=context["user"].id).count() <= 1:
        raise HTTPException(status_code=409, detail="마지막 로그인 수단은 연결 해제할 수 없습니다.")
    db.delete(account)
    _audit(db, context["workspace"].id, context["user"].id, "oauth_account_unlinked", "oauth_account", account.id, {"provider": provider})
    db.commit()
    return {"ok": True}


@router.delete("/account")
def withdraw_account(
    payload: AccountWithdrawalRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    """Deactivate a Sellform account and invalidate all of its devices.

    We retain a non-identifying audit shell rather than physically deleting rows
    referenced by project history.  This satisfies withdrawal without breaking
    business/audit foreign keys.
    """
    if payload.confirmation.strip().upper() != "DELETE":
        raise HTTPException(status_code=400, detail="계정 탈퇴를 진행하려면 DELETE를 입력해 주세요.")
    context = get_auth_context(db, request, response)
    require_csrf(request, context.get("session"))
    user: User = context["user"]
    if user.email == "seller@local.sellform":
        raise HTTPException(status_code=409, detail="개발용 계정은 탈퇴할 수 없습니다. 로컬 데이터베이스를 초기화해 주세요.")

    now = dt.datetime.utcnow()
    providers = [row.provider for row in db.query(OAuthAccount).filter_by(user_id=user.id).all()]
    revoked_count = db.query(UserSession).filter_by(user_id=user.id, revoked_at=None).update({"revoked_at": now})
    db.query(OAuthAccount).filter_by(user_id=user.id).delete(synchronize_session=False)
    user.is_active = False
    user.deleted_at = now
    user.name = "탈퇴한 사용자"
    user.email = f"deleted-{user.id}@deleted.sellform.local"
    _audit(
        db,
        context["workspace"].id,
        user.id,
        "account_withdrawn",
        "user",
        user.id,
        {"providers": providers, "revoked_sessions": revoked_count},
    )
    db.commit()
    clear_session_cookies(response)
    return {"ok": True}

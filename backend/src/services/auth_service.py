"""Server-session authentication primitives for Sprint 9.

Provider access tokens are used only during the callback and are never stored.
The database stores a random opaque session token hash, not a browser identity.
"""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import hmac
import re
import secrets
from typing import Any

from fastapi import HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from src.config import settings
from src.db.models import AuditLog, Brand, OAuthAccount, OAuthLoginAttempt, User, UserSession, Workspace, WorkspaceMember

DEV_USER_ID = "00000000-0000-0000-0000-000000000001"
DEV_WORKSPACE_ID = "00000000-0000-0000-0000-000000000002"
DEV_BRAND_ID = "00000000-0000-0000-0000-000000000003"
SUPPORTED_PROVIDERS = ("google", "kakao", "naver")


def _now() -> dt.datetime:
    return dt.datetime.utcnow()


def _token_hash(value: str) -> str:
    return hmac.new(
        settings.SELLFORM_SESSION_SECRET.encode("utf-8"), value.encode("utf-8"), hashlib.sha256
    ).hexdigest()


def _new_secret() -> str:
    return secrets.token_urlsafe(48)


def _set_session_cookies(response: Response, token: str, csrf_token: str) -> None:
    max_age = settings.SELLFORM_SESSION_TTL_SECONDS
    response.set_cookie(
        settings.SELLFORM_SESSION_COOKIE_NAME,
        token,
        max_age=max_age,
        httponly=True,
        secure=settings.SELLFORM_SESSION_COOKIE_SECURE,
        samesite="lax",
        path="/",
    )
    response.set_cookie(
        settings.SELLFORM_SESSION_CSRF_COOKIE_NAME,
        csrf_token,
        max_age=max_age,
        httponly=False,
        secure=settings.SELLFORM_SESSION_COOKIE_SECURE,
        samesite="lax",
        path="/",
    )


def clear_session_cookies(response: Response) -> None:
    response.delete_cookie(settings.SELLFORM_SESSION_COOKIE_NAME, path="/")
    response.delete_cookie(settings.SELLFORM_SESSION_CSRF_COOKIE_NAME, path="/")


def _ensure_brand(db: Session, workspace: Workspace) -> None:
    if db.query(Brand).filter(Brand.workspace_id == workspace.id).first():
        return
    # Legacy test clients use the development brand constant with an explicit
    # mock workspace. Keep that compatibility confined to the test-only mock
    # authentication path; real workspaces still receive an independent ID.
    test_default_brand = (
        settings.SELLFORM_AUTH_ALLOW_TEST_MOCK
        and not db.get(Brand, DEV_BRAND_ID)
    )
    brand_id = DEV_BRAND_ID if workspace.id == DEV_WORKSPACE_ID or test_default_brand else None
    db.add(Brand(
        id=brand_id,
        workspace_id=workspace.id,
        name="기본 브랜드",
        brand_colors={"primary": "#059669", "secondary": "#0f172a"},
        font_tone="modern",
        default_disclaimer=None,
    ))


def _ensure_owner_membership(db: Session, workspace: Workspace) -> None:
    """Keep the explicit membership graph consistent with workspace ownership."""
    membership = db.query(WorkspaceMember).filter_by(
        workspace_id=workspace.id,
        user_id=workspace.owner_id,
    ).first()
    if not membership:
        db.add(WorkspaceMember(workspace_id=workspace.id, user_id=workspace.owner_id, role="owner"))
    elif membership.role != "owner":
        membership.role = "owner"


def _audit(db: Session, workspace_id: str, user_id: str, action: str, entity_type: str, entity_id: str, payload: dict[str, Any] | None = None) -> None:
    db.add(AuditLog(
        workspace_id=workspace_id,
        user_id=user_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        payload=payload or {},
    ))


def bootstrap_development_identity(db: Session) -> tuple[User, Workspace]:
    """Local-only identity used until the seller configures social providers."""
    user = db.get(User, DEV_USER_ID)
    if not user:
        user = User(id=DEV_USER_ID, email="seller@local.sellform", name="로컬 판매자")
        db.add(user)
        db.flush()
    workspace = db.get(Workspace, DEV_WORKSPACE_ID)
    if not workspace:
        workspace = Workspace(id=DEV_WORKSPACE_ID, name="개발용 워크스페이스", owner_id=user.id)
        db.add(workspace)
        db.flush()
    if not db.query(OAuthAccount).filter_by(provider="development", provider_account_id="local-seller").first():
        db.add(OAuthAccount(user_id=user.id, provider="development", provider_account_id="local-seller", display_name=user.name))
    _ensure_brand(db, workspace)
    _ensure_owner_membership(db, workspace)
    db.commit()
    return user, workspace


def _role_for_workspace(db: Session, user: User, workspace: Workspace) -> str:
    if workspace.owner_id == user.id:
        return "owner"
    member = db.query(WorkspaceMember).filter_by(workspace_id=workspace.id, user_id=user.id).first()
    if not member:
        raise HTTPException(status_code=403, detail="워크스페이스 접근 권한이 없습니다.")
    # Legacy "member" is the Sprint 9 editor role.
    return "editor" if member.role == "member" else member.role


def create_session(db: Session, user: User, workspace: Workspace, request: Request | None = None) -> tuple[UserSession, str, str]:
    token, csrf_token = _new_secret(), _new_secret()
    session = UserSession(
        user_id=user.id,
        active_workspace_id=workspace.id,
        token_hash=_token_hash(token),
        csrf_token_hash=_token_hash(csrf_token),
        user_agent=(request.headers.get("user-agent") if request else None),
        ip_address=(request.client.host if request and request.client else None),
        expires_at=_now() + dt.timedelta(seconds=settings.SELLFORM_SESSION_TTL_SECONDS),
    )
    db.add(session)
    db.commit()
    return session, token, csrf_token


def rotate_session(db: Session, active_session: UserSession, workspace: Workspace, request: Request | None = None) -> tuple[UserSession, str, str]:
    """Replace a session when its active workspace authority changes."""
    active_session.revoked_at = _now()
    db.commit()
    return create_session(db, active_session.user, workspace, request)


def session_from_request(db: Session, request: Request) -> UserSession | None:
    token = request.cookies.get(settings.SELLFORM_SESSION_COOKIE_NAME)
    if not token:
        return None
    session = db.query(UserSession).filter_by(token_hash=_token_hash(token)).first()
    if not session or session.revoked_at or session.expires_at <= _now() or not session.user.is_active:
        return None
    session.last_seen_at = _now()
    db.commit()
    return session


def _test_mock_context(db: Session, user_id: str | None, workspace_id: str | None) -> tuple[User, Workspace] | None:
    if not settings.SELLFORM_AUTH_ALLOW_TEST_MOCK or not user_id or not workspace_id:
        return None
    user = db.get(User, user_id)
    if not user:
        user = User(id=user_id, email=f"test-{user_id}@sellform.test", name="Test Seller")
        db.add(user)
        db.flush()
    workspace = db.get(Workspace, workspace_id)
    if not workspace:
        workspace = Workspace(id=workspace_id, name="Test Workspace", owner_id=user.id)
        db.add(workspace)
        db.flush()
    _ensure_brand(db, workspace)
    _ensure_owner_membership(db, workspace)
    db.commit()
    return user, workspace


def get_auth_context(
    db: Session,
    request: Request,
    response: Response,
    test_mock_user_id: str | None = None,
    test_mock_workspace_id: str | None = None,
) -> dict[str, Any]:
    """Resolve authorization from a signed-in server session only.

    X-Mock headers are accepted only when the explicit test-only setting is on.
    They are ignored in every production runtime.
    """
    test_context = _test_mock_context(db, test_mock_user_id, test_mock_workspace_id)
    if test_context:
        user, workspace = test_context
        return {"user": user, "workspace": workspace, "role": _role_for_workspace(db, user, workspace), "session": None}

    active_session = session_from_request(db, request)
    if active_session:
        workspace = db.get(Workspace, active_session.active_workspace_id)
        if not workspace:
            raise HTTPException(status_code=401, detail="활성 워크스페이스가 없습니다.")
        return {
            "user": active_session.user,
            "workspace": workspace,
            "role": _role_for_workspace(db, active_session.user, workspace),
            "session": active_session,
        }

    if settings.SELLFORM_AUTH_MODE.lower() == "development":
        user, workspace = bootstrap_development_identity(db)
        session, token, csrf = create_session(db, user, workspace, request)
        _set_session_cookies(response, token, csrf)
        return {"user": user, "workspace": workspace, "role": "owner", "session": session}
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="로그인이 필요합니다.")


def require_csrf(request: Request, session: UserSession | None) -> None:
    if not session:
        return
    supplied = request.headers.get("X-CSRF-Token")
    if not supplied or not hmac.compare_digest(_token_hash(supplied), session.csrf_token_hash):
        raise HTTPException(status_code=403, detail="CSRF 확인에 실패했습니다. 페이지를 새로고침해 주세요.")


def safe_redirect_path(path: str | None) -> str:
    value = path or "/workspace"
    if not value.startswith("/") or value.startswith("//") or not re.match(r"^/workspace(?:/.*)?$", value):
        return "/workspace"
    return value


def provider_settings(provider: str) -> dict[str, str | None]:
    if provider not in SUPPORTED_PROVIDERS:
        raise HTTPException(status_code=404, detail="지원하지 않는 로그인 제공자입니다.")
    values = {
        "google": {
            "client_id": settings.SELLFORM_OAUTH_GOOGLE_CLIENT_ID,
            "client_secret": settings.SELLFORM_OAUTH_GOOGLE_CLIENT_SECRET,
            "authorize_url": "https://accounts.google.com/o/oauth2/v2/auth",
            "token_url": "https://oauth2.googleapis.com/token",
            "userinfo_url": "https://openidconnect.googleapis.com/v1/userinfo",
        },
        "kakao": {
            "client_id": settings.SELLFORM_OAUTH_KAKAO_CLIENT_ID,
            "client_secret": settings.SELLFORM_OAUTH_KAKAO_CLIENT_SECRET,
            "authorize_url": "https://kauth.kakao.com/oauth/authorize",
            "token_url": "https://kauth.kakao.com/oauth/token",
            "userinfo_url": "https://kapi.kakao.com/v2/user/me",
        },
        "naver": {
            "client_id": settings.SELLFORM_OAUTH_NAVER_CLIENT_ID,
            "client_secret": settings.SELLFORM_OAUTH_NAVER_CLIENT_SECRET,
            "authorize_url": "https://nid.naver.com/oauth2.0/authorize",
            "token_url": "https://nid.naver.com/oauth2.0/token",
            "userinfo_url": "https://openapi.naver.com/v1/nid/me",
        },
    }
    return values[provider]


def create_oauth_attempt(db: Session, provider: str, intent: str, redirect_path: str, user_id: str | None = None) -> tuple[OAuthLoginAttempt, str]:
    state, nonce, verifier = _new_secret(), _new_secret(), _new_secret()
    attempt = OAuthLoginAttempt(
        state_hash=_token_hash(state), provider=provider, intent=intent,
        nonce=nonce, code_verifier=verifier, user_id=user_id,
        redirect_path=safe_redirect_path(redirect_path),
        expires_at=_now() + dt.timedelta(seconds=settings.SELLFORM_AUTH_STATE_TTL_SECONDS),
    )
    db.add(attempt)
    db.commit()
    return attempt, state


def consume_oauth_attempt(db: Session, provider: str, state: str) -> OAuthLoginAttempt:
    attempt = db.query(OAuthLoginAttempt).filter_by(state_hash=_token_hash(state), provider=provider).first()
    if not attempt or attempt.consumed_at or attempt.expires_at <= _now():
        raise HTTPException(status_code=400, detail="로그인 요청이 만료되었거나 이미 사용되었습니다.")
    attempt.consumed_at = _now()
    db.commit()
    return attempt


def resolve_provider_identity(
    db: Session, *, provider: str, provider_account_id: str, email: str | None,
    display_name: str | None, attempt: OAuthLoginAttempt,
) -> tuple[User, Workspace]:
    account = db.query(OAuthAccount).filter_by(provider=provider, provider_account_id=str(provider_account_id)).first()
    if attempt.intent == "link":
        if not attempt.user_id:
            raise HTTPException(status_code=400, detail="연결할 사용자 정보가 없습니다.")
        if account and account.user_id != attempt.user_id:
            raise HTTPException(status_code=409, detail="이 소셜 계정은 다른 Sellform 계정에 연결되어 있습니다.")
        user = db.get(User, attempt.user_id)
        if not user:
            raise HTTPException(status_code=401, detail="로그인이 만료되었습니다.")
        if not account:
            account = OAuthAccount(user_id=user.id, provider=provider, provider_account_id=str(provider_account_id), provider_email=email, display_name=display_name)
            db.add(account)
    elif account:
        user = account.user
    else:
        # Do not silently merge duplicate provider e-mails.  The stable provider
        # subject is the identity boundary; explicit re-auth linking is required.
        candidate_email = email or f"{provider}-{provider_account_id}@unverified.sellform.local"
        if db.query(User).filter_by(email=candidate_email).first():
            candidate_email = f"{provider}-{provider_account_id}@unverified.sellform.local"
        user = User(email=candidate_email, name=display_name or f"{provider.title()} 판매자")
        db.add(user)
        db.flush()
        account = OAuthAccount(user_id=user.id, provider=provider, provider_account_id=str(provider_account_id), provider_email=email, display_name=display_name)
        db.add(account)
        workspace = Workspace(name=f"{user.name}의 워크스페이스", owner_id=user.id)
        db.add(workspace)
        db.flush()
        _ensure_brand(db, workspace)
        _ensure_owner_membership(db, workspace)
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="탈퇴했거나 비활성화된 계정입니다.")
    account.last_login_at = _now()
    db.commit()
    workspace = db.query(Workspace).filter_by(owner_id=user.id).order_by(Workspace.id.asc()).first()
    if not workspace:
        membership = db.query(WorkspaceMember).filter_by(user_id=user.id).first()
        if not membership:
            raise HTTPException(status_code=403, detail="접근 가능한 워크스페이스가 없습니다.")
        workspace = db.get(Workspace, membership.workspace_id)
    _audit(db, workspace.id, user.id, "oauth_login" if attempt.intent == "login" else "oauth_account_linked", "oauth_account", account.id, {"provider": provider})
    db.commit()
    return user, workspace


def session_payload(context: dict[str, Any], csrf_token: str | None = None) -> dict[str, Any]:
    user, workspace = context["user"], context["workspace"]
    return {
        "user": {"id": user.id, "email": user.email, "name": user.name},
        "workspace": {"id": workspace.id, "name": workspace.name},
        "role": context["role"],
        "csrf_token": csrf_token,
    }

import json
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt
import pyotp
from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, EmailStr
from sqlmodel import func, select
from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from app.core.config import settings
from app.core.deps import DB, SESSION_COOKIE, CurrentUser, client_ip
from app.core.urls import base_url, rp_id, secure_cookies
from app.core.security import (
    decrypt,
    encrypt,
    hash_password,
    hash_token,
    new_token,
    validate_password,
    verify_password,
)
from app.models import (
    ApiToken,
    Invite,
    PasswordReset,
    Role,
    Session,
    User,
    WebAuthnCredential,
)
from app.services.app_settings import get_user_settings, system_flags
from app.services.audit import audit

router = APIRouter(prefix="/auth", tags=["auth"])

CHALLENGE_COOKIE = "ff_challenge"


# ---------------------------------------------------------------- helpers
def user_out(user: User) -> dict[str, Any]:
    return {
        "id": user.id,
        "email": user.email,
        "display_name": user.display_name,
        "role": user.role,
        "totp_enabled": user.totp_enabled,
        "onboarding_done": user.onboarding_done,
        "has_password": bool(user.password_hash),
        "oidc_linked": bool(user.oidc_sub),
    }


async def create_session(db: DB, user: User, request: Request, response: Response) -> None:
    token = new_token()
    now = datetime.now(UTC)
    db.add(
        Session(
            id=hash_token(token),
            user_id=user.id,
            created_at=now,
            expires_at=now + timedelta(days=settings.session_days),
            user_agent=request.headers.get("user-agent", "")[:255],
            ip=client_ip(request),
        )
    )
    user.last_login_at = now
    db.add(user)
    await db.commit()
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=settings.session_days * 86400,
        httponly=True,
        samesite="lax",
        secure=secure_cookies(request),
        path="/",
    )


def _sign(data: dict[str, Any], minutes: int = 5) -> str:
    payload = {**data, "exp": datetime.now(UTC) + timedelta(minutes=minutes)}
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def _unsign(token: str | None) -> dict[str, Any]:
    if not token:
        raise HTTPException(400, "Sitzung abgelaufen, bitte erneut versuchen")
    try:
        return jwt.decode(token, settings.secret_key, algorithms=["HS256"])
    except jwt.PyJWTError as e:
        raise HTTPException(400, "Ungültige oder abgelaufene Anfrage") from e


def _set_challenge(request: Request, response: Response, data: dict[str, Any]) -> None:
    response.set_cookie(
        CHALLENGE_COOKIE, _sign(data), max_age=300, httponly=True, samesite="lax",
        secure=secure_cookies(request), path="/api/auth",
    )


async def user_count(db: DB) -> int:
    return (await db.exec(select(func.count()).select_from(User))).one()


# ---------------------------------------------------------------- config / me
@router.get("/config")
async def auth_config(db: DB) -> dict[str, Any]:
    flags = await system_flags(db)
    return {
        "open_registration": flags["open_registration"],
        "needs_setup": await user_count(db) == 0,
        "oidc_enabled": settings.oidc_enabled,
        "oidc_name": settings.oidc_display_name,
        "ai_enabled": flags["ai_enabled"],
        "vapid_public_key": settings.vapid_public_key,
    }


@router.get("/me")
async def me(user: CurrentUser, db: DB) -> dict[str, Any]:
    return {"user": user_out(user), "settings": await get_user_settings(db, user.id)}


# ---------------------------------------------------------------- password login
class LoginIn(BaseModel):
    email: str
    password: str
    totp: str | None = None


@router.post("/login")
async def login(body: LoginIn, request: Request, response: Response, db: DB) -> dict[str, Any]:
    user = (await db.exec(select(User).where(func.lower(User.email) == body.email.lower().strip()))).first()
    if not user or not verify_password(body.password, user.password_hash):
        await audit(db, "login_failed", target=body.email[:120], ip=client_ip(request))
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "E-Mail oder Passwort falsch")
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Konto gesperrt")
    if user.totp_enabled:
        if not body.totp:
            return {"totp_required": True}
        secret = decrypt(user.totp_secret_enc)
        if not secret or not pyotp.TOTP(secret).verify(body.totp.replace(" ", ""), valid_window=1):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "2FA-Code ungültig")
    await create_session(db, user, request, response)
    await audit(db, "login", actor_id=user.id, ip=client_ip(request))
    return {"user": user_out(user)}


@router.post("/logout")
async def logout(request: Request, response: Response, db: DB) -> dict[str, bool]:
    cookie = request.cookies.get(SESSION_COOKIE)
    if cookie:
        sess = await db.get(Session, hash_token(cookie))
        if sess:
            await db.delete(sess)
            await db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


# ---------------------------------------------------------------- registration
class RegisterIn(BaseModel):
    email: EmailStr
    password: str
    display_name: str = ""
    invite: str | None = None


@router.get("/invite/{token}")
async def check_invite(token: str, db: DB) -> dict[str, Any]:
    inv = (await db.exec(select(Invite).where(Invite.token_hash == hash_token(token)))).first()
    if not inv or inv.used_at or _aware(inv.expires_at) < datetime.now(UTC):
        raise HTTPException(404, "Einladung ungültig oder abgelaufen")
    return {"email": inv.email, "role": inv.role}


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


@router.post("/register")
async def register(body: RegisterIn, request: Request, response: Response, db: DB) -> dict[str, Any]:
    if err := validate_password(body.password):
        raise HTTPException(422, err)
    first_user = await user_count(db) == 0
    flags = await system_flags(db)
    invite = None
    role = Role.user
    if first_user:
        role = Role.admin
    elif body.invite:
        invite = (await db.exec(select(Invite).where(Invite.token_hash == hash_token(body.invite)))).first()
        if not invite or invite.used_at or _aware(invite.expires_at) < datetime.now(UTC):
            raise HTTPException(400, "Einladung ungültig oder abgelaufen")
        if invite.email and invite.email.lower() != body.email.lower():
            raise HTTPException(400, "Einladung gilt für eine andere E-Mail-Adresse")
        role = invite.role
    elif not flags["open_registration"]:
        raise HTTPException(403, "Registrierung nur mit Einladung möglich")

    email = body.email.lower().strip()
    if (await db.exec(select(User).where(func.lower(User.email) == email))).first():
        raise HTTPException(409, "E-Mail bereits registriert")
    user = User(
        email=email,
        display_name=body.display_name or email.split("@")[0],
        password_hash=hash_password(body.password),
        role=role,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    if invite:
        invite.used_at = datetime.now(UTC)
        invite.used_by = user.id
        db.add(invite)
    await audit(db, "register", actor_id=user.id, details={"role": role, "invite": bool(invite)}, ip=client_ip(request))
    from app.services.bootstrap import init_user

    await init_user(db, user)
    await create_session(db, user, request, response)
    return {"user": user_out(user)}


# ---------------------------------------------------------------- password
class ResetIn(BaseModel):
    token: str
    password: str


@router.post("/password/reset")
async def reset_password(body: ResetIn, db: DB) -> dict[str, bool]:
    if err := validate_password(body.password):
        raise HTTPException(422, err)
    pr = (await db.exec(select(PasswordReset).where(PasswordReset.token_hash == hash_token(body.token)))).first()
    if not pr or pr.used or _aware(pr.expires_at) < datetime.now(UTC):
        raise HTTPException(400, "Link ungültig oder abgelaufen")
    user = await db.get(User, pr.user_id)
    user.password_hash = hash_password(body.password)
    pr.used = True
    db.add_all([user, pr])
    # alle Sitzungen beenden
    for s in (await db.exec(select(Session).where(Session.user_id == user.id))).all():
        await db.delete(s)
    await audit(db, "password_reset", actor_id=user.id)
    return {"ok": True}


class ChangePwIn(BaseModel):
    old_password: str | None = None
    new_password: str


@router.post("/password/change")
async def change_password(body: ChangePwIn, user: CurrentUser, db: DB) -> dict[str, bool]:
    if user.password_hash and not verify_password(body.old_password or "", user.password_hash):
        raise HTTPException(400, "Altes Passwort falsch")
    if err := validate_password(body.new_password):
        raise HTTPException(422, err)
    user.password_hash = hash_password(body.new_password)
    db.add(user)
    await audit(db, "password_change", actor_id=user.id)
    return {"ok": True}


# ---------------------------------------------------------------- TOTP
@router.post("/totp/setup")
async def totp_setup(user: CurrentUser, db: DB) -> dict[str, str]:
    secret = pyotp.random_base32()
    user.totp_secret_enc = encrypt(secret)
    user.totp_enabled = False
    db.add(user)
    await db.commit()
    uri = pyotp.TOTP(secret).provisioning_uri(name=user.email, issuer_name=settings.app_name)
    return {"secret": secret, "uri": uri}


class CodeIn(BaseModel):
    code: str


@router.post("/totp/enable")
async def totp_enable(body: CodeIn, user: CurrentUser, db: DB) -> dict[str, bool]:
    secret = decrypt(user.totp_secret_enc)
    if not secret or not pyotp.TOTP(secret).verify(body.code.replace(" ", ""), valid_window=1):
        raise HTTPException(400, "Code ungültig")
    user.totp_enabled = True
    db.add(user)
    await audit(db, "totp_enabled", actor_id=user.id)
    return {"ok": True}


@router.post("/totp/disable")
async def totp_disable(body: CodeIn, user: CurrentUser, db: DB) -> dict[str, bool]:
    secret = decrypt(user.totp_secret_enc)
    if user.totp_enabled and (not secret or not pyotp.TOTP(secret).verify(body.code.replace(" ", ""), valid_window=1)):
        raise HTTPException(400, "Code ungültig")
    user.totp_enabled = False
    user.totp_secret_enc = None
    db.add(user)
    await audit(db, "totp_disabled", actor_id=user.id)
    return {"ok": True}


# ---------------------------------------------------------------- Passkeys (WebAuthn)
def _origin(request: Request) -> str:
    return base_url(request)


@router.get("/passkeys")
async def list_passkeys(user: CurrentUser, db: DB) -> list[dict[str, Any]]:
    rows = (await db.exec(select(WebAuthnCredential).where(WebAuthnCredential.user_id == user.id))).all()
    return [{"id": r.id, "name": r.name, "created_at": r.created_at, "last_used_at": r.last_used_at} for r in rows]


@router.delete("/passkeys/{cred_id}")
async def delete_passkey(cred_id: int, user: CurrentUser, db: DB) -> dict[str, bool]:
    row = await db.get(WebAuthnCredential, cred_id)
    if not row or row.user_id != user.id:
        raise HTTPException(404, "Nicht gefunden")
    await db.delete(row)
    await db.commit()
    return {"ok": True}


@router.post("/passkey/register/options")
async def passkey_register_options(request: Request, user: CurrentUser, response: Response, db: DB) -> Any:
    existing = (await db.exec(select(WebAuthnCredential).where(WebAuthnCredential.user_id == user.id))).all()
    opts = generate_registration_options(
        rp_id=rp_id(request),
        rp_name=settings.webauthn_rp_name,
        user_name=user.email,
        user_id=str(user.id).encode(),
        user_display_name=user.display_name or user.email,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.PREFERRED,
            user_verification=UserVerificationRequirement.PREFERRED,
        ),
        exclude_credentials=[PublicKeyCredentialDescriptor(id=base64url_to_bytes(c.credential_id)) for c in existing],
    )
    _set_challenge(request, response, {"c": bytes_to_base64url(opts.challenge), "u": user.id, "t": "reg"})
    return json.loads(options_to_json(opts))


class PasskeyVerifyIn(BaseModel):
    credential: dict[str, Any]
    name: str = "Passkey"


@router.post("/passkey/register/verify")
async def passkey_register_verify(body: PasskeyVerifyIn, request: Request, user: CurrentUser, db: DB) -> dict[str, bool]:
    ch = _unsign(request.cookies.get(CHALLENGE_COOKIE))
    if ch.get("t") != "reg" or ch.get("u") != user.id:
        raise HTTPException(400, "Ungültige Challenge")
    try:
        ver = verify_registration_response(
            credential=body.credential,
            expected_challenge=base64url_to_bytes(ch["c"]),
            expected_rp_id=rp_id(request),
            expected_origin=_origin(request),
        )
    except Exception as e:  # noqa: BLE001 - webauthn wirft diverse Fehlerklassen
        raise HTTPException(400, f"Passkey-Registrierung fehlgeschlagen: {e}") from e
    db.add(
        WebAuthnCredential(
            user_id=user.id,
            credential_id=bytes_to_base64url(ver.credential_id),
            public_key=bytes_to_base64url(ver.credential_public_key),
            sign_count=ver.sign_count,
            transports=body.credential.get("response", {}).get("transports", []) or [],
            name=body.name[:60] or "Passkey",
        )
    )
    await audit(db, "passkey_added", actor_id=user.id)
    return {"ok": True}


@router.post("/passkey/login/options")
async def passkey_login_options(request: Request, response: Response) -> Any:
    opts = generate_authentication_options(
        rp_id=rp_id(request), user_verification=UserVerificationRequirement.PREFERRED
    )
    _set_challenge(request, response, {"c": bytes_to_base64url(opts.challenge), "t": "auth"})
    return json.loads(options_to_json(opts))


class PasskeyLoginIn(BaseModel):
    credential: dict[str, Any]


@router.post("/passkey/login/verify")
async def passkey_login_verify(body: PasskeyLoginIn, request: Request, response: Response, db: DB) -> dict[str, Any]:
    ch = _unsign(request.cookies.get(CHALLENGE_COOKIE))
    if ch.get("t") != "auth":
        raise HTTPException(400, "Ungültige Challenge")
    cred_id = body.credential.get("id") or body.credential.get("rawId")
    row = (await db.exec(select(WebAuthnCredential).where(WebAuthnCredential.credential_id == cred_id))).first()
    if not row:
        raise HTTPException(401, "Unbekannter Passkey")
    try:
        ver = verify_authentication_response(
            credential=body.credential,
            expected_challenge=base64url_to_bytes(ch["c"]),
            expected_rp_id=rp_id(request),
            expected_origin=_origin(request),
            credential_public_key=base64url_to_bytes(row.public_key),
            credential_current_sign_count=row.sign_count,
        )
    except Exception as e:  # noqa: BLE001
        raise HTTPException(401, f"Passkey ungültig: {e}") from e
    row.sign_count = ver.new_sign_count
    row.last_used_at = datetime.now(UTC)
    db.add(row)
    user = await db.get(User, row.user_id)
    if not user or not user.is_active:
        raise HTTPException(403, "Konto gesperrt")
    response.delete_cookie(CHALLENGE_COOKIE, path="/api/auth")
    await create_session(db, user, request, response)
    await audit(db, "login_passkey", actor_id=user.id, ip=client_ip(request))
    return {"user": user_out(user)}


# ---------------------------------------------------------------- OIDC
_oidc_cache: dict[str, Any] = {}


async def _oidc_meta() -> dict[str, Any]:
    if "meta" not in _oidc_cache:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(settings.oidc_issuer.rstrip("/") + "/.well-known/openid-configuration")
            r.raise_for_status()
            _oidc_cache["meta"] = r.json()
    return _oidc_cache["meta"]


def _oidc_redirect_uri(request: Request) -> str:
    return _origin(request) + "/api/auth/oidc/callback"


@router.get("/oidc/login")
async def oidc_login(request: Request) -> RedirectResponse:
    if not settings.oidc_enabled:
        raise HTTPException(404, "OIDC nicht konfiguriert")
    meta = await _oidc_meta()
    state, nonce = secrets.token_urlsafe(16), secrets.token_urlsafe(16)
    params = {
        "response_type": "code",
        "client_id": settings.oidc_client_id,
        "redirect_uri": _oidc_redirect_uri(request),
        "scope": "openid email profile groups",
        "state": state,
        "nonce": nonce,
    }
    resp = RedirectResponse(meta["authorization_endpoint"] + "?" + urlencode(params))
    resp.set_cookie(
        "ff_oidc", _sign({"s": state, "n": nonce}, minutes=10), max_age=600, httponly=True,
        samesite="lax", secure=secure_cookies(request), path="/api/auth/oidc",
    )
    return resp


@router.get("/oidc/callback")
async def oidc_callback(request: Request, db: DB, code: str = "", state: str = "") -> RedirectResponse:
    if not settings.oidc_enabled:
        raise HTTPException(404, "OIDC nicht konfiguriert")
    stored = _unsign(request.cookies.get("ff_oidc"))
    if stored.get("s") != state:
        raise HTTPException(400, "Ungültiger State")
    meta = await _oidc_meta()
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.post(
            meta["token_endpoint"],
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": _oidc_redirect_uri(request),
                "client_id": settings.oidc_client_id,
                "client_secret": settings.oidc_client_secret,
            },
        )
    if r.status_code != 200:
        raise HTTPException(400, "Token-Austausch fehlgeschlagen")
    id_token = r.json()["id_token"]
    jwk_client = jwt.PyJWKClient(meta["jwks_uri"])
    signing_key = jwk_client.get_signing_key_from_jwt(id_token)
    claims = jwt.decode(
        id_token, signing_key.key, algorithms=["RS256", "ES256", "RS512", "PS256"],
        audience=settings.oidc_client_id, issuer=meta.get("issuer"),
    )
    if claims.get("nonce") != stored.get("n"):
        raise HTTPException(400, "Ungültige Nonce")
    sub, email = claims["sub"], (claims.get("email") or "").lower()
    user = (await db.exec(select(User).where(User.oidc_sub == sub))).first()
    if not user and email and claims.get("email_verified", True):
        user = (await db.exec(select(User).where(func.lower(User.email) == email))).first()
        if user:
            user.oidc_sub = sub
    if not user:
        if not settings.oidc_auto_create or not email:
            return RedirectResponse("/login?error=oidc_no_account")
        is_admin = settings.oidc_admin_group and settings.oidc_admin_group in (claims.get("groups") or [])
        user = User(
            email=email, display_name=claims.get("name") or email.split("@")[0], oidc_sub=sub,
            role=Role.admin if is_admin else Role.user,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        from app.services.bootstrap import init_user

        await init_user(db, user)
    if not user.is_active:
        return RedirectResponse("/login?error=locked")
    resp = RedirectResponse("/")
    await create_session(db, user, request, resp)
    resp.delete_cookie("ff_oidc", path="/api/auth/oidc")
    await audit(db, "login_oidc", actor_id=user.id, ip=client_ip(request))
    return resp


# ---------------------------------------------------------------- API tokens
class TokenIn(BaseModel):
    name: str


@router.get("/tokens")
async def list_tokens(user: CurrentUser, db: DB) -> list[dict[str, Any]]:
    rows = (await db.exec(select(ApiToken).where(ApiToken.user_id == user.id))).all()
    return [
        {"id": r.id, "name": r.name, "prefix": r.prefix, "created_at": r.created_at, "last_used_at": r.last_used_at}
        for r in rows
    ]


@router.post("/tokens")
async def create_token(body: TokenIn, user: CurrentUser, db: DB) -> dict[str, Any]:
    token = new_token("ff_")
    row = ApiToken(user_id=user.id, name=body.name[:80], token_hash=hash_token(token), prefix=token[:10])
    db.add(row)
    await db.commit()
    await db.refresh(row)
    await audit(db, "api_token_created", actor_id=user.id, target=row.name)
    return {"id": row.id, "name": row.name, "token": token}


@router.delete("/tokens/{token_id}")
async def delete_token(token_id: int, user: CurrentUser, db: DB) -> dict[str, bool]:
    row = await db.get(ApiToken, token_id)
    if not row or row.user_id != user.id:
        raise HTTPException(404, "Nicht gefunden")
    await db.delete(row)
    await db.commit()
    return {"ok": True}


@router.get("/sessions")
async def list_sessions(user: CurrentUser, db: DB) -> list[dict[str, Any]]:
    rows = (await db.exec(select(Session).where(Session.user_id == user.id))).all()
    return [{"created_at": r.created_at, "user_agent": r.user_agent, "ip": r.ip} for r in rows]

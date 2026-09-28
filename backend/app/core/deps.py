from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, HTTPException, Query, Request, status
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db import get_session
from app.core.security import hash_token
from app.models import ApiToken, Role, Session, TrainerLink, User

SESSION_COOKIE = "ff_session"
CSRF_HEADER = "x-requested-with"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

DB = Annotated[AsyncSession, Depends(get_session)]


async def _user_from_request(request: Request, db: AsyncSession) -> User | None:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
        row = (await db.exec(select(ApiToken).where(ApiToken.token_hash == hash_token(token)))).first()
        if not row:
            return None
        row.last_used_at = datetime.now(UTC)
        db.add(row)
        await db.commit()
        user = await db.get(User, row.user_id)
        request.state.auth_method = "token"
        return user
    cookie = request.cookies.get(SESSION_COOKIE)
    if not cookie:
        return None
    sess = await db.get(Session, hash_token(cookie))
    if not sess:
        return None
    expires = sess.expires_at if sess.expires_at.tzinfo else sess.expires_at.replace(tzinfo=UTC)
    if expires < datetime.now(UTC):
        await db.delete(sess)
        await db.commit()
        return None
    if request.method not in SAFE_METHODS and request.headers.get(CSRF_HEADER) != "fitforge":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "CSRF-Header fehlt")
    request.state.auth_method = "session"
    return await db.get(User, sess.user_id)


async def optional_user(request: Request, db: DB) -> User | None:
    user = await _user_from_request(request, db)
    if user and not user.is_active:
        return None
    return user


async def current_user(request: Request, db: DB) -> User:
    user = await _user_from_request(request, db)
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Nicht angemeldet")
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Konto gesperrt")
    request.state.user = user
    return user


CurrentUser = Annotated[User, Depends(current_user)]


async def require_admin(user: CurrentUser) -> User:
    if user.role != Role.admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Nur für Administratoren")
    return user


AdminUser = Annotated[User, Depends(require_admin)]


async def subject_user_id(
    user: CurrentUser, db: DB, athlete_id: Annotated[int | None, Query(alias="athlete")] = None
) -> int:
    """Für lesende Endpunkte: Trainer dürfen freigegebene Benutzer ansehen."""
    if athlete_id is None or athlete_id == user.id:
        return user.id
    if user.role not in (Role.trainer, Role.admin):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Kein Zugriff")
    link = (
        await db.exec(
            select(TrainerLink).where(TrainerLink.trainer_id == user.id, TrainerLink.athlete_id == athlete_id)
        )
    ).first()
    if not link:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Keine Freigabe durch diesen Benutzer")
    return athlete_id


SubjectId = Annotated[int, Depends(subject_user_id)]


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else ""

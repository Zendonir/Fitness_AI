"""Zentrale Zugriffshelfer – jede benutzerbezogene Abfrage läuft hierüber."""

from typing import TypeVar

from fastapi import HTTPException, status
from sqlalchemy import and_, or_
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import Role, ShareGrant, User

M = TypeVar("M", bound=SQLModel)

RESOURCE_TYPES = {"plan", "recipe", "food", "exercise"}


def not_found() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, "Nicht gefunden")


def owned(stmt, model, user_id: int):
    return stmt.where(model.user_id == user_id)


async def get_owned(db: AsyncSession, model: type[M], obj_id: int, user_id: int) -> M:
    obj = await db.get(model, obj_id)
    if obj is None or getattr(obj, "user_id", None) != user_id:
        raise not_found()
    return obj


def readable_clause(model, resource_type: str, user_id: int):
    granted = select(ShareGrant.resource_id).where(
        ShareGrant.resource_type == resource_type, ShareGrant.user_id == user_id
    )
    return or_(
        model.owner_id.is_(None),
        model.owner_id == user_id,
        model.visibility == "public",
        and_(model.visibility == "shared", model.id.in_(granted)),
    )


async def can_read(db: AsyncSession, obj, resource_type: str, user_id: int) -> bool:
    if obj.owner_id is None or obj.owner_id == user_id or obj.visibility == "public":
        return True
    if obj.visibility == "shared":
        grant = (
            await db.exec(
                select(ShareGrant).where(
                    ShareGrant.resource_type == resource_type,
                    ShareGrant.resource_id == obj.id,
                    ShareGrant.user_id == user_id,
                )
            )
        ).first()
        return grant is not None
    return False


async def get_readable(db: AsyncSession, model: type[M], resource_type: str, obj_id: int, user: User) -> M:
    obj = await db.get(model, obj_id)
    if obj is None or not await can_read(db, obj, resource_type, user.id):
        raise not_found()
    return obj


async def get_writable(db: AsyncSession, model: type[M], resource_type: str, obj_id: int, user: User) -> M:
    obj = await get_readable(db, model, resource_type, obj_id, user)
    if obj.owner_id == user.id:
        return obj
    if obj.owner_id is None and user.role == Role.admin:
        return obj
    raise HTTPException(status.HTTP_403_FORBIDDEN, "Nur der Eigentümer darf dies ändern")

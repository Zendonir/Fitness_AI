from typing import Any

from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import AuditLog


async def audit(
    db: AsyncSession,
    action: str,
    actor_id: int | None = None,
    target: str = "",
    details: dict[str, Any] | None = None,
    ip: str = "",
    commit: bool = True,
) -> None:
    db.add(AuditLog(actor_id=actor_id, action=action, target=target, details=details or {}, ip=ip))
    if commit:
        await db.commit()

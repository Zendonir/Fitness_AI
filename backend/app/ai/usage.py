"""Kosten-Tracking und Monatslimit pro Benutzer."""

from datetime import UTC, datetime
from typing import Any

from sqlmodel import func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.ai.registry import estimate_cost
from app.models import AIUsage, User
from app.services.app_settings import get_app_setting, system_flags


class AILimitError(Exception):
    pass


class AIDisabledError(Exception):
    pass


def month_start() -> datetime:
    now = datetime.now(UTC)
    return datetime(now.year, now.month, 1, tzinfo=UTC)


async def month_cost(db: AsyncSession, user_id: int) -> float:
    v = (await db.exec(select(func.coalesce(func.sum(AIUsage.cost_usd), 0)).where(AIUsage.user_id == user_id,
                                                                                   AIUsage.created_at >= month_start()))).one()
    return float(v or 0)


async def user_limit(db: AsyncSession, user: User) -> float:
    if user.ai_monthly_limit_usd is not None:
        return float(user.ai_monthly_limit_usd)
    return (await system_flags(db))["default_monthly_limit_usd"]


async def check_limit(db: AsyncSession, user: User) -> None:
    limit = await user_limit(db, user)
    if limit >= 0 and await month_cost(db, user.id) >= limit:
        raise AILimitError(f"Monatliches KI-Budget von {limit:.2f} $ ist aufgebraucht.")


async def record_usage(
    db: AsyncSession, *, user_id: int | None, task: str, provider: str, model: str, input_tokens: int,
    output_tokens: int, duration_ms: int, success: bool = True, error: str | None = None,
    content: dict[str, Any] | None = None,
) -> AIUsage:
    overrides = await get_app_setting(db, "ai_pricing", {})
    row = AIUsage(user_id=user_id, task=task, provider=provider, model=model, input_tokens=input_tokens,
                  output_tokens=output_tokens, cost_usd=estimate_cost(provider, model, input_tokens, output_tokens, overrides)
                  if success or input_tokens else 0.0,
                  duration_ms=duration_ms, success=success, error=(error or "")[:500] or None, content=content)
    db.add(row)
    await db.commit()
    return row

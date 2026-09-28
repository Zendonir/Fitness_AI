"""Web Push (VAPID). iOS unterstützt Push ab 16.4 für installierte PWAs."""

import asyncio
import json
import logging

from pywebpush import WebPushException, webpush
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.models import PushSubscription
from app.services.app_settings import get_user_settings

log = logging.getLogger(__name__)


def push_configured() -> bool:
    return bool(settings.vapid_private_key and settings.vapid_public_key)


def _send(sub: PushSubscription, payload: dict, ttl: int) -> int | None:
    try:
        webpush(
            subscription_info={"endpoint": sub.endpoint, "keys": {"p256dh": sub.p256dh, "auth": sub.auth}},
            data=json.dumps(payload),
            vapid_private_key=settings.vapid_private_key,
            vapid_claims={"sub": settings.vapid_subject},
            ttl=ttl,
        )
        return None
    except WebPushException as e:
        return e.response.status_code if e.response is not None else 0


async def notify_user(
    db: AsyncSession,
    user_id: int,
    title: str,
    body: str,
    url: str = "/",
    kind: str = "hints",
    tag: str | None = None,
    ttl: int = 3600,
) -> int:
    """Sendet an alle Geräte des Benutzers. kind ∈ hints|briefings|timer. Gibt Anzahl zugestellter zurück."""
    if not push_configured():
        return 0
    prefs = (await get_user_settings(db, user_id)).get("ai", {}).get("push", {})
    if prefs.get(kind) is False:
        return 0
    subs = (await db.exec(select(PushSubscription).where(PushSubscription.user_id == user_id))).all()
    payload = {"title": title, "body": body, "url": url, "tag": tag or kind}
    sent = 0
    for sub in subs:
        status = await asyncio.to_thread(_send, sub, payload, ttl)
        if status in (404, 410):
            await db.delete(sub)
        elif status is None:
            sent += 1
        else:
            log.warning("Push an %s fehlgeschlagen: %s", sub.endpoint[:40], status)
    await db.commit()
    return sent

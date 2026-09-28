"""arq-Worker: Zusammenfassungen, Berichte, proaktive Hinweise, Briefings, Push-Timer, Backups.

Start: arq app.worker.WorkerSettings
"""

import logging
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from arq import cron
from arq.connections import RedisSettings
from sqlmodel import select

from app.core import db as dbmod
from app.core.config import settings
from app.models import User
from app.services.app_settings import get_user_settings, system_flags

log = logging.getLogger("fitforge.worker")
TZ = ZoneInfo(settings.tz)


async def _active_users() -> list[int]:
    async with dbmod.session_scope() as db:
        return list((await db.exec(select(User.id).where(User.is_active))).all())


async def _for_each_user(fn, *args: Any) -> int:
    n = 0
    for uid in await _active_users():
        try:
            async with dbmod.session_scope() as db:
                user = await db.get(User, uid)
                await fn(db, user, *args)
                n += 1
        except Exception:  # noqa: BLE001 - ein Benutzer darf die anderen nicht blockieren
            log.exception("Job %s für Benutzer %s fehlgeschlagen", getattr(fn, "__name__", fn), uid)
    return n


async def daily_summaries_job(ctx: dict) -> int:
    from app.ai.jobs import daily_summary

    return await _for_each_user(daily_summary, date.today() - timedelta(days=1))


async def weekly_reports_job(ctx: dict) -> int:
    from app.ai.jobs import run_weekly

    return await _for_each_user(run_weekly)


async def monthly_reports_job(ctx: dict) -> int:
    if date.today().day != 1:
        return 0
    from app.ai.jobs import run_monthly

    return await _for_each_user(run_monthly)


async def hints_job(ctx: dict) -> int:
    from app.ai.jobs import detect_hints

    return await _for_each_user(detect_hints)


def _due(hhmm: str, now: datetime, window_min: int = 5) -> bool:
    try:
        h, m = (int(x) for x in hhmm.split(":"))
    except ValueError:
        return False
    target = now.replace(hour=h, minute=m, second=0, microsecond=0)
    return target <= now < target + timedelta(minutes=window_min)


async def briefings_job(ctx: dict) -> int:
    from app.ai.jobs import briefing

    now = datetime.now(TZ)
    sent = 0
    for uid in await _active_users():
        try:
            async with dbmod.session_scope() as db:
                s = (await get_user_settings(db, uid))["ai"]
                if not s.get("proactive", {}).get("enabled", True):
                    continue
                b = s.get("briefing", {})
                user = await db.get(User, uid)
                if b.get("morning_enabled") and _due(b.get("morning_time", "07:00"), now):
                    sent += bool(await briefing(db, user, "morning"))
                if b.get("evening_enabled") and _due(b.get("evening_time", "20:30"), now):
                    sent += bool(await briefing(db, user, "evening"))
        except Exception:  # noqa: BLE001
            log.exception("Briefing für %s fehlgeschlagen", uid)
    return sent


async def timer_push_job(ctx: dict, user_id: int, token: str, exercise: str = "") -> bool:
    redis = ctx["redis"]
    current = await redis.get(f"ff:timer:{user_id}")
    if (current.decode() if isinstance(current, bytes) else current) != token:
        return False  # abgebrochen oder durch neueren Timer ersetzt
    from app.services.push import notify_user

    async with dbmod.session_scope() as db:
        await notify_user(db, user_id, "Pause vorbei ⏱️", f"Weiter geht's{': ' + exercise if exercise else ''}!",
                          url="/training/live", kind="timer", tag="rest-timer", ttl=120)
    await redis.delete(f"ff:timer:{user_id}")
    return True


async def backup_job(ctx: dict) -> dict:
    from app.services.backup import run_backup

    return await run_backup()


async def cleanup_job(ctx: dict) -> None:
    """Abgelaufene Sessions und alte offene Aktionen entfernen."""
    from datetime import UTC

    from app.models import PendingAction, Session

    async with dbmod.session_scope() as db:
        now = datetime.now(UTC)
        for s in (await db.exec(select(Session).where(Session.expires_at < now))).all():
            await db.delete(s)
        for a in (await db.exec(select(PendingAction).where(PendingAction.status == "pending",
                                                            PendingAction.created_at < now - timedelta(days=7)))).all():
            a.status = "expired"
            db.add(a)
        await db.commit()


async def startup(ctx: dict) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    async with dbmod.session_scope() as db:
        flags = await system_flags(db)
    log.info("Worker gestartet (KI %s)", "aktiv" if flags["ai_enabled"] else "aus")


class WorkerSettings:
    functions = [timer_push_job, backup_job, daily_summaries_job, weekly_reports_job, hints_job, briefings_job]
    cron_jobs = [
        cron(briefings_job, minute=set(range(0, 60, 5)), run_at_startup=False),
        cron(daily_summaries_job, hour={2}, minute={30}),
        cron(weekly_reports_job, weekday={0}, hour={5}, minute={0}),
        cron(monthly_reports_job, hour={5}, minute={30}),
        cron(hints_job, hour={9, 13, 18}, minute={15}),
        cron(backup_job, hour={settings.backup_hour}, minute={0}),
        cron(cleanup_job, hour={4}, minute={10}),
    ]
    on_startup = startup
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    timezone = TZ
    max_jobs = 4
    job_timeout = 900

"""Lokale Lebensmittelsuche über eigene Lebensmittel, BLS (generische Gerichte) und den Open-Food-Facts-Cache."""

import re

from sqlalchemy import or_
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.access import readable_clause
from app.models import Food

_UMLAUTS = (("ae", "ä"), ("oe", "ö"), ("ue", "ü"), ("ss", "ß"))


def variants(token: str) -> set[str]:
    out = {token}
    for a, b in _UMLAUTS:
        out |= {v.replace(a, b) for v in list(out)} | {v.replace(b, a) for v in list(out)}
    return out


def tokens(q: str) -> list[str]:
    return [t for t in re.split(r"[\s,/]+", q.lower().strip()) if len(t) >= 2][:6]


def score(f: Food, toks: list[str], user_id: int) -> tuple:
    name = f.name.lower()
    source_rank = 0 if f.owner_id == user_id else 1 if f.source == "bls" else 2 if f.owner_id else 3
    first = toks[0] if toks else ""
    starts = 0 if any(name.startswith(v) for v in variants(first)) else 1
    word_start = 0 if all(any(re.search(r"(^|[\s,(/-])" + re.escape(v), name) for v in variants(t)) for t in toks) else 1
    return (starts, source_rank, word_start, len(name))


async def search_local(db: AsyncSession, user_id: int, q: str, limit: int = 40) -> list[Food]:
    toks = tokens(q)
    if not toks:
        return []
    stmt = select(Food).where(readable_clause(Food, "food", user_id))
    for t in toks:
        stmt = stmt.where(or_(*[col(Food.name).ilike(f"%{v}%") for v in variants(t)],
                              *[col(Food.brand).ilike(f"%{v}%") for v in variants(t)]))
    rows = (await db.exec(stmt.limit(500))).all()
    return sorted(rows, key=lambda f: score(f, toks, user_id))[:limit]

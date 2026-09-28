import io
import uuid
from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from PIL import Image, ImageOps
from pydantic import BaseModel, Field
from sqlmodel import select

from app.core.access import get_owned
from app.core.config import settings
from app.core.deps import DB, CurrentUser, SubjectId
from app.models import BodyMeasurement, MetricDefinition, MetricEntry, ProgressPhoto

router = APIRouter(tags=["body"])

BODY_FIELDS = ("weight_kg", "body_fat_pct", "waist_cm", "chest_cm", "hips_cm", "arm_cm", "thigh_cm", "neck_cm")


def rolling_avg(points: list[tuple[date, float]], window: int = 7) -> list[dict[str, Any]]:
    """Gleitender Mittelwert über die letzten `window` Kalendertage (nur vorhandene Messungen)."""
    out = []
    for i, (d, v) in enumerate(points):
        vals = [pv for pd, pv in points[: i + 1] if (d - pd).days < window]
        out.append({"day": d, "value": v, "avg": round(sum(vals) / len(vals), 2)})
    return out


# ================================================================ Körperwerte
class BodyIn(BaseModel):
    day: date | None = None
    weight_kg: float | None = Field(None, gt=20, lt=400)
    body_fat_pct: float | None = Field(None, ge=2, le=70)
    waist_cm: float | None = None
    chest_cm: float | None = None
    hips_cm: float | None = None
    arm_cm: float | None = None
    thigh_cm: float | None = None
    neck_cm: float | None = None
    notes: str = ""
    source: str = "manual"
    client_id: str | None = None


@router.get("/body")
async def list_body(subject: SubjectId, db: DB, days: int = 90) -> dict[str, Any]:
    since = date.today() - timedelta(days=days)
    rows = (
        await db.exec(select(BodyMeasurement).where(BodyMeasurement.user_id == subject, BodyMeasurement.day >= since - timedelta(days=7))
                      .order_by(BodyMeasurement.day, BodyMeasurement.created_at))
    ).all()
    weights: dict[date, float] = {}
    for r in rows:
        if r.weight_kg:
            weights[r.day] = r.weight_kg  # letzter Wert des Tages
    trend = [p for p in rolling_avg(sorted(weights.items())) if p["day"] >= since]
    latest = {f: next((getattr(r, f) for r in reversed(rows) if getattr(r, f) is not None), None) for f in BODY_FIELDS}
    change_7 = None
    if len(trend) >= 2:
        last = trend[-1]
        prev = next((p for p in reversed(trend) if (last["day"] - p["day"]).days >= 7), None)
        if prev:
            change_7 = round(last["avg"] - prev["avg"], 2)
    return {
        "entries": [r.model_dump() for r in rows if r.day >= since][::-1],
        "weight_trend": trend,
        "latest": latest,
        "weekly_change_kg": change_7,
    }


@router.post("/body")
async def add_body(body: BodyIn, user: CurrentUser, db: DB) -> dict[str, Any]:
    if body.client_id:
        ex = (await db.exec(select(BodyMeasurement).where(BodyMeasurement.user_id == user.id, BodyMeasurement.client_id == body.client_id))).first()
        if ex:
            return ex.model_dump()
    m = BodyMeasurement(user_id=user.id, **{**body.model_dump(), "day": body.day or date.today()})
    db.add(m)
    await db.commit()
    await db.refresh(m)
    return m.model_dump()


@router.patch("/body/{bid}")
async def patch_body(bid: int, body: dict[str, Any], user: CurrentUser, db: DB) -> dict[str, Any]:
    m = await get_owned(db, BodyMeasurement, bid, user.id)
    for k in (*BODY_FIELDS, "notes", "day"):
        if k in body:
            setattr(m, k, date.fromisoformat(body[k]) if k == "day" else body[k])
    db.add(m)
    await db.commit()
    return m.model_dump()


@router.delete("/body/{bid}")
async def delete_body(bid: int, user: CurrentUser, db: DB) -> dict[str, bool]:
    m = await get_owned(db, BodyMeasurement, bid, user.id)
    await db.delete(m)
    await db.commit()
    return {"ok": True}


# ================================================================ Fortschrittsfotos (lokal gespeichert)
def _photo_dir(user_id: int):
    d = settings.uploads_dir / str(user_id) / "photos"
    d.mkdir(parents=True, exist_ok=True)
    return d


def process_image(raw: bytes, max_side: int = 1600) -> bytes:
    """Orientierung korrigieren, EXIF (inkl. GPS) entfernen, verkleinern, als JPEG speichern."""
    img = Image.open(io.BytesIO(raw))
    img = ImageOps.exif_transpose(img).convert("RGB")
    img.thumbnail((max_side, max_side))
    out = io.BytesIO()
    img.save(out, "JPEG", quality=85, optimize=True)
    return out.getvalue()


@router.get("/photos")
async def list_photos(user: CurrentUser, db: DB) -> list[dict[str, Any]]:
    rows = (await db.exec(select(ProgressPhoto).where(ProgressPhoto.user_id == user.id).order_by(ProgressPhoto.day.desc()))).all()
    return [{**r.model_dump(exclude={"filename"}), "url": f"/api/photos/{r.id}/file"} for r in rows]


@router.post("/photos")
async def upload_photo(
    user: CurrentUser, db: DB, file: UploadFile = File(...), day: date | None = Form(None),
    pose: str = Form("front"), note: str = Form(""),
) -> dict[str, Any]:
    raw = await file.read()
    if len(raw) > 25 * 1024 * 1024:
        raise HTTPException(413, "Foto zu groß (max. 25 MB)")
    try:
        data = process_image(raw)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(422, "Bild konnte nicht gelesen werden") from e
    name = f"{uuid.uuid4().hex}.jpg"
    (_photo_dir(user.id) / name).write_bytes(data)
    p = ProgressPhoto(user_id=user.id, day=day or date.today(), filename=name, pose=pose, note=note[:200])
    db.add(p)
    await db.commit()
    await db.refresh(p)
    return {**p.model_dump(exclude={"filename"}), "url": f"/api/photos/{p.id}/file"}


@router.get("/photos/{pid}/file")
async def photo_file(pid: int, user: CurrentUser, db: DB) -> FileResponse:
    p = await get_owned(db, ProgressPhoto, pid, user.id)
    path = _photo_dir(user.id) / p.filename
    if not path.exists():
        raise HTTPException(404, "Datei fehlt")
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})


@router.delete("/photos/{pid}")
async def delete_photo(pid: int, user: CurrentUser, db: DB) -> dict[str, bool]:
    p = await get_owned(db, ProgressPhoto, pid, user.id)
    (_photo_dir(user.id) / p.filename).unlink(missing_ok=True)
    await db.delete(p)
    await db.commit()
    return {"ok": True}


# ================================================================ Eigene Metriken
class MetricIn(BaseModel):
    name: str
    kind: str = Field("number", pattern="^(number|scale|bool|text)$")
    unit: str = ""
    scale_min: float | None = 1
    scale_max: float | None = 10
    target: float | None = None
    chart: str = "line"
    color: str | None = None
    position: int = 0
    archived: bool = False


class MetricEntryIn(BaseModel):
    metric_id: int
    day: date | None = None
    value: float | bool | str | None = None


@router.get("/metrics")
async def list_metrics(subject: SubjectId, db: DB) -> list[dict[str, Any]]:
    rows = (await db.exec(select(MetricDefinition).where(MetricDefinition.user_id == subject).order_by(MetricDefinition.position))).all()
    out = []
    for m in rows:
        last = (await db.exec(select(MetricEntry).where(MetricEntry.metric_id == m.id).order_by(MetricEntry.day.desc()).limit(1))).first()
        out.append({**m.model_dump(), "last": last.model_dump() if last else None})
    return out


@router.post("/metrics")
async def create_metric(body: MetricIn, user: CurrentUser, db: DB) -> dict[str, Any]:
    m = MetricDefinition(user_id=user.id, **body.model_dump())
    db.add(m)
    await db.commit()
    await db.refresh(m)
    return m.model_dump()


@router.patch("/metrics/{mid}")
async def patch_metric(mid: int, body: dict[str, Any], user: CurrentUser, db: DB) -> dict[str, Any]:
    m = await get_owned(db, MetricDefinition, mid, user.id)
    for k in MetricIn.model_fields:
        if k in body:
            setattr(m, k, body[k])
    db.add(m)
    await db.commit()
    return m.model_dump()


@router.delete("/metrics/{mid}")
async def delete_metric(mid: int, user: CurrentUser, db: DB) -> dict[str, bool]:
    m = await get_owned(db, MetricDefinition, mid, user.id)
    await db.delete(m)
    await db.commit()
    return {"ok": True}


@router.get("/metrics/{mid}/entries")
async def metric_entries(mid: int, subject: SubjectId, db: DB, days: int = 90) -> list[dict[str, Any]]:
    await get_owned(db, MetricDefinition, mid, subject)
    since = date.today() - timedelta(days=days)
    rows = (await db.exec(select(MetricEntry).where(MetricEntry.metric_id == mid, MetricEntry.user_id == subject,
                                                    MetricEntry.day >= since).order_by(MetricEntry.day))).all()
    return [r.model_dump() for r in rows]


def _coerce(m: MetricDefinition, value: Any) -> tuple[float | None, str | None]:
    if m.kind == "text":
        return None, str(value or "")[:2000]
    if m.kind == "bool":
        return (1.0 if value in (True, 1, "1", "true", "ja") else 0.0), None
    try:
        v = float(value)
    except (TypeError, ValueError) as e:
        raise HTTPException(422, "Zahl erwartet") from e
    if m.kind == "scale" and m.scale_min is not None and m.scale_max is not None and not (m.scale_min <= v <= m.scale_max):
        raise HTTPException(422, f"Wert muss zwischen {m.scale_min:g} und {m.scale_max:g} liegen")
    return v, None


@router.post("/metrics/entries")
async def add_metric_entry(body: MetricEntryIn, user: CurrentUser, db: DB) -> dict[str, Any]:
    m = await get_owned(db, MetricDefinition, body.metric_id, user.id)
    num, txt = _coerce(m, body.value)
    day = body.day or date.today()
    existing = (await db.exec(select(MetricEntry).where(MetricEntry.metric_id == m.id, MetricEntry.day == day))).first()
    e = existing or MetricEntry(user_id=user.id, metric_id=m.id, day=day)
    e.value_num, e.value_text = num, txt
    db.add(e)
    await db.commit()
    await db.refresh(e)
    return e.model_dump()


@router.delete("/metrics/entries/{eid}")
async def delete_metric_entry(eid: int, user: CurrentUser, db: DB) -> dict[str, bool]:
    e = await get_owned(db, MetricEntry, eid, user.id)
    await db.delete(e)
    await db.commit()
    return {"ok": True}

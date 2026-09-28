"""Import von Ausdauereinheiten aus GPX und CSV."""

import csv
import io
from datetime import UTC, datetime
from typing import Any

import gpxpy

KIND_ALIASES = {
    "run": "run", "running": "run", "laufen": "run", "lauf": "run", "joggen": "run",
    "bike": "bike", "cycling": "bike", "rad": "bike", "radfahren": "bike", "ride": "bike", "biking": "bike",
    "row": "row", "rowing": "row", "rudern": "row",
    "walk": "walk", "walking": "walk", "gehen": "walk", "wandern": "walk", "hiking": "walk",
    "swim": "swim", "swimming": "swim", "schwimmen": "swim",
}


def _hr_from_point(p) -> int | None:
    for ext in p.extensions or []:
        for el in ext.iter():
            if el.tag.lower().endswith("hr") and el.text:
                try:
                    return int(float(el.text))
                except ValueError:
                    return None
    return None


def parse_gpx(content: bytes | str, kind: str | None = None) -> dict[str, Any]:
    gpx = gpxpy.parse(content.decode() if isinstance(content, bytes) else content)
    points = [p for t in gpx.tracks for s in t.segments for p in s.points]
    if not points:
        raise ValueError("GPX enthält keine Trackpunkte")
    start = points[0].time or datetime.now(UTC)
    end = points[-1].time or start
    hrs = [h for p in points if (h := _hr_from_point(p))]
    up, _down = gpx.get_uphill_downhill()
    step = max(1, len(points) // 500)
    track = [
        [round(p.latitude, 6), round(p.longitude, 6), round(p.elevation or 0, 1),
         int(((p.time or start) - start).total_seconds())]
        for p in points[::step]
    ]
    guessed = kind
    if not guessed and gpx.tracks and gpx.tracks[0].type:
        guessed = KIND_ALIASES.get(gpx.tracks[0].type.lower())
    return {
        "kind": guessed or "run",
        "started_at": start if start.tzinfo else start.replace(tzinfo=UTC),
        "duration_s": int((end - start).total_seconds()),
        "distance_m": round(gpx.length_3d() or gpx.length_2d() or 0, 1),
        "elevation_m": round(up or 0, 1),
        "avg_hr": round(sum(hrs) / len(hrs)) if hrs else None,
        "max_hr": max(hrs) if hrs else None,
        "track": track,
        "source": "gpx",
    }


def _duration(v: str) -> int:
    v = v.strip()
    if ":" in v:
        parts = [float(x) for x in v.split(":")]
        while len(parts) < 3:
            parts.insert(0, 0)
        h, m, s = parts
        return int(h * 3600 + m * 60 + s)
    return int(float(v.replace(",", ".")))


def _num(v: str | None) -> float | None:
    if v is None or str(v).strip() == "":
        return None
    return float(str(v).replace(",", "."))


def _date(v: str) -> datetime:
    v = v.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M", "%d.%m.%Y %H:%M", "%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(v, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    return datetime.fromisoformat(v)


def parse_csv(content: bytes | str) -> list[dict[str, Any]]:
    """Erwartete Spalten (flexibel benannt): date, type, duration, distance_km|distance_m, avg_hr, max_hr, kcal."""
    text = content.decode("utf-8-sig") if isinstance(content, bytes) else content
    try:
        dialect = csv.Sniffer().sniff(text.splitlines()[0], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    rows = list(csv.DictReader(io.StringIO(text), dialect=dialect))
    out = []
    for r in rows:
        row = {k.strip().lower(): (v or "").strip() for k, v in r.items() if k}
        date_v = row.get("date") or row.get("datum") or row.get("start") or row.get("started_at")
        if not date_v:
            continue
        dist_m = None
        if row.get("distance_km") or row.get("distanz_km"):
            dist_m = (_num(row.get("distance_km") or row.get("distanz_km")) or 0) * 1000
        elif row.get("distance_m") or row.get("distance"):
            dist_m = _num(row.get("distance_m") or row.get("distance"))
        kind_raw = (row.get("type") or row.get("typ") or row.get("sport") or "run").lower()
        out.append(
            {
                "kind": KIND_ALIASES.get(kind_raw, "other"),
                "started_at": _date(date_v),
                "duration_s": _duration(row.get("duration") or row.get("dauer") or "0"),
                "distance_m": dist_m,
                "avg_hr": int(v) if (v := _num(row.get("avg_hr") or row.get("puls"))) else None,
                "max_hr": int(v) if (v := _num(row.get("max_hr"))) else None,
                "kcal": _num(row.get("kcal") or row.get("calories")),
                "source": "csv",
            }
        )
    return out

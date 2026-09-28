import json
from datetime import date, datetime, timedelta

from app.services.backup import select_keep


async def test_home_assistant_summary_with_token(make_user, anon_client):
    c = await make_user()
    tok = (await c.post("/api/auth/tokens", json={"name": "HA"})).json()["token"]
    await c.post("/api/meals", json={"name": "Müsli", "kcal": 500, "protein": 20})
    await c.post("/api/body", json={"weight_kg": 81.2})
    r = await anon_client.get("/api/ha/summary", headers={"Authorization": f"Bearer {tok}"})
    d = r.json()
    assert d["kcal_today"] == 500 and d["protein_today"] == 20 and d["weight_avg_7d"] == 81.2
    assert (await anon_client.get("/api/ha/summary")).status_code == 401


async def test_apple_health_import(make_user):
    c = await make_user()
    body = {"date": date.today().isoformat(), "weight_kg": 80.4, "body_fat_pct": 0.18, "steps": 9500, "sleep_hours": 7.2,
            "workouts": [{"type": "Laufen", "start": datetime.now().isoformat(), "duration_min": 30, "distance_km": 5.2}]}
    r = (await c.post("/api/integrations/apple-health", json=body)).json()
    assert r["workouts_added"] == 1 and r["steps"] == 9500
    r2 = (await c.post("/api/integrations/apple-health", json={**body, "weight_kg": 80.1})).json()
    assert r2["workouts_added"] == 0
    b = (await c.get("/api/body")).json()
    assert b["latest"]["weight_kg"] == 80.1 and b["latest"]["body_fat_pct"] == 18.0
    assert len([e for e in b["entries"] if e["source"] == "health"]) == 1
    metrics = {m["name"]: m for m in (await c.get("/api/metrics")).json()}
    assert metrics["Schritte"]["last"]["value_num"] == 9500
    raw = (await c.post("/api/integrations/apple-health/raw", json={"weight_kg": "79,9 kg", "steps": "10.000"})).json()
    assert raw["steps"] == 10000


async def test_export_import_roundtrip(make_user):
    a = await make_user()
    ex = (await a.post("/api/exercises", json={"name": "Meine Übung", "primary_muscles": ["chest"]})).json()
    glob = (await a.get("/api/exercises")).json()[0]
    await a.post("/api/workouts", json={"name": "W", "sets": [{"exercise_id": ex["id"], "reps": 5, "weight_kg": 50},
                                                              {"exercise_id": glob["id"], "reps": 8, "weight_kg": 30}]})
    f = (await a.post("/api/foods", json={"name": "Mein Brot", "kcal": 250})).json()
    await a.post("/api/recipes", json={"name": "Stulle", "ingredients": [{"food_id": f["id"], "grams": 80}]})
    await a.post("/api/meals", json={"food_id": f["id"], "grams": 100})
    m = (await a.post("/api/metrics", json={"name": "Schlaf"})).json()
    await a.post("/api/metrics/entries", json={"metric_id": m["id"], "value": 7})
    export = (await a.get("/api/me/export")).json()
    assert export["tables"]["workout_set"] and export["tables"]["food"][0]["name"] == "Mein Brot"
    csv_zip = await a.get("/api/me/export?format=csv")
    assert csv_zip.headers["content-type"] == "application/zip"
    b = await make_user()
    r = await b.post("/api/me/import", files={"file": ("e.json", json.dumps(export).encode(), "application/json")})
    counts = r.json()["imported"]
    assert counts["workout_set"] == 2 and counts["recipe_ingredient"] == 1 and counts["metric_entry"] == 1
    w = (await b.get("/api/workouts")).json()
    assert w[0]["sets_count"] == 2
    assert (await b.get("/api/meals")).json()["totals"]["kcal"] == 250


def test_backup_retention():
    now = datetime(2026, 9, 28, 3)
    stamps = [now - timedelta(days=i) for i in range(120)]
    keep = select_keep(stamps, daily=7, weekly=4, monthly=6)
    assert all(now - timedelta(days=i) in keep for i in range(7))
    assert len(keep) <= 7 + 4 + 6
    assert min(keep) < now - timedelta(days=60)

import io


async def _ex(c, slug="bench_press"):
    exs = (await c.get("/api/exercises", params={"q": "Bankdrücken"})).json()
    return next(e for e in exs if e["slug"] == slug)


async def test_library_seeded(make_user):
    c = await make_user()
    exs = (await c.get("/api/exercises")).json()
    assert len(exs) >= 80
    plans = (await c.get("/api/plans")).json()
    assert {p["name"] for p in plans if p["kind"] == "template"} >= {"Ganzkörper 3x", "Upper/Lower 4x", "Push/Pull/Legs 6x"}


async def test_plan_activate_and_live_workout(make_user):
    c = await make_user()
    tpl = next(p for p in (await c.get("/api/plans")).json() if p["name"] == "Ganzkörper 3x")
    plan = (await c.post(f"/api/plans/{tpl['id']}/activate")).json()
    assert plan["own"] and plan["is_active"]
    today = (await c.get("/api/training/today")).json()
    assert today["active_plan"]
    day_id = plan["days"][0]["id"]
    live = (await c.post("/api/workouts/start", json={"plan_day_id": day_id})).json()
    assert live["exercises"][0]["suggestion"]["action"] == "start"
    ex_id = live["exercises"][0]["exercise_id"]
    for _ in range(3):
        r = await c.post(f"/api/workouts/{live['id']}/sets", json={"exercise_id": ex_id, "reps": 10, "weight_kg": 60})
        assert r.status_code == 200
    fin = (await c.post(f"/api/workouts/{live['id']}/finish")).json()
    assert fin["finished_at"]
    # zweites Workout: Vorschlag basiert auf Vorwerten, PR wird erkannt
    live2 = (await c.post("/api/workouts/start", json={"plan_day_id": day_id})).json()
    sugg = live2["exercises"][0]["suggestion"]
    assert sugg["weight_kg"] == 60 and sugg["reps"] == 10 + 1 or sugg["action"] in ("increase", "add_reps")
    await c.post(f"/api/workouts/{live2['id']}/sets", json={"exercise_id": ex_id, "reps": 8, "weight_kg": 70})
    fin2 = (await c.post(f"/api/workouts/{live2['id']}/finish")).json()
    assert any(p["type"] == "weight" for p in fin2["prs"])


async def test_workout_client_id_idempotent(make_user):
    c = await make_user()
    ex = await _ex(c)
    body = {"client_id": "abc-1", "name": "Offline", "sets": [{"exercise_id": ex["id"], "reps": 5, "weight_kg": 80}]}
    a = (await c.post("/api/workouts", json=body)).json()
    b = (await c.post("/api/workouts", json=body)).json()
    assert a["id"] == b["id"]


async def test_custom_plan_editor(make_user):
    c = await make_user()
    ex = await _ex(c)
    body = {"name": "Mein Plan", "weeks": 4, "deload_weeks": [4], "days": [
        {"name": "Tag 1", "exercises": [{"exercise_id": ex["id"], "sets": 4, "rep_min": 5, "rep_max": 8}]},
        {"name": "Tag 2", "exercises": []}]}
    p = (await c.post("/api/plans", json=body)).json()
    assert len(p["days"]) == 2 and p["days"][0]["exercises"][0]["sets"] == 4
    body["days"].reverse()
    p = (await c.put(f"/api/plans/{p['id']}", json=body)).json()
    assert p["days"][0]["name"] == "Tag 2"


async def test_custom_exercise_and_sharing(make_user):
    a = await make_user()
    b = await make_user()
    e = (await a.post("/api/exercises", json={"name": "Landmine Press", "primary_muscles": ["front_delts"]})).json()
    assert (await b.get(f"/api/exercises/{e['id']}")).status_code == 404
    await a.put(f"/api/share/exercise/{e['id']}", json={"visibility": "shared", "user_ids": [b.user["id"]]})
    assert (await b.get(f"/api/exercises/{e['id']}")).status_code == 200
    # b darf nicht ändern
    assert (await b.patch(f"/api/exercises/{e['id']}", json={"name": "x"})).status_code == 403
    # b darf Freigabe nicht ändern
    r = await b.put(f"/api/share/exercise/{e['id']}", json={"visibility": "public"})
    assert r.status_code == 403
    await a.put(f"/api/share/exercise/{e['id']}", json={"visibility": "private"})
    assert (await b.get(f"/api/exercises/{e['id']}")).status_code == 404


async def test_templates_readonly_for_users(make_user):
    c = await make_user()
    tpl = next(p for p in (await c.get("/api/plans")).json() if p["kind"] == "template")
    r = await c.put(f"/api/plans/{tpl['id']}", json={"name": "hack", "days": []})
    assert r.status_code == 403
    assert (await c.delete(f"/api/plans/{tpl['id']}")).status_code == 403


GPX = b"""<?xml version="1.0"?>
<gpx version="1.1" creator="t" xmlns="http://www.topografix.com/GPX/1/1"
 xmlns:gpxtpx="http://www.garmin.com/xmlschemas/TrackPointExtension/v1">
<trk><type>running</type><trkseg>
<trkpt lat="52.5200" lon="13.4050"><ele>34</ele><time>2026-09-01T07:00:00Z</time><extensions><gpxtpx:TrackPointExtension><gpxtpx:hr>140</gpxtpx:hr></gpxtpx:TrackPointExtension></extensions></trkpt>
<trkpt lat="52.5300" lon="13.4050"><ele>40</ele><time>2026-09-01T07:06:00Z</time><extensions><gpxtpx:TrackPointExtension><gpxtpx:hr>160</gpxtpx:hr></gpxtpx:TrackPointExtension></extensions></trkpt>
</trkseg></trk></gpx>"""


async def test_gpx_and_csv_import(make_user):
    c = await make_user()
    r = await c.post("/api/cardio/import", files={"file": ("run.gpx", io.BytesIO(GPX), "application/gpx+xml")})
    assert r.json() == {"imported": 1, "skipped": 0}
    r = await c.post("/api/cardio/import", files={"file": ("run.gpx", io.BytesIO(GPX), "application/gpx+xml")})
    assert r.json()["skipped"] == 1
    rows = (await c.get("/api/cardio")).json()
    assert rows[0]["kind"] == "run" and rows[0]["duration_s"] == 360 and 1000 < rows[0]["distance_m"] < 1200
    assert rows[0]["avg_hr"] == 150
    csv_data = "date;type;duration;distance_km;avg_hr\n2026-09-02 18:00;Rad;1:05:00;30,5;135\n"
    r = await c.post("/api/cardio/import", files={"file": ("a.csv", io.BytesIO(csv_data.encode()), "text/csv")})
    assert r.json()["imported"] == 1
    rows = (await c.get("/api/cardio")).json()
    bike = next(x for x in rows if x["kind"] == "bike")
    assert bike["duration_s"] == 3900 and bike["distance_m"] == 30500


async def test_exercise_media(make_user, anon_client):
    from sqlmodel import select

    from app.core.db import session_scope
    from app.models import Exercise
    from app.services.bootstrap import seed_database

    cfg = (await anon_client.get("/api/auth/config")).json()
    assert cfg["exercise_media_base"].startswith("https://cdn.jsdelivr.net/gh/JahelCuadrado/ExerciseGymGifsDB@")
    c = await make_user()
    exs = (await c.get("/api/exercises")).json()
    bench = next(e for e in exs if e["slug"] == "bench_press")
    assert bench["media_id"] == "pectorals/barbell-bench-press"
    assert sum(1 for e in exs if e["owner_id"] is None and e["media_id"]) >= 80
    # eigene Übung mit Animation aus der Bibliothek
    own = (await c.post("/api/exercises", json={"name": "Kabel-Curl Seil", "media_id": "biceps/cable-hammer-curl-with-rope",
                                                 "primary_muscles": ["biceps"]})).json()
    assert own["media_id"] == "biceps/cable-hammer-curl-with-rope"
    assert (await c.post("/api/exercises", json={"name": "x", "media_id": "../../etc/passwd"})).status_code == 422
    upd = (await c.patch(f"/api/exercises/{own['id']}", json={"media_id": None})).json()
    assert upd["media_id"] is None
    # Bestehende Installationen: fehlende Zuordnungen werden beim Start nachgetragen
    async with session_scope() as db:
        e = (await db.exec(select(Exercise).where(Exercise.slug == "bench_press", Exercise.owner_id.is_(None)))).first()
        e.media_id = None
        db.add(e)
        await db.commit()
        await seed_database(db)
        await db.refresh(e)
        assert e.media_id == "pectorals/barbell-bench-press"

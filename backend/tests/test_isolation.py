"""Strikte Datentrennung: Benutzer B sieht/ändert nie Daten von Benutzer A."""


async def test_workouts_isolated(make_user):
    a = await make_user()
    b = await make_user()
    ex = (await a.get("/api/exercises")).json()[0]
    w = (await a.post("/api/workouts/start", json={"name": "A"})).json()
    s = (await a.post(f"/api/workouts/{w['id']}/sets", json={"exercise_id": ex["id"], "reps": 5, "weight_kg": 50})).json()
    assert (await b.get(f"/api/workouts/{w['id']}")).status_code == 404
    assert (await b.get(f"/api/workouts/{w['id']}/live")).status_code == 404
    assert (await b.patch(f"/api/workouts/{w['id']}", json={"name": "hack"})).status_code == 404
    assert (await b.post(f"/api/workouts/{w['id']}/sets", json={"exercise_id": ex["id"]})).status_code == 404
    assert (await b.patch(f"/api/sets/{s['id']}", json={"reps": 99})).status_code == 404
    assert (await b.delete(f"/api/sets/{s['id']}")).status_code == 404
    assert (await b.delete(f"/api/workouts/{w['id']}")).status_code == 404
    assert all(x["id"] != w["id"] for x in (await b.get("/api/workouts")).json())
    assert (await a.get(f"/api/workouts/{w['id']}")).json()["sets"][0]["reps"] == 5


async def test_plans_isolated(make_user):
    a = await make_user()
    b = await make_user()
    p = (await a.post("/api/plans", json={"name": "Privat", "days": []})).json()
    assert (await b.get(f"/api/plans/{p['id']}")).status_code == 404
    assert (await b.put(f"/api/plans/{p['id']}", json={"name": "x", "days": []})).status_code == 404
    assert (await b.post(f"/api/plans/{p['id']}/activate")).status_code == 404
    assert all(x["id"] != p["id"] for x in (await b.get("/api/plans")).json())
    # Plan-Tag eines fremden Plans kann nicht gestartet werden
    tpl = next(x for x in (await a.get("/api/plans")).json() if x["kind"] == "template")
    own = (await a.post(f"/api/plans/{tpl['id']}/activate")).json()
    r = await b.post("/api/workouts/start", json={"plan_day_id": own["days"][0]["id"]})
    assert r.status_code == 404


async def test_cardio_isolated(make_user):
    a = await make_user()
    b = await make_user()
    c = (await a.post("/api/cardio", json={"kind": "run", "duration_s": 600})).json()
    assert (await b.get(f"/api/cardio/{c['id']}")).status_code == 404
    assert (await b.delete(f"/api/cardio/{c['id']}")).status_code == 404
    assert (await b.get("/api/cardio")).json() == []

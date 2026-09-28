from datetime import UTC, date, datetime, timedelta


async def _seed(c):
    exs = (await c.get("/api/exercises")).json()
    bench = next(e for e in exs if e["slug"] == "bench_press")
    for i, w in enumerate([60, 62.5, 65]):
        started = (datetime.now(UTC) - timedelta(days=14 - i * 7)).isoformat()
        await c.post("/api/workouts", json={"name": "Push", "started_at": started, "finished_at": started,
                                            "sets": [{"exercise_id": bench["id"], "reps": 8, "weight_kg": w}] * 3})
    for i in range(14):
        d = (date.today() - timedelta(days=i)).isoformat()
        await c.post("/api/meals", json={"day": d, "name": "Essen", "kcal": 2500, "protein": 150, "carbs": 250, "fat": 80})
        await c.post("/api/body", json={"day": d, "weight_kg": 80 - i * 0.1})
    return bench


async def test_stats_endpoints(make_user):
    c = await make_user()
    bench = await _seed(c)
    mv = (await c.get("/api/stats/muscles", params={"days": 30})).json()
    assert mv["sets"]["chest"] == 9 and mv["sets"]["triceps"] == 4.5
    ex = (await c.get(f"/api/stats/exercise/{bench['id']}")).json()
    assert len(ex["sessions"]) == 3 and ex["sessions"][-1]["pr"] is True
    assert ex["best_e1rm"] == round(65 * (1 + 8 / 30), 1)
    assert any(r["reps"] == 8 and r["weight_kg"] == 65 for r in ex["rep_records"])
    cal = (await c.get("/api/stats/calendar", params={"days": 30})).json()
    assert sum(d["workouts"] for d in cal) == 3
    wv = (await c.get("/api/stats/weekly-volume", params={"weeks": 4})).json()
    assert sum(wv["sets_by_muscle"]["chest"]) == 9
    nut = (await c.get("/api/stats/nutrition", params={"days": 14})).json()
    assert nut["average"]["kcal"] == 2500 and nut["logged_days"] == 14
    corr = (await c.get("/api/stats/correlations", params={"days": 28})).json()
    assert "weekly" in corr
    streak = (await c.get("/api/stats/streaks")).json()
    assert streak["days"] >= 14
    today = (await c.get("/api/stats/today")).json()
    assert today["nutrition"]["totals"]["kcal"] == 2500
    rep = (await c.get("/api/reports/week")).json()
    assert rep["data"]["training"]["workouts"] >= 1
    month = (await c.get("/api/reports/month")).json()
    assert month["period"] == "month"


async def test_dashboards(make_user):
    c = await make_user()
    ds = (await c.get("/api/dashboards")).json()
    assert ds and ds[0]["widgets"]
    d = (await c.post("/api/dashboards", json={"name": "Kraft", "widgets": [{"type": "exercise_1rm", "w": 9, "config": {"exercise_id": 1}}]})).json()
    assert d["widgets"][0]["w"] == 4
    assert (await c.put(f"/api/dashboards/{d['id']}", json={"name": "x", "widgets": [{"type": "hack"}]})).status_code == 422
    other = await make_user()
    assert (await other.put(f"/api/dashboards/{d['id']}", json={"name": "x"})).status_code == 404


async def test_stats_isolated(make_user):
    a = await make_user()
    await _seed(a)
    b = await make_user()
    assert (await b.get("/api/stats/muscles", params={"days": 30})).json()["sets"] == {}
    assert (await b.get("/api/stats/nutrition")).json()["logged_days"] == 0
    assert (await b.get(f"/api/stats/muscles?athlete={a.user['id']}")).status_code == 403

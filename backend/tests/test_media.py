"""Lokaler Cache für Übungsanimationen und Abbrechen von Trainings."""

import os

import httpx
import pytest

from app.services import media_cache

GIF = b"GIF89a" + b"\x00" * 100


@pytest.fixture
def upstream(monkeypatch):
    calls: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req.url.path)
        if "missing" in req.url.path:
            return httpx.Response(404)
        if req.url.path.endswith(".json"):
            return httpx.Response(200, json={"exercises": []})
        return httpx.Response(200, content=GIF)

    monkeypatch.setattr(media_cache, "_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    return calls


async def test_media_proxy_caches(make_user, anon_client, upstream):
    c = await make_user()
    path = "pectorals/test-press.gif"
    assert (await anon_client.get(f"/api/media/{path}")).status_code == 401
    r = await c.get(f"/api/media/{path}")
    assert r.status_code == 200 and r.content == GIF
    assert r.headers["content-type"] == "image/gif" and "immutable" in r.headers["cache-control"]
    r = await c.get(f"/api/media/{path}")
    assert r.status_code == 200
    assert len(upstream) == 1  # zweiter Abruf kommt aus dem Cache
    assert (media_cache.cache_dir() / path).is_file()
    r = await c.get("/api/media/api/en/muscles/biceps.json")
    assert r.status_code == 200 and r.json() == {"exercises": []}
    assert (await c.get("/api/media/pectorals/missing-one.gif")).status_code == 404


@pytest.mark.parametrize("path", ["../secrets/x.gif", "pectorals/x.png", "a/b/c.gif", "pectorals/X.gif", "api/de/muscles/x.json"])
async def test_media_proxy_rejects_paths(make_user, upstream, path):
    c = await make_user()
    assert (await c.get(f"/api/media/{path}")).status_code == 404
    assert upstream == []


async def test_media_warm_and_prune(upstream):
    res = await media_cache.warm(["glutes/warm-a", "glutes/warm-b", "glutes/missing-c"])
    assert res["loaded"] == 4 and res["failed"] == 2
    again = await media_cache.warm(["glutes/warm-a"])
    assert again == {"loaded": 0, "failed": 0, "cached": 2}
    old = media_cache.settings.media_cache_dir / "v0.0.1" / "x" / "old.gif"
    old.parent.mkdir(parents=True, exist_ok=True)
    old.write_bytes(GIF)
    a = media_cache.cache_dir() / "glutes/warm-a.gif"
    os.utime(a, (1, 1))  # ältester Zugriff -> wird zuerst entfernt
    size = sum(p.stat().st_size for p in media_cache.cache_dir().rglob("*") if p.is_file())
    media_cache.prune(max_bytes=size - 1)
    assert not old.exists() and not a.exists()
    assert (media_cache.cache_dir() / "glutes/warm-b.gif").exists()


async def test_discard_workout(make_user):
    c = await make_user()
    ex = (await c.get("/api/exercises")).json()[0]
    w = (await c.post("/api/workouts", json={"name": "Versehen"})).json()
    r = await c.post(f"/api/workouts/{w['id']}/sets", json={"exercise_id": ex["id"], "reps": 5, "weight": 50, "completed": True})
    assert r.status_code == 200, r.text
    other = await make_user()
    assert (await other.delete(f"/api/workouts/{w['id']}")).status_code == 404
    assert (await c.delete(f"/api/workouts/{w['id']}")).json() == {"ok": True}
    assert (await c.get(f"/api/workouts/{w['id']}/live")).status_code == 404
    assert all(x["id"] != w["id"] for x in (await c.get("/api/workouts")).json())

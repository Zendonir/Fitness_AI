"""Rechteprüfung: Rollen, Admin-Endpunkte, Trainer-Zugriff."""

from tests.conftest import PASSWORD


async def test_admin_endpoints_forbidden_for_users(make_user):
    c = await make_user()
    for path in ("/api/admin/users", "/api/admin/settings", "/api/admin/audit", "/api/admin/ai-usage"):
        assert (await c.get(path)).status_code == 403, path
    assert (await c.post("/api/admin/invites", json={})).status_code == 403


async def test_admin_lists_users_and_audit(admin_client, make_user):
    await make_user()
    users = (await admin_client.get("/api/admin/users")).json()
    assert any(u["role"] == "admin" for u in users)
    log = (await admin_client.get("/api/admin/audit")).json()
    assert any(e["action"] == "register" for e in log)


async def test_admin_cannot_lock_self(admin_client):
    me = (await admin_client.get("/api/auth/me")).json()["user"]
    r = await admin_client.patch(f"/api/admin/users/{me['id']}", json={"is_active": False})
    assert r.status_code == 400


async def test_trainer_needs_grant(make_user):
    athlete = await make_user()
    trainer = await make_user("trainer")
    other = await make_user()
    r = await trainer.get(f"/api/workouts?athlete={athlete.user['id']}")
    assert r.status_code == 403
    # normaler Benutzer kann niemals fremde Daten per athlete-Parameter lesen
    r = await other.get(f"/api/workouts?athlete={athlete.user['id']}")
    assert r.status_code == 403
    await athlete.post("/api/me/trainers", json={"trainer_id": trainer.user["id"]})
    r = await trainer.get(f"/api/workouts?athlete={athlete.user['id']}")
    assert r.status_code == 200
    r = await trainer.post("/api/trainer/comments", json={"athlete_id": athlete.user["id"], "text": "Gute Woche!"})
    assert r.status_code == 200
    comments = (await athlete.get("/api/me/comments")).json()
    assert comments[0]["text"] == "Gute Woche!"
    # Trainer darf keine Schreibzugriffe im Namen des Athleten ausführen
    r = await other.post("/api/trainer/comments", json={"athlete_id": athlete.user["id"], "text": "x"})
    assert r.status_code == 403


async def test_role_user_cannot_be_trainer_target(make_user):
    a = await make_user()
    b = await make_user()
    r = await a.post("/api/me/trainers", json={"trainer_id": b.user["id"]})
    assert r.status_code == 400


async def test_delete_account(make_user, anon_client):
    c = await make_user()
    r = await c.request("DELETE", "/api/me", json={"password": PASSWORD, "confirm": "LÖSCHEN"})
    assert r.status_code == 200
    r = await anon_client.post("/api/auth/login", json={"email": c.user["email"], "password": PASSWORD})
    assert r.status_code == 401

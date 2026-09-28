import pyotp

from tests.conftest import PASSWORD


async def test_health(anon_client):
    r = await anon_client.get("/api/health")
    assert r.json() == {"status": "ok"}


async def test_requires_login(anon_client):
    r = await anon_client.get("/api/auth/me")
    assert r.status_code == 401


async def test_registration_requires_invite(admin_client, anon_client):
    r = await anon_client.post("/api/auth/register", json={"email": "x@test.de", "password": PASSWORD})
    assert r.status_code == 403
    await admin_client.patch("/api/admin/settings", json={"open_registration": True})
    r = await anon_client.post("/api/auth/register", json={"email": "open@test.de", "password": PASSWORD})
    assert r.status_code == 200
    assert r.json()["user"]["role"] == "user"
    await admin_client.patch("/api/admin/settings", json={"open_registration": False})


async def test_invite_single_use_and_role(admin_client, anon_client):
    inv = await admin_client.post("/api/admin/invites", json={"role": "trainer"})
    token = inv.json()["url"].split("invite=")[1]
    r = await anon_client.post("/api/auth/register", json={"email": "tr@test.de", "password": PASSWORD, "invite": token})
    assert r.json()["user"]["role"] == "trainer"
    r = await anon_client.post("/api/auth/register", json={"email": "tr2@test.de", "password": PASSWORD, "invite": token})
    assert r.status_code == 400


async def test_weak_password_rejected(admin_client, anon_client):
    r = await anon_client.post("/api/auth/register", json={"email": "w@test.de", "password": "kurz"})
    assert r.status_code == 422


async def test_login_logout(make_user, anon_client):
    c = await make_user()
    r = await anon_client.post("/api/auth/login", json={"email": c.user["email"], "password": "falsch-falsch"})
    assert r.status_code == 401
    r = await anon_client.post("/api/auth/login", json={"email": c.user["email"], "password": PASSWORD})
    assert r.status_code == 200
    assert (await anon_client.get("/api/auth/me")).status_code == 200
    await anon_client.post("/api/auth/logout")
    assert (await anon_client.get("/api/auth/me")).status_code == 401


async def test_csrf_header_required(make_user):
    c = await make_user()
    r = await c.patch("/api/me/settings", json={"water_goal_ml": 3000}, headers={"X-Requested-With": ""})
    assert r.status_code == 403


async def test_totp_flow(make_user, anon_client):
    c = await make_user()
    setup = (await c.post("/api/auth/totp/setup")).json()
    code = pyotp.TOTP(setup["secret"]).now()
    assert (await c.post("/api/auth/totp/enable", json={"code": code})).status_code == 200
    r = await anon_client.post("/api/auth/login", json={"email": c.user["email"], "password": PASSWORD})
    assert r.json() == {"totp_required": True}
    r = await anon_client.post("/api/auth/login", json={"email": c.user["email"], "password": PASSWORD, "totp": "000000"})
    assert r.status_code == 401
    r = await anon_client.post("/api/auth/login", json={"email": c.user["email"], "password": PASSWORD,
                                                        "totp": pyotp.TOTP(setup["secret"]).now()})
    assert r.status_code == 200


async def test_api_token(make_user, anon_client):
    c = await make_user()
    tok = (await c.post("/api/auth/tokens", json={"name": "HA"})).json()["token"]
    r = await anon_client.get("/api/auth/me", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200
    assert r.json()["user"]["email"] == c.user["email"]
    r = await anon_client.get("/api/auth/me", headers={"Authorization": "Bearer ff_wrong"})
    assert r.status_code == 401


async def test_password_reset_link(admin_client, make_user, anon_client):
    c = await make_user()
    url = (await admin_client.post(f"/api/admin/users/{c.user['id']}/reset-link")).json()["url"]
    token = url.split("token=")[1]
    r = await anon_client.post("/api/auth/password/reset", json={"token": token, "password": "neues-passwort-123"})
    assert r.status_code == 200
    r = await anon_client.post("/api/auth/login", json={"email": c.user["email"], "password": "neues-passwort-123"})
    assert r.status_code == 200
    r = await anon_client.post("/api/auth/password/reset", json={"token": token, "password": "noch-ein-passwort"})
    assert r.status_code == 400


async def test_locked_user_cannot_access(admin_client, make_user):
    c = await make_user()
    await admin_client.patch(f"/api/admin/users/{c.user['id']}", json={"is_active": False})
    assert (await c.get("/api/auth/me")).status_code in (401, 403)

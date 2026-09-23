"""Admin-hozzáférés az egységes Energiafelhő-fiókkal (Keycloak) – 2026-09-23.

- Keycloak Bearer token `ev-admin` realm-szereppel → /api/admin/* és a védett
  /api/sessions/* végpontok elérhetők (200); szerep nélkül 403 `admin_role_missing`
  (a token egyébként érvényes, tehát NEM 401 – a SPA ebből tudja, hogy „nincs admin-jogod").
- A szerep neve KEYCLOAK_ADMIN_ROLE-lal állítható.
- A Basic vész-út csak akkor él, amíg ADMIN_PASSWORD be van állítva; nélküle 401
  `basic_disabled`. Ha sem Keycloak, sem ADMIN_PASSWORD → 503 `admin_not_configured`.
- /api/me `is_admin` a kijelzéshez (fejléc „Admin” link) – szerep szerint.

A JWKS-mock és a token-gyár a test_keycloak_auth modulból jön (a keycloak_env fixture
autouse, ezért az importtal ebben a modulban is bekapcsol).
"""
import base64

import pytest

from tests.test_keycloak_auth import bearer, keycloak_env, make_token  # noqa: F401

ADMIN_URLS = ["/api/admin/stats", "/api/admin/charge-points", "/api/sessions/"]


def admin_token(role="ev-admin", **kw):
    extra = {"realm_access": {"roles": ["default-roles-ugyfelek", "ugyfel"] + ([role] if role else [])}}
    extra.update(kw.pop("extra", {}) or {})
    return make_token(email=kw.pop("email", "gellert@example.hu"), extra=extra, **kw)


def basic(user, pw):
    return {"Authorization": "Basic " + base64.b64encode(f"{user}:{pw}".encode()).decode()}


@pytest.mark.asyncio
@pytest.mark.parametrize("url", ADMIN_URLS)
async def test_keycloak_admin_role_ok(client, url):
    r = await client.get(url, headers=bearer(admin_token()))
    assert r.status_code == 200, r.text


@pytest.mark.asyncio
async def test_keycloak_without_role_is_403_not_401(client):
    r = await client.get("/api/admin/stats", headers=bearer(admin_token(role=None)))
    assert r.status_code == 403
    assert r.json()["detail"] == "admin_role_missing"
    # nincs realm_access claim egyáltalán
    tok = make_token(email="ugyfel@example.hu")
    r = await client.get("/api/admin/stats", headers=bearer(tok))
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_keycloak_role_name_from_env(client, monkeypatch):
    monkeypatch.setenv("KEYCLOAK_ADMIN_ROLE", "toltes-admin")
    assert (await client.get("/api/admin/stats", headers=bearer(admin_token(role="ev-admin")))).status_code == 403
    assert (await client.get("/api/admin/stats", headers=bearer(admin_token(role="toltes-admin")))).status_code == 200


@pytest.mark.asyncio
async def test_keycloak_invalid_token_is_401(client):
    # lejárt token szereppel is 401 (a token-ellenőrzés a szerep előtt van)
    r = await client.get("/api/admin/stats", headers=bearer(admin_token(exp_in=-120)))
    assert r.status_code == 401
    assert r.json()["detail"] == "keycloak_token_expired"
    # ID-token (typ=ID) sem jó
    r = await client.get("/api/admin/stats", headers=bearer(admin_token(typ="ID")))
    assert r.status_code == 401
    # régi v1 e-mail-token: nem JWT → nem Keycloak; admin-jogot nem ad
    r = await client.get("/api/admin/stats", headers={"Authorization": "Bearer v1.abc.123.sig"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_keycloak_disabled_bearer_401(client, monkeypatch):
    monkeypatch.delenv("KEYCLOAK_ISSUER")
    r = await client.get("/api/admin/stats", headers=bearer(admin_token()))
    assert r.status_code == 401
    assert r.json()["detail"] == "keycloak_disabled"
    # a Basic vész-út ettől még él
    assert (await client.get("/api/admin/stats", headers=basic("admin", "test-admin-pw"))).status_code == 200


@pytest.mark.asyncio
async def test_basic_fallback(client):
    assert (await client.get("/api/admin/stats", headers=basic("admin", "test-admin-pw"))).status_code == 200
    r = await client.get("/api/admin/stats", headers=basic("admin", "rossz"))
    assert r.status_code == 401
    r = await client.get("/api/admin/stats", headers=basic("gellert@energiafelho.hu", "test-admin-pw"))
    assert r.status_code == 401
    r = await client.get("/api/admin/stats", headers={"Authorization": "Basic nem-base64!!"})
    assert r.status_code == 401
    r = await client.get("/api/admin/stats")
    assert r.status_code == 401
    assert r.headers.get("www-authenticate") == "Bearer"


@pytest.mark.asyncio
async def test_basic_disabled_without_password(client, monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "")
    r = await client.get("/api/admin/stats", headers=basic("admin", "test-admin-pw"))
    assert r.status_code == 401
    assert r.json()["detail"] == "basic_disabled"
    # Keycloak-út működik
    assert (await client.get("/api/admin/stats", headers=bearer(admin_token()))).status_code == 200


@pytest.mark.asyncio
async def test_nothing_configured_503(client, monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "")
    monkeypatch.delenv("KEYCLOAK_ISSUER")
    r = await client.get("/api/admin/stats", headers=basic("admin", "x"))
    assert r.status_code == 503
    assert r.json()["detail"] == "admin_not_configured"


@pytest.mark.asyncio
async def test_me_is_admin_flag(client):
    r = await client.get("/api/me", headers=bearer(admin_token()))
    assert r.status_code == 200, r.text
    assert r.json()["is_admin"] is True
    r = await client.get("/api/me", headers=bearer(make_token(email="ugyfel@example.hu")))
    assert r.status_code == 200
    assert r.json()["is_admin"] is False

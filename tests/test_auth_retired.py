"""A régi e-mail-kódos belépés megszűnt (TERV-egy-fiok, C. fázis, 2026-09-22).

A két régi végpont HTTP 410-et ad, kódot nem küld és nem ellenőriz; a Keycloak-config és a
profil végpont marad; a korábban kiadott v1 e-mail-tokenek a lejáratukig még jók.
"""
import os

import pytest

os.environ.setdefault("AUTH_SECRET", "test-auth-secret")

from app.services.auth_tokens import issue_token  # noqa: E402

RETIRED = {
    "error": "retired",
    "message": "A régi e-mail-kódos belépés megszűnt. Lépj be az Energiafelhő-fiókoddal.",
}


@pytest.mark.parametrize("path", ["/api/auth/request-code", "/api/auth/verify-code"])
@pytest.mark.parametrize(
    "body",
    [None, {}, {"email": "valaki@example.hu"}, {"email": "valaki@example.hu", "code": "123456"}],
)
async def test_email_code_login_is_retired(client, path, body):
    r = await client.post(path, json=body) if body is not None else await client.post(path)
    assert r.status_code == 410, r.text
    assert r.json() == RETIRED


async def test_no_login_code_is_written(client, db):
    from sqlalchemy import select
    from app.db.models import LoginCode

    await client.post("/api/auth/request-code", json={"email": "valaki@example.hu"})
    assert (await db.execute(select(LoginCode))).scalars().all() == []


async def test_keycloak_config_and_profile_remain(client, monkeypatch):
    monkeypatch.delenv("KEYCLOAK_ISSUER", raising=False)
    from app.services import keycloak
    keycloak.reset_cache()
    r = await client.get("/api/auth/keycloak/config")
    assert r.status_code == 200 and r.json() == {"enabled": False}

    # profil: token nélkül 401, régi (még érvényes) v1 e-mail-tokennel 200
    assert (await client.get("/api/auth/profile")).status_code == 401
    r = await client.get("/api/auth/profile",
                         headers={"Authorization": f"Bearer {issue_token('regi@example.hu')}"})
    assert r.status_code == 200 and r.json() == {"ok": True, "profile": None}

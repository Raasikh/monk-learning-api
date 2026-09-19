"""/admin is closed to everyone who isn't on ADMIN_EMAILS.

This is the only file in the suite whose job is a *negative*: proving that a
route does nothing. It is worth its keep because the failure mode is silent —
the dashboard reads every student's row through the service key, so a gate that
quietly stops gating looks exactly like a gate that works, right up until the
day someone notices /admin/api/users answers a stranger.

Three properties are pinned:

 1. An empty ADMIN_EMAILS closes the door rather than opening it. Env vars get
    dropped in redeploys; this one must fail shut when it does.
 2. A valid student token is not an admin token. Being signed in is not the
    same as being allowed in, and the JWT check alone would conflate them.
 3. Rejection is 404, never 403. A 403 tells a prober the route exists and
    that they merely lack a role — which is the half of the answer worth
    hiding.
"""

import importlib

import pytest
from fastapi.testclient import TestClient

from app import auth as auth_mod
from app.config import settings


FOUNDER = "founder@monklearning.example"
COFOUNDER = "CoFounder@MonkLearning.example"     # deliberately mixed-case
STUDENT = "student@example.com"


@pytest.fixture
def client(monkeypatch):
    """The app, with the startup hooks (env validation, warmers) removed."""
    main = importlib.import_module("app.main")
    monkeypatch.setattr(main.app.router, "on_startup", [])
    return TestClient(main.app)


@pytest.fixture
def allowlist(monkeypatch):
    """Two founders on the list, one of them typed with stray capitals."""
    monkeypatch.setattr(settings, "ADMIN_EMAILS", f"{FOUNDER}, {COFOUNDER}")


def _as(monkeypatch, email, user_id="11111111-1111-1111-1111-111111111111"):
    """Make every presented token decode to this identity."""
    monkeypatch.setattr(
        auth_mod, "decode_supabase_claims",
        lambda token: {"sub": user_id, "email": email},
    )


BEARER = {"Authorization": "Bearer stub-token"}

# Everything that must be unreachable. /admin itself is excluded on purpose —
# it is the sign-in screen and holds no data.
GUARDED = [
    "/admin/api/whoami",
    "/admin/api/overview",
    "/admin/api/retention",
    "/admin/api/features",
    "/admin/api/costs",
    "/admin/api/users",
    "/admin/api/users/11111111-1111-1111-1111-111111111111",
]


@pytest.mark.parametrize("path", GUARDED)
def test_no_token_is_404(client, allowlist, path):
    assert client.get(path).status_code == 404


@pytest.mark.parametrize("path", GUARDED)
def test_a_signed_in_student_is_404(client, allowlist, monkeypatch, path):
    _as(monkeypatch, STUDENT)
    assert client.get(path, headers=BEARER).status_code == 404


def test_empty_allowlist_fails_shut(client, monkeypatch):
    """No ADMIN_EMAILS means nobody, not everybody."""
    monkeypatch.setattr(settings, "ADMIN_EMAILS", "")
    _as(monkeypatch, FOUNDER)
    assert client.get("/admin/api/whoami", headers=BEARER).status_code == 404


def test_a_founder_gets_in(client, allowlist, monkeypatch):
    _as(monkeypatch, FOUNDER)
    r = client.get("/admin/api/whoami", headers=BEARER)
    assert r.status_code == 200
    assert r.json()["email"] == FOUNDER


def test_the_allowlist_ignores_capitalisation(client, allowlist, monkeypatch):
    """The env var is typed by a human; Supabase stores addresses lowercased."""
    _as(monkeypatch, COFOUNDER.lower())
    assert client.get("/admin/api/whoami", headers=BEARER).status_code == 200


def test_a_token_without_an_email_claim_is_404(client, allowlist, monkeypatch):
    """An anonymous session carries a `sub` but no verified address."""
    monkeypatch.setattr(
        auth_mod, "decode_supabase_claims",
        lambda token: {"sub": "22222222-2222-2222-2222-222222222222"},
    )
    assert client.get("/admin/api/whoami", headers=BEARER).status_code == 404


def test_an_unverifiable_token_is_404(client, allowlist, monkeypatch):
    """A forged or expired token must not distinguish itself from a wrong one."""
    import jwt

    def boom(token):
        raise jwt.InvalidTokenError("signature mismatch")

    monkeypatch.setattr(auth_mod, "decode_supabase_claims", boom)
    assert client.get("/admin/api/whoami", headers=BEARER).status_code == 404


def test_the_sign_in_page_is_public(client, allowlist):
    """It has to be — it is where you sign in. It carries no data."""
    r = client.get("/admin")
    assert r.status_code == 200
    assert "<title>Monk · Admin</title>" in r.text


def test_the_page_never_ships_the_secret_key(client, allowlist):
    """config.json hands out the anon key (already in every app bundle) and
    must never hand out the service key the dashboard's reads run under."""
    body = client.get("/admin/config.json").text
    assert settings.SUPABASE_SECRET_KEY not in body


# ─────────────────────────────────────────────────────────────────────────────
# Delete / restore — the only routes that change anything.
# ─────────────────────────────────────────────────────────────────────────────

WRITE_ROUTES = [
    "/admin/api/users/11111111-1111-1111-1111-111111111111/delete",
    "/admin/api/users/11111111-1111-1111-1111-111111111111/restore",
]


@pytest.mark.parametrize("path", WRITE_ROUTES)
def test_writes_are_404_without_an_admin_token(client, allowlist, monkeypatch, path):
    _as(monkeypatch, STUDENT)
    assert client.post(path, headers=BEARER, json={}).status_code == 404
    assert client.post(path, json={}).status_code == 404


@pytest.mark.parametrize("path", WRITE_ROUTES)
def test_writes_reject_GET(client, allowlist, monkeypatch, path):
    """POST only. A GET that bans an account is reachable from a prefetch, a
    link, or an <img> tag — none of which involve anyone deciding anything."""
    _as(monkeypatch, FOUNDER)
    assert client.get(path, headers=BEARER).status_code == 405


def test_you_cannot_delete_yourself(client, allowlist, monkeypatch):
    """One mis-click would otherwise lock the person holding the mouse out of
    the product AND out of this dashboard, with nobody left to undo it."""
    me = "22222222-2222-2222-2222-222222222222"
    _as(monkeypatch, FOUNDER, user_id=me)
    r = client.post(f"/admin/api/users/{me}/delete", headers=BEARER, json={})
    assert r.status_code == 400
    assert "your own account" in r.json()["detail"].lower()


def test_you_cannot_delete_another_admin(client, allowlist, monkeypatch):
    import app.routers.admin as admin_mod

    async def fake_rpc(fn, params, expect="object"):
        assert fn == "admin_user", f"should not have reached {fn}()"
        return {"email": COFOUNDER.lower()}

    monkeypatch.setattr(admin_mod, "_rpc", fake_rpc)
    _as(monkeypatch, FOUNDER, user_id="33333333-3333-3333-3333-333333333333")
    r = client.post("/admin/api/users/44444444-4444-4444-4444-444444444444/delete",
                    headers=BEARER, json={})
    assert r.status_code == 400
    assert "admin allowlist" in r.json()["detail"]


def test_a_normal_student_can_be_deleted(client, allowlist, monkeypatch):
    import app.routers.admin as admin_mod

    calls = []

    async def fake_rpc(fn, params, expect="object"):
        calls.append((fn, params))
        if fn == "admin_user":
            return {"email": STUDENT}
        return {"ok": True, "already": False, "email": STUDENT}

    monkeypatch.setattr(admin_mod, "_rpc", fake_rpc)
    _as(monkeypatch, FOUNDER, user_id="33333333-3333-3333-3333-333333333333")
    target = "55555555-5555-5555-5555-555555555555"
    r = client.post(f"/admin/api/users/{target}/delete", headers=BEARER,
                    json={"reason": "duplicate signup"})
    assert r.status_code == 200 and r.json()["ok"] is True

    fn, params = next(c for c in calls if c[0] == "admin_delete_user")
    assert params["p_user_id"] == target
    # The actor is the signed-in admin, never anything the client sent — the
    # audit log is worthless if the caller can name themselves.
    assert params["p_actor"] == FOUNDER
    assert params["p_reason"] == "duplicate signup"


def test_the_reason_is_truncated_not_rejected(client, allowlist, monkeypatch):
    """A pasted stack trace should not 500 the delete; it should be cut."""
    import app.routers.admin as admin_mod

    seen = {}

    async def fake_rpc(fn, params, expect="object"):
        if fn == "admin_user":
            return {"email": STUDENT}
        seen.update(params)
        return {"ok": True, "email": STUDENT}

    monkeypatch.setattr(admin_mod, "_rpc", fake_rpc)
    _as(monkeypatch, FOUNDER, user_id="33333333-3333-3333-3333-333333333333")
    r = client.post("/admin/api/users/66666666-6666-6666-6666-666666666666/delete",
                    headers=BEARER, json={"reason": "x" * 5000})
    assert r.status_code == 200
    assert len(seen["p_reason"]) == 500

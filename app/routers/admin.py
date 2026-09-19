"""
/admin — the founders' analytics dashboard.

Deliberately NOT in the mobile app. Two reasons, and the first is the one
that matters: everything in the Expo bundle ships to every student's phone,
so an admin screen there is readable by anyone who unzips the IPA. The second
is that it could not work anyway — the phone holds the publishable key under
RLS and only ever touches `profiles` and `lesson_sections` directly. Every
number here lives behind the service key, which only this process has.

Shape of the thing:

    GET  /admin                  the page itself (static HTML, no build step)
    GET  /admin/config.json      public: Supabase URL + anon key, for sign-in
    GET  /admin/api/overview     signups, DAU/WAU/MAU, daily series
    GET  /admin/api/retention    weekly cohorts, D1/D7/D30
    GET  /admin/api/features     practice / classroom / doubts / notes usage
    GET  /admin/api/costs        LLM spend, from llm_calls
    GET  /admin/api/users        searchable user list
    GET  /admin/api/users/{id}   one student in full

Every aggregate route takes `include_internal` (default false), which decides
whether accounts on `admin_excluded_users` — founders, test rigs — are counted.
False is the honest view and the default; the toggle exists because "did my own
test session record?" is a real question. The per-user drilldown never filters:
asking for one account always returns it.

Every /admin/api/* route depends on `require_admin`, which answers 404 to
anyone not on ADMIN_EMAILS — see the note there on why 404 and not 403.

The endpoints do no arithmetic. Each is one `.rpc()` into a function from
migration 0048, which computes in Postgres and returns finished JSON. That is
not laziness: PostgREST silently truncates at 1000 rows (app/db.py), so any
DAU counted by pulling rows into Python is wrong the day the table outgrows a
page, and wrong without saying so.
"""

import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse

from app.auth import AdminIdentity, require_admin
from app.config import settings
from app.db import aexec, supabase

logger = logging.getLogger("admin")

router = APIRouter(prefix="/admin", tags=["admin"])

_PAGE = Path(__file__).resolve().parent.parent / "admin_ui" / "index.html"

# The dashboard's range selector. Bounded so a typo in the URL can't ask
# Postgres to bucket ten years of rows on a single-worker box.
_MIN_DAYS, _MAX_DAYS = 1, 365


def _days(value: int) -> int:
    return max(_MIN_DAYS, min(_MAX_DAYS, value))


async def _rpc(fn: str, params: dict, expect: str = "object"):
    """One analytics function call, off the event loop.

    `aexec` rather than a bare call because the Supabase client is synchronous
    httpx: called straight from `async def` it parks the whole loop for the
    round trip, and there is exactly one uvicorn worker — so a slow dashboard
    query would stall a student's live classroom audio. Same reasoning as
    every other caller in this codebase; see app/db.py.

    `expect` exists because a jsonb-returning function can come back wrapped
    in a single-element list depending on the client (progress.py hit the same
    thing), and admin_retention legitimately RETURNS a jsonb array — so
    unwrapping unconditionally would hand back only its first cohort.
    """
    try:
        res = await aexec(lambda: supabase.rpc(fn, params).execute())
    except Exception as exc:
        # The most likely cause by far is that migration 0048 has not been
        # applied to this environment yet, which is a setup problem and
        # deserves to say so rather than surfacing as a bare 500.
        logger.error("[admin] rpc %s failed: %s", fn, exc)
        raise HTTPException(
            status_code=503,
            detail=(
                f"Analytics function {fn}() is unavailable. If this is a fresh "
                "deploy, apply migrations/0048_admin_analytics.sql in the "
                "Supabase SQL editor."
            ),
        )
    data = res.data
    if expect == "object" and isinstance(data, list):
        data = data[0] if data else None
    return data


# ─────────────────────────────────────────────────────────────────────────────
# The page, and the one public thing it needs to sign in with.
# ─────────────────────────────────────────────────────────────────────────────

@router.get("", include_in_schema=False)
@router.get("/", include_in_schema=False)
async def admin_page():
    """Served unauthenticated on purpose — it IS the sign-in screen.

    The page holds no data. It renders a single email box, and until Supabase
    hands it a token every /admin/api/* call it makes comes back 404.
    """
    if not _PAGE.exists():
        raise HTTPException(status_code=404, detail="Not Found")
    return FileResponse(_PAGE, media_type="text/html")


@router.get("/config.json", include_in_schema=False)
async def admin_config():
    """Supabase URL + publishable key, so the page can run the same email OTP.

    Both values are public by definition: they are compiled into every copy of
    the mobile app already (.env is committed, and says so at the top). What
    keeps a student out of this dashboard is the ADMIN_EMAILS check on the API
    side, never the secrecy of these two strings.
    """
    if not settings.SUPABASE_URL or not settings.SUPABASE_PUBLISHABLE_KEY:
        return JSONResponse(
            status_code=503,
            content={
                "error": (
                    "SUPABASE_PUBLISHABLE_KEY is not set on this deploy. Copy "
                    "EXPO_PUBLIC_SUPABASE_PUBLISHABLE_KEY from the mobile app's "
                    ".env into the API's environment."
                )
            },
        )
    return {
        "supabase_url": settings.SUPABASE_URL,
        "supabase_key": settings.SUPABASE_PUBLISHABLE_KEY,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Data.
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/api/whoami")
async def whoami(admin: AdminIdentity = Depends(require_admin)):
    """Lets the page tell "you are not an admin" from "your token expired".

    Both are 404 on every other route by design, which is correct for an
    attacker and useless for the signed-in founder staring at an empty screen.
    """
    return {"user_id": admin.user_id, "email": admin.email}


@router.get("/api/overview")
async def overview(
    days: int = Query(30, ge=_MIN_DAYS, le=_MAX_DAYS),
    include_internal: bool = Query(False),
    admin: AdminIdentity = Depends(require_admin),
):
    return await _rpc("admin_overview",
                      {"p_days": _days(days), "p_include_internal": include_internal})


@router.get("/api/retention")
async def retention(
    weeks: int = Query(8, ge=1, le=52),
    include_internal: bool = Query(False),
    admin: AdminIdentity = Depends(require_admin),
):
    cohorts = await _rpc("admin_retention",
                         {"p_weeks": weeks, "p_include_internal": include_internal},
                         expect="array")
    return {"cohorts": cohorts or []}


@router.get("/api/features")
async def features(
    days: int = Query(30, ge=_MIN_DAYS, le=_MAX_DAYS),
    include_internal: bool = Query(False),
    admin: AdminIdentity = Depends(require_admin),
):
    return await _rpc("admin_features",
                      {"p_days": _days(days), "p_include_internal": include_internal})


@router.get("/api/costs")
async def costs(
    days: int = Query(30, ge=_MIN_DAYS, le=_MAX_DAYS),
    include_internal: bool = Query(False),
    admin: AdminIdentity = Depends(require_admin),
):
    return await _rpc("admin_costs",
                      {"p_days": _days(days), "p_include_internal": include_internal})


@router.get("/api/users")
async def users(
    q: Optional[str] = Query(None, max_length=200),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    sort: str = Query("recent"),
    include_internal: bool = Query(False),
    admin: AdminIdentity = Depends(require_admin),
):
    # Whitelisted rather than passed through: `sort` reaches an ORDER BY, and
    # although 0048 compares it to literals rather than interpolating it, the
    # guarantee belongs at the boundary too.
    if sort not in {"recent", "active", "attempts", "cost"}:
        sort = "recent"
    return await _rpc(
        "admin_users",
        {"p_q": q, "p_limit": limit, "p_offset": offset, "p_sort": sort,
         "p_include_internal": include_internal},
    )


@router.get("/api/users/{user_id}")
async def user_detail(
    user_id: str,
    days: int = Query(30, ge=_MIN_DAYS, le=_MAX_DAYS),
    admin: AdminIdentity = Depends(require_admin),
):
    data = await _rpc("admin_user", {"p_user_id": user_id, "p_days": _days(days)})
    if not data:
        raise HTTPException(status_code=404, detail="No such user")
    return data

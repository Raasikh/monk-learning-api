import asyncio
import os
import time
from typing import Any, Callable, Dict, List, Optional, Sequence, TypeVar
from supabase import create_client, Client, ClientOptions
from app.config import settings

_T = TypeVar("_T")


async def aexec(build: Callable[[], _T]) -> _T:
    """Run one blocking Supabase/SDK call off the event loop.

    Every client in this codebase is synchronous httpx. Called straight from an
    `async def` — which is what the live-class WebSocket and the tutor turn
    generators are — each call parks the entire event loop for the length of its
    round trip, measured at ~325ms for Supabase. A turn makes about ten of them,
    so one student's turn was freezing every other student's audio for three or
    four seconds at a time, and there is only ONE uvicorn worker (see the note
    in railway.toml), so that loop is the whole server.

    Usage is a thunk, because the calls are chained expressions rather than
    functions:

        res = await aexec(lambda: supabase.table("x").select("*").execute())

    Independent reads should go through asyncio.gather rather than one await
    after another.
    """
    return await asyncio.to_thread(build)

# PostgREST's own default is 120s. Nothing this API asks of Postgres is worth
# two minutes: a query that slow has already lost the student, and the request
# holding a threadpool slot that long is what turns one bad query into a stalled
# process. Env-overridable so it can be raised during a slow migration without a
# redeploy.
_POSTGREST_TIMEOUT_S = int(os.getenv("POSTGREST_TIMEOUT_S", "15"))

# PostgREST caps a response at 1000 rows and reports no error when it truncates.
# `concepts` is already 1,144, so a plain .execute() silently returns two thirds
# of the taxonomy — the failure looks like missing content, never like a bug.
POSTGREST_PAGE = 1000

_supabase_client: Optional[Client] = None


def get_supabase() -> Client:
    global _supabase_client
    if _supabase_client is None:
        if not settings.SUPABASE_URL or not settings.SUPABASE_SECRET_KEY:
            raise RuntimeError("SUPABASE_URL and SUPABASE_SECRET_KEY must be set in environment variables")
        _supabase_client = create_client(
            supabase_url=settings.SUPABASE_URL,
            supabase_key=settings.SUPABASE_SECRET_KEY,
            options=ClientOptions(postgrest_client_timeout=_POSTGREST_TIMEOUT_S),
        )
    return _supabase_client


# Module-level property proxy or lazy getter for backward compatibility
class LazySupabase:
    def __getattr__(self, name):
        return getattr(get_supabase(), name)


supabase = LazySupabase()


# The syllabus tables change when a curation job runs, never per request, but
# /progress and /drona/catalogue were each re-downloading all of them on every
# page load: 106 chapters + 1,144 concepts + weights + config measured at 2.9s
# of the ~5s a Progress page took. Supabase round trips are ~350ms apiece and
# concepts needs two pages, so the cost is round trips, not rows.
_TAXONOMY_TTL_S = float(os.getenv("TAXONOMY_CACHE_TTL_S", "600"))
_taxonomy_cache: Dict[str, Any] = {}


def fetch_all_cached(table: str, columns: str, order_by: Sequence[str] = ("id",),
                     **eq: Any) -> List[Dict[str, Any]]:
    """fetch_all() for tables that only change when we rebuild the syllabus.

    Safe for chapters/concepts/weights/config; NEVER use it for per-user rows,
    which must reflect the answer a student just gave. Set
    TAXONOMY_CACHE_TTL_S=0 to disable while editing the taxonomy.

    `order_by` is passed straight through — see fetch_all, where it is load
    bearing rather than cosmetic. It is part of the cache key because two orders
    are two different lists.
    """
    key = f"{table}|{columns}|{tuple(order_by)}|{sorted(eq.items())}"
    hit = _taxonomy_cache.get(key)
    now = time.monotonic()
    if hit and _TAXONOMY_TTL_S > 0 and (now - hit[0]) < _TAXONOMY_TTL_S:
        return hit[1]
    rows = fetch_all(table, columns, order_by=order_by, **eq)
    _taxonomy_cache[key] = (now, rows)
    return rows


def clear_taxonomy_cache() -> None:
    """Drop cached syllabus rows — call after a curation/migration job."""
    _taxonomy_cache.clear()


def fetch_all(table: str, columns: str, order_by: Sequence[str] = ("id",),
              **eq: Any) -> List[Dict[str, Any]]:
    """SELECT every matching row, paging past PostgREST's 1000-row ceiling.

    Use this for any table that can exceed 1000 rows — `concepts` (1,172) and
    `concept_aliases` (1,574) already do. A truncated read is invisible: no
    error, no warning, just a short list that looks plausible.

    `eq` applies equality filters, e.g. fetch_all("concepts", "id,name",
    chapter_id=cid).

    `order_by` IS NOT COSMETIC. `.range(1000, 1999)` asks for the second window
    of an order, and without an ORDER BY there is no defined order to take a
    window of — Postgres may return rows in whatever order the chosen plan
    produces, and two requests are two plans. The observable failure is not an
    error: it is a page that repeats rows the first page already had, and
    therefore silently omits others. That is the same shape as the truncation
    this function exists to prevent, one layer down.

    It must be UNIQUE, or ties inside it are unordered again and the window can
    still slip. Most tables here use the primary key, but not all of them have
    one called `id`: `progress_config` is keyed by `version` and
    `chapter_exam_weights` by (chapter_id, exam), so both pass their own — and a
    default of ("id",) would raise a PostgREST error on either rather than
    degrade, which is at least loud.
    """
    out: List[Dict[str, Any]] = []
    offset = 0
    while True:
        q = supabase.table(table).select(columns)
        for col, val in eq.items():
            q = q.eq(col, val)
        for col in order_by:
            q = q.order(col)
        page = q.range(offset, offset + POSTGREST_PAGE - 1).execute().data or []
        out.extend(page)
        if len(page) < POSTGREST_PAGE:
            return out
        offset += POSTGREST_PAGE

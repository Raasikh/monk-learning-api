import os
import time
from typing import Any, Dict, List, Optional
from supabase import create_client, Client
from app.config import settings

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
            supabase_key=settings.SUPABASE_SECRET_KEY
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


def fetch_all_cached(table: str, columns: str, **eq: Any) -> List[Dict[str, Any]]:
    """fetch_all() for tables that only change when we rebuild the syllabus.

    Safe for chapters/concepts/weights/config; NEVER use it for per-user rows,
    which must reflect the answer a student just gave. Set
    TAXONOMY_CACHE_TTL_S=0 to disable while editing the taxonomy.
    """
    key = f"{table}|{columns}|{sorted(eq.items())}"
    hit = _taxonomy_cache.get(key)
    now = time.monotonic()
    if hit and _TAXONOMY_TTL_S > 0 and (now - hit[0]) < _TAXONOMY_TTL_S:
        return hit[1]
    rows = fetch_all(table, columns, **eq)
    _taxonomy_cache[key] = (now, rows)
    return rows


def clear_taxonomy_cache() -> None:
    """Drop cached syllabus rows — call after a curation/migration job."""
    _taxonomy_cache.clear()


def fetch_all(table: str, columns: str, **eq: Any) -> List[Dict[str, Any]]:
    """SELECT every matching row, paging past PostgREST's 1000-row ceiling.

    Use this for any table that can exceed 1000 rows — `concepts` (1,144) and
    `concept_aliases` (1,574) already do. A truncated read is invisible: no
    error, no warning, just a short list that looks plausible.

    `eq` applies equality filters, e.g. fetch_all("concepts", "id,name",
    chapter_id=cid).
    """
    out: List[Dict[str, Any]] = []
    offset = 0
    while True:
        q = supabase.table(table).select(columns)
        for col, val in eq.items():
            q = q.eq(col, val)
        page = q.range(offset, offset + POSTGREST_PAGE - 1).execute().data or []
        out.extend(page)
        if len(page) < POSTGREST_PAGE:
            return out
        offset += POSTGREST_PAGE

import asyncio
import json
import logging
import os
import random
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Dict, Any, Tuple
from fastapi import (APIRouter, BackgroundTasks, Depends, File, Form, HTTPException,
                     UploadFile, status)
from pydantic import BaseModel

from app import exam_scope, redis_store
from app.auth import get_current_user_id
from app.db import supabase, fetch_all_cached, POSTGREST_PAGE
from app.drona.persona import normalize_language, normalize_voice, tutor_name
from app.progress_scoring import apply_answer_scoring, record_serve
# The follow-up machinery is the doubts router's, reused rather than copied:
# `_followup_response` takes a plain context dict and writes nothing to the
# doubts table, so a practice question can ask the same question of it.
from app.routers.doubts import (_followup_response, _tutor_prefs_for,
                                followup_voice_response, speak_stream_response)


def _candidate_query(subject, discipline, chapter_id):
    # `eq`, not `ilike`. Every one of the 15,408 rows in `questions` stores
    # its subject in exactly the lowercase vocabulary exam_scope documents —
    # verified against production, zero exceptions and zero NULLs — and
    # `chosen_subject` is already in those terms. ilike on a text column
    # cannot use a btree index; eq can, which is what the index added in
    # migration 0052 is for.
    q = (
        supabase.table("questions")
        .select("id, question_type, chapter_id, chapter_name, concept, "
                "difficulty, target_exams, discipline")
        .eq("subject", subject)
        .is_("needs_manual", "null")
        # NOT `.neq("source", ...)`. In SQL `NULL <> 'x'` is NULL, not true,
        # so a plain neq silently drops every row whose `source` is unset --
        # 9,035 of the bank's 15,408 rows, 59% of it.
        .or_("source.is.null,source.neq.extracted_master_content")
    )
    if chapter_id:
        q = q.eq("chapter_id", chapter_id)
    # Botany/Zoology is a filter the database can apply. The Python loop
    # below did it over every row that came back, which meant transferring
    # the half of biology this session cannot use in order to discard it.
    # Matching `ilike` here reproduces that loop's semantics exactly,
    # including excluding a NULL discipline.
    if subject == "biology" and discipline:
        q = q.ilike("discipline", f"%{discipline}%")
    return q

def _fetch_pool(subject, discipline, chapter_id=None):
    """EVERY servable row, not the first thousand.

    PostgREST caps a response at 1000 rows and does not say that it did.
    There are 2,628-3,092 servable rows per subject (counted against
    production 2026-09-19), so a plain read handed selection about a third
    of the bank and the other two thirds were unreachable — a question a
    student could never be served, with nothing anywhere to say so.

    Paging is what fixes it, and it only became affordable once the pool was
    cached: these three round trips are paid when a pool is FILLED, roughly
    once per subject per 600s across all workers, not on a student's tap.

    `.order("id")` is load-bearing. Paging with .range() and no ORDER BY
    asks the database for "rows 1000-1999" of an unspecified order, so a
    different plan between pages can repeat rows or skip them. A stable,
    unique key makes the window mean what it says.
    """
    rows: List[Dict[str, Any]] = []
    offset = 0
    while True:
        page = (
            _candidate_query(subject, discipline, chapter_id)
            .order("id")
            .range(offset, offset + POSTGREST_PAGE - 1)
            .execute()
            .data
        ) or []
        rows.extend(page)
        if len(page) < POSTGREST_PAGE:
            break
        offset += POSTGREST_PAGE
        if offset >= _CANDIDATE_MAX_ROWS:
            # Not a silent truncation: a bank this size means the pool
            # approach itself needs revisiting, and the log says so.
            logger.warning(
                "[PRACTICE NEXT] candidate pool for %s hit the %d-row ceiling "
                "— selection is no longer seeing the whole bank",
                subject, _CANDIDATE_MAX_ROWS,
            )
            break
    return rows


def _cached_pool(subject: str, discipline: Optional[str]):
    """(rows, tier, rows_to_share) for an unfocused pool.

    `tier` names who answered — local / redis / supabase — and is reported in
    the per-question log line, so a slow call can be read rather than guessed
    at. `rows_to_share` is non-None only on a Supabase fill, and is the caller's
    cue to push it to Redis for the other workers; whether that happens inline
    or after the response is the caller's business, not this function's.
    """
    key = f"{subject}|{discipline or ''}"
    now = time.monotonic()

    hit = _candidate_cache.get(key)
    if hit and (now - hit[0]) < _CANDIDATE_TTL_S:
        return hit[1], "local", None

    shared = redis_store.cache_get_json(_pool_key(key))
    if shared is not None:
        _candidate_cache[key] = (now, shared)
        return shared, "redis", None

    rows = _fetch_pool(subject, discipline)
    _candidate_cache[key] = (now, rows)
    return rows, "supabase", rows


def warm_candidate_pools(force: bool = False) -> None:
    """Fill every unfocused pool, so that no STUDENT ever pays for a cold one.

    The pool stopped being truncated at 1000 rows, which made a fill three paged
    round trips (~2.3s) instead of one. That is the right cost for correctness
    and the wrong thing to charge to whoever happens to tap first.

    `force` refetches rather than accepting a cached copy, and is what the
    refresh loop uses. Warming ONLY at startup was not enough, and production
    said so plainly: pools warmed at 18:46:40, the TTL expired at 18:56, and a
    student at 19:17 paid 4206ms to refill physics. At low traffic the first
    student after every TTL window pays — which is most students.

    Subjects are filled one at a time rather than in parallel: this is not
    urgent work, and four workers should not each open four concurrent paged
    reads against Supabase.
    """
    for subject in exam_scope.subjects_for("both"):
        key = f"{subject}|"
        try:
            if force:
                rows = _fetch_pool(subject, None)
                _candidate_cache[key] = (time.monotonic(), rows)
                tier = "refetched"
            else:
                rows, tier, _share = _cached_pool(subject, None)
            # Always (re)shared, and with a TTL well past the refresh interval,
            # so an entry never expires in the gap between two refreshes.
            redis_store.cache_set_json(_pool_key(key), rows, _POOL_SHARE_TTL_S)
            logger.info("[PRACTICE WARM] %s pool=%s rows=%d", subject, tier, len(rows))
        except Exception as err:  # noqa: BLE001 — a cold pool is slow, not broken
            logger.warning("[PRACTICE WARM] %s failed, will fill on demand: %s",
                           subject, err)


async def refresh_candidate_pools_loop() -> None:
    """Keeps the pools warm for as long as the process lives.

    A cache that is only filled at startup is warm for one TTL and cold for the
    rest of the day. This refetches on an interval SHORTER than the TTL, so the
    local copy is replaced before it can expire and the Redis copy is rewritten
    long before its own longer TTL runs out. The intended steady state is that a
    student's read is always `pool=local`, and `pool=supabase` in the log means
    something is wrong rather than something is normal.

    The cost is four paged reads per worker per interval — at the default, about
    one Supabase read every four seconds across the whole service, for a table
    that is never on a student's critical path. That is the trade: a little
    constant background load to buy a predictable tap.
    """
    while True:
        await asyncio.sleep(_POOL_REFRESH_S)
        try:
            await asyncio.to_thread(warm_candidate_pools, True)
        except Exception as err:  # noqa: BLE001 — never let the loop die
            logger.warning("[PRACTICE WARM] refresh pass failed: %s", err)


def resolve_display_concept(question_id: str, raw_concept: Optional[str]) -> Optional[str]:
    """The name shown during practice must match what Progress scores and
    displays for the same question — otherwise a student sees one concept
    name while answering and a different one on their Progress page for the
    identical question. Resolves through question_concepts (primary role) to
    the curated concepts.name; falls back to the legacy free-text tag for
    subjects not yet curated, so nothing breaks for them.

    ONE round trip, with the name joined on.

    This used to read `question_concepts` and then call
    fetch_all_cached("concepts", "id, name") to look the name up in a dict —
    1,172 rows fetched to resolve one of them. The cache made that free on a
    warm worker and 1753ms on a cold one, measured against production, and with
    WEB_CONCURRENCY=4 there are four workers to warm and a 600s TTL to lose it
    to. It was the whole of a 2284ms second wave on a call whose candidate pool
    had come from Redis, i.e. with nothing else left to blame.

    PostgREST embeds the related row over the concept_id foreign key, so the
    name arrives with the row that points at it and no table-wide fetch happens
    at all. Same fallback as before: no row, no name, or a failure all fall
    back to the legacy free-text tag.
    """
    try:
        rows = (
            supabase.table("question_concepts")
            .select("concept_id, concepts(name)")
            .eq("question_id", question_id)
            .eq("role", "primary")
            .limit(1)
            .execute()
            .data
        )
        if rows:
            # Embedded to-one arrives as a dict; a PostgREST version that infers
            # to-many would hand back a list, so both are read.
            embedded = rows[0].get("concepts")
            if isinstance(embedded, list):
                embedded = embedded[0] if embedded else None
            name = (embedded or {}).get("name") if isinstance(embedded, dict) else None
            if name:
                return name
    except Exception as e:
        logger.warning("[CONCEPT RESOLVE] %s: %s", question_id[:8], e)
    return raw_concept

logger = logging.getLogger("practice")

router = APIRouter(prefix="/practice", tags=["practice"])


# --- Request & Response Models ---

class PracticeNextRequest(BaseModel):
    exam: Optional[str] = "both"         # "jee", "neet", "both"
    class_level: Optional[str] = "both"  # "11", "12", "both"
    subject: Optional[str] = None        # Optional override for legacy callers
    # Focus mode. When set, only this chapter's questions are eligible — which
    # is both what the chapter picker has always promised and, incidentally,
    # the fastest this endpoint gets: a chapter is tens of rows where a subject
    # is hundreds.
    chapter_id: Optional[str] = None


class PracticeAnswerRequest(BaseModel):
    question_id: str
    chosen_option: Optional[str] = None
    chosen_value: Optional[float] = None
    # How long the question was actually ON SCREEN, measured by the client.
    #
    # The server can only see when it HANDED THE QUESTION OUT (question_serves
    # .served_at), and the app fetches one question ahead — so that clock
    # starts while the student is still reading the previous one, and keeps
    # running if they leave Practice and come back to a held question. Every
    # server-derived reading is therefore inflated by an unknown amount.
    # Trusted when present, ignored when absent or implausible.
    elapsed_ms: Optional[int] = None
    # True when the student pressed "I don't know" rather than answering. Still
    # graded incorrect and still spaced the same way; excluded from timing
    # statistics, because giving up is fast and solving is slow.
    gave_up: bool = False


class PracticeExplainRequest(BaseModel):
    question_id: str
    chosen_option: Optional[str] = None
    chosen_value: Optional[float] = None
    language: Optional[str] = None
    voice: Optional[str] = None


# --- Helper Functions ---

# Questions a student may ANSWER in a rolling 24 hours.
#
# Counted on attempts, not on serves. A serve is already self-limiting in the
# way that matters — record_serve burns the question out of this student's pool
# whether they answer it or not — so charging for one would punish a student
# twice for opening Practice and changing their mind. "150 questions a day" is
# a promise about questions faced, and an attempt is the record of facing one.
#
# Give-ups count. The student was shown the question and shown the worked
# solution; that is the expensive part and the useful part.
DAILY_QUESTION_LIMIT = 150

# How many times to re-pick if the chosen question fails the quality gate.
# Measured across every subject, the gate rejects 0% of servable rows, so this
# is a guard rather than a loop that runs.
QUALITY_RETRIES = 5

# ── The candidate pool, held in memory ──────────────────────────────────────
#
# THE POOL IS CONTENT, NOT PER-STUDENT. Every student sitting the same subject
# scans the identical set of servable rows; only the choosing is personal.
#
# Measured against production 2026-09-19, that scan is what /practice/next
# actually spends its time on. One round trip to Supabase costs ~292ms no
# matter what it carries, and the candidate fetch costs ~800ms — so ~510ms of
# every question served was transferring 1000 rows to pick one of them, again,
# for every student, on every tap. Trimming columns barely moved it (797→749ms)
# because `target_exams` and `chapter_name` are the heavy ones and the filters
# need both.
#
# So it is cached exactly like the syllabus tables in app/db.py, and for the
# same reason: it changes when the question bank is rebuilt, never per request.
# The exam, class and discipline rules still run in Python over these rows, so
# nothing about WHICH question a student may see moves into a cache.
#
# Only the unfocused pools are held. A chapter-focused session reads a few rows
# and is already fast, and caching per chapter would grow this without bound —
# this way it is at most one entry per subject per discipline, ~8 in total.
#
# TWO TIERS, because one worker's memory is no longer the whole server.
# WEB_CONCURRENCY is 4, so an in-process dict is four independent copies, each
# cold-fetching the same 278KB — and at low traffic a worker can go a whole TTL
# without being asked for the same subject twice, which is the case where a
# per-process cache helps least. Tier 2 is Redis, shared by every worker:
#
#   tier 1  this worker's dict   free
#   tier 2  Redis                one round trip for ~750KB
#   tier 3  Supabase             ~2.3s, three paged round trips
#
# Tier 3 got more expensive when the pool stopped being truncated at 1000 rows,
# which is precisely why no student should ever pay it: warm_candidate_pools()
# fills all four at startup, off any request path.
#
# With REDIS_URL unset tier 2 is skipped silently and this behaves exactly as
# the single-worker version did — the same degradation the rest of
# app/redis_store.py promises.
_CANDIDATE_TTL_S = float(os.getenv("CANDIDATE_CACHE_TTL_S", "600"))
_candidate_cache: Dict[str, Tuple[float, List[Dict[str, Any]]]] = {}

# A ceiling on the paged candidate read, so a runaway import cannot turn one
# cache fill into an unbounded number of round trips. The largest subject is
# ~3,100 servable rows today; 20,000 is room to grow several times over and
# still a bound. Hitting it is logged, never silent — silence is the bug this
# whole change exists to remove.
_CANDIDATE_MAX_ROWS = int(os.getenv("CANDIDATE_MAX_ROWS", "20000"))

# How often the pools are refetched, and how long a shared copy is allowed to
# live. Both exist so that a pool is never expired at the moment a student asks.
#
#   refresh  <  local TTL      the local copy is replaced before it expires
#   refresh  <<  share TTL     the Redis copy outlives the gap between refreshes
#
# Warming at startup alone left the pools warm for one TTL and cold afterwards:
# filled 18:46:40, expired 18:56, and a student at 19:17 paid 4206ms to refill.
_POOL_REFRESH_S = float(os.getenv("CANDIDATE_REFRESH_S", "240"))
_POOL_SHARE_TTL_S = int(os.getenv("CANDIDATE_SHARE_TTL_S", "3600"))


# BUMP THIS whenever what a cached pool CONTAINS changes.
#
# A TTL is not a migration. The paged read shipped without this and the warmer
# said so immediately, in production:
#
#   [PRACTICE WARM] physics     pool=supabase rows=2628   <- correct
#   [PRACTICE WARM] chemistry   pool=redis    rows=1000   <- the old deploy's
#   [PRACTICE WARM] mathematics pool=redis    rows=1000   <- truncated pool
#
# The new code read the previous version's 1000-row entries, found them
# perfectly valid JSON, and kept serving a third of the bank for as long as
# those keys lived. A version in the key means an old entry is not a stale
# value to be trusted — it is a different key nobody asks for.
_POOL_CACHE_VERSION = "v2-paged"


def _pool_key(key: str) -> str:
    return f"practice:pool:{_POOL_CACHE_VERSION}:{key}"


def clear_candidate_cache() -> None:
    """Drop this worker's cached pools — call after a question-bank import.

    Deliberately local. It cannot reach the other workers' copies or Redis, so
    a bank import still waits out the TTL; what it is for is tests, and a
    process that knows its own copy is stale.
    """
    _candidate_cache.clear()


PLACEHOLDER_OPTIONS = {'A': 'Option A', 'B': 'Option B', 'C': 'Option C', 'D': 'Option D'}

# --- Numerical grading tolerance -------------------------------------------
# `value_tolerance` on the row is authoritative when set. Nothing has ever
# populated it with a usable value: measured 2026-08-10 against production, it
# is 0 on 377 of the 383 servable numerical rows and NULL on the other 6. Zero
# fails the `> 0` guard below just as NULL does, so the fallback still decides
# every numerical grade in production today. Do not read "tolerance is set" as
# "a per-row tolerance is in force" -- check that it is greater than zero.
#
#   accept  <=>  abs(given - key) <= max(NUMERIC_ABS_FLOOR, abs(key) * NUMERIC_REL_FRACTION)
#
# A purely ABSOLUTE tolerance cannot work across this corpus. Measured range of
# correct_value over the 390 non-null servable numerical rows: min 0 (11 rows are
# exactly 0), smallest non-zero 0.06, median 10, max 65544. The previous
# hardcoded 1e-3 rejected a student answer of 9.8 against a key of 9.81.
#
# 0.5% is the tightest relative band that still absorbs 2-3 significant-figure
# rounding. The absolute floor only binds when the key is exactly 0.
#
# For INTEGER-valued keys at or above 200, an unbounded 0.5% band would exceed 1
# and start accepting the adjacent integer (201 against a key of 200). Those keys
# are capped at 0.5 so neighbouring integers stay distinct. The cap is bounded
# above by NUMERIC_INT_CAP_MAX because at very large magnitudes integer adjacency
# is not a meaningful distinction -- 6.02e23 is integer-valued as a float, and
# capping it at 0.5 would demand an exact match to 24 significant figures.
NUMERIC_REL_FRACTION = 0.005   # 0.5%
NUMERIC_ABS_FLOOR = 1e-6
NUMERIC_INT_CAP = 0.5
NUMERIC_INT_CAP_MIN = 200
NUMERIC_INT_CAP_MAX = 1e6      # corpus max is 65544, so every live row is covered


def grade_numerical(given: float, key: float, tolerance: Optional[float] = None) -> bool:
    """True when `given` matches `key`.

    Uses the per-row `value_tolerance` when it is present and positive;
    otherwise falls back to a relative band, capped for large integer keys.
    """
    given = float(given)
    key = float(key)
    if tolerance is not None and float(tolerance) > 0:
        return abs(given - key) <= float(tolerance)

    tol = max(NUMERIC_ABS_FLOOR, abs(key) * NUMERIC_REL_FRACTION)
    if NUMERIC_INT_CAP_MIN <= abs(key) < NUMERIC_INT_CAP_MAX and key.is_integer():
        tol = min(tol, NUMERIC_INT_CAP)
    return abs(given - key) <= tol


def is_quality_question(q: Dict[str, Any]) -> bool:
    """Quality Filter Rule (GATE 8.6): Exclude corrupt or low-quality rows."""
    text = (q.get("question_text") or "").strip()
    if len(text) < 20:
        return False

    q_type = q.get("question_type")
    opts = q.get("options") or {}
    
    opt_dict = {}
    if isinstance(opts, dict):
        opt_dict = {str(k).strip(): str(v).strip() for k, v in opts.items()}
    elif isinstance(opts, list):
        opt_dict = {str(i): str(v).strip() for i, v in enumerate(opts)}

    if opt_dict == PLACEHOLDER_OPTIONS:
        return False

    if q_type == "single_correct":
        non_empty = [v for v in opt_dict.values() if v]
        if len(non_empty) < 4:
            return False

    return True


def matches_exam(target_exams_val: Any, selected_exam: str) -> bool:
    """Checks if question matches selected exam mode."""
    if selected_exam == "both":
        return True
    
    if not target_exams_val:
        return False

    if isinstance(target_exams_val, str):
        try:
            exams_list = json.loads(target_exams_val)
        except Exception:
            exams_list = [target_exams_val]
    else:
        exams_list = target_exams_val

    exams_lower = [str(e).lower() for e in exams_list]
    
    if selected_exam == "jee":
        return any("jee" in e for e in exams_lower)
    elif selected_exam == "neet":
        return any("neet" in e for e in exams_lower)

    return True


# --- Endpoints ---

@router.post("/next")
def get_next_question(
    req: PracticeNextRequest,
    background_tasks: BackgroundTasks,
    user_id: str = Depends(get_current_user_id)
):
    """
    Selects 1 exam-based practice question following GATE 8 rules:
    - Exam-based weighted subject distribution (JEE, NEET, Both)
    - 21-attempt repeat spacing logic & prioritization of wrong attempts
    - Strict Quality Filter (GATE 8.6)
    """
    exam_mode = (req.exam or "both").strip().lower()
    if exam_mode not in ["jee", "neet", "both"]:
        exam_mode = "both"

    class_req = (req.class_level or "both").strip().lower()
    if class_req not in ["11", "12", "both"]:
        class_req = "both"

    # 1. Subject Selection via Weighted Random Distribution (GATE 8.3)
    target_discipline: Optional[str] = None

    if req.subject: # Legacy override if specifically provided
        chosen_subject = req.subject.strip().lower()
        if chosen_subject in ["math", "maths"]:
            chosen_subject = "mathematics"
    elif exam_mode == "jee":
        chosen_subject = random.choices(["physics", "chemistry", "mathematics"], weights=[0.333, 0.333, 0.334])[0]
    elif exam_mode == "neet":
        chosen_subject = random.choices(["biology", "chemistry", "physics"], weights=[0.50, 0.25, 0.25])[0]
        if chosen_subject == "biology":
            target_discipline = random.choices(["botany", "zoology"], weights=[0.50, 0.50])[0]
    else: # Both
        chosen_subject = random.choices(["physics", "chemistry", "mathematics", "biology"], weights=[0.25, 0.25, 0.25, 0.25])[0]

    # 2. Determine Class Chapter Constraints
    valid_chapter_ids: Optional[List[str]] = None
    valid_chapter_names: Optional[List[str]] = None

    # An explicit chapter pick OVERRIDES the class filter.
    #
    # Focus mode lists Class 11 and Class 12 chapters side by side, and the two
    # filters used to fight: a Class 11 student who picked "Current Electricity"
    # (Class 12) had every candidate thrown out by the class whitelist and was
    # told "No eligible practice questions available" -- for a chapter holding
    # 125 questions. Naming one chapter is a stronger, more deliberate signal
    # than the class on the profile: a student revising ahead, or back, means
    # it. `chapter_id` also pins the class unambiguously on its own, so nothing
    # leaks across classes by skipping the whitelist here.
    if class_req in ["11", "12"] and not req.chapter_id:
        class_int = int(class_req)
        # Chapters are syllabus, not per-user state — cached, so this stops
        # being a round trip on every question after the first.
        chapter_rows = [
            c for c in fetch_all_cached("chapters", "id, name, subject, class_level")
            if (c.get("subject") or "").strip().lower() == chosen_subject
            and c.get("class_level") == class_int
        ]
        valid_chapter_ids = [row["id"] for row in chapter_rows]
        valid_chapter_names = [row["name"] for row in chapter_rows if row.get("name")]

    # 3. Fetch User Practice Attempts (for 21-attempt repeat spacing logic - GATE 8.4)
    #
    # The MOST RECENT page, explicitly — not an unbounded ascending read.
    #
    # This asked for every attempt ordered created_at ASC with no limit, and
    # PostgREST caps a response at 1000 rows without reporting that it did (the
    # hazard POSTGREST_PAGE in app/db.py is named after). Ascending + capped
    # means a student past 1000 attempts was handed their OLDEST 1000 and
    # nothing since, which broke more than the spacing:
    #
    #   * `used_today` counts rows newer than 24h. None of the oldest 1000 are,
    #     so it came back 0 and the 150/day cap silently stopped applying to
    #     exactly the heaviest users.
    #   * `attempts_since` was measured against a frozen n_total_attempts of
    #     1000, so nearly every wrong answer looked 21-attempts stale and Tier 1
    #     swallowed the selection.
    #
    # Ordering desc and taking one page fixes both: today's attempts are always
    # present (the daily cap is 150, so a day cannot outrun a 1000-row window),
    # and the gap arithmetic below stays exact because it only ever asks how
    # many attempts came AFTER a given one — which is a within-window question.
    # Rows are reversed back to ascending so the indexing below is unchanged.
    #
    # Still one round trip, deliberately: the comment on `used_today` records
    # that adding a query at the front of this handler hit an HTTP/2 GOAWAY and
    # took the endpoint down, so this must not become two.
    ATTEMPT_WINDOW = POSTGREST_PAGE

    def _read_attempts():
        return (
            supabase.table("practice_attempts")
            .select("id, question_id, is_correct, created_at")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .limit(ATTEMPT_WINDOW)
            .execute()
        )

    # Which tier answered, and what still needs sharing. Both are reported in
    # the log line below: this endpoint was shipped without a way to see inside
    # it, and the first production numbers were then unreadable — a slow call
    # could have been a cold pool, a dead Redis, or a slow Supabase, and the
    # logs could not tell them apart.
    pool_tier = "supabase"
    to_share: Optional[List[Dict[str, Any]]] = None
    share_key: Optional[str] = None

    def _read_candidates():
        """The servable pool for this subject — cached. See _candidate_cache."""
        nonlocal pool_tier, to_share, share_key
        if req.chapter_id:
            # Focused sessions read a few rows and are already cheap; caching
            # per chapter would grow the cache without bound.
            pool_tier = "focused"
            return _fetch_pool(chosen_subject, target_discipline, req.chapter_id)
        if _CANDIDATE_TTL_S <= 0:
            pool_tier = "off"
            return _fetch_pool(chosen_subject, target_discipline)

        rows, pool_tier, share = _cached_pool(chosen_subject, target_discipline)
        if share is not None:
            # Handed to a background task rather than written here. Serialising
            # ~750KB and PUTting it are real work, and doing both before
            # returning made a cold call slower than it had been with no cache
            # at all — the student paid to warm a pool they were not going to
            # read again. This worker already has its copy; the share is for the
            # other three.
            to_share = share
            share_key = _pool_key(f"{chosen_subject}|{target_discipline or ''}")
        return rows

    # Two reads, one wave. The attempt history and the candidate pool have
    # nothing to say to each other, and running them back to back was a whole
    # Supabase round trip of pure waiting on the tap behind every question.
    # `reads`, not `pool` — `pool` is the tier pool further down.
    wave1_t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=2) as reads:
        attempts_task = reads.submit(_read_attempts)
        candidates_task = reads.submit(_read_candidates)
        attempts_res = attempts_task.result()
        candidate_rows = candidates_task.result()
    wave1_ms = int((time.perf_counter() - wave1_t0) * 1000)

    if to_share is not None and share_key:
        background_tasks.add_task(redis_store.cache_set_json, share_key,
                                  to_share, int(_CANDIDATE_TTL_S))

    # Oldest-first again, which is what latest_attempt_map's index means.
    all_user_attempts = list(reversed(attempts_res.data or []))
    # Within-window total. A question whose last attempt predates the window is
    # simply absent from latest_attempt_map and lands in Tier 2 (unseen) rather
    # than Tier 1/3 — correct in effect, since anything 1000 attempts old is far
    # past the 21-attempt spacing gate either way.
    n_total_attempts = len(all_user_attempts)

    # The day's tally, counted from the attempts already in hand.
    #
    # This used to be its own query, and that one extra round trip is what took
    # /practice/next down: the Supabase client pools ONE HTTP/2 connection, and
    # the server sends GOAWAY with last_stream_id=3, so adding a request at the
    # front pushed the chapters query onto a stream the connection would no
    # longer accept — "httpx.RemoteProtocolError: ConnectionTerminated" at the
    # line that had nothing to do with the change. Every attempt is already
    # here, with created_at, so the count is free.
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    used_today = 0
    for att in all_user_attempts:
        created = att.get("created_at")
        if not created:
            continue
        try:
            if datetime.fromisoformat(created.replace("Z", "+00:00")) >= since:
                used_today += 1
        except (TypeError, ValueError):
            continue

    if used_today >= DAILY_QUESTION_LIMIT:
        # Reuses the `exhausted` shape the client already renders, with a
        # reason so it can tell "you are done for today" from "this filter has
        # nothing left" — the two need different words and different advice.
        return {
            "exhausted": True,
            "reason": "daily_limit",
            "message": (
                f"That's all {DAILY_QUESTION_LIMIT} for today. Come back tomorrow — "
                "or go over what you got wrong with Drona."
            ),
            "questions_used_today": used_today,
            "daily_limit": DAILY_QUESTION_LIMIT,
        }

    # Track most recent attempt index and status for each question
    latest_attempt_map: Dict[str, Dict[str, Any]] = {}
    for idx, att in enumerate(all_user_attempts):
        q_id = att.get("question_id")
        if q_id:
            latest_attempt_map[q_id] = {
                "is_correct": att.get("is_correct", False),
                "attempt_index": idx + 1 # 1-based attempt sequence
            }

    # 4. Candidate questions — fetched above, in the same wave as the attempts.
    #
    # Only what CHOOSING needs. This used to select the full row —
    # question_text, options and diagram included — for every candidate, to pick
    # one. Measured against production on physics (879 servable rows), three
    # runs each:
    #
    #     full columns    1165 ms   0.76 MB
    #     these columns    348 ms   0.29 MB
    #
    # The chosen question's own row is read below. The quality gate moves with
    # it, because it needs the text and the options; that costs nothing in
    # practice, since the gate rejects 0% of servable rows in every subject —
    # measured, not assumed.
    #
    # STILL TRUNCATED, AND KNOWINGLY SO. There are 2,628-3,092 servable rows per
    # subject (counted against production 2026-09-19) and PostgREST caps a
    # response at 1000 without saying so, so selection sees roughly a third of
    # the bank. Paging it would cost the round trips this endpoint is trying to
    # shed, and a random offset would hide the Tier-1 rows the spacing logic
    # exists to find. The fix is to select in the database — see the note on
    # `_read_candidates` and migration 0050.

    # 5. Filter Candidates by Exam, Class, and Quality
    candidate_questions = []
    # Read-only over `candidate_rows`: these dicts may be the cached pool,
    # shared with every other request for this subject. Nothing below mutates
    # one — the tiers hold references and `tier.remove` only edits the tier.
    for q in candidate_rows:
        # source and needs_manual are filtered in the query now.
        # Exam Filter
        if not matches_exam(q.get("target_exams"), exam_mode):
            continue

        # Class Filter
        #
        # `chapter_id` is AUTHORITATIVE when present: it names exactly one row in
        # `chapters`, so it pins the class unambiguously. Name matching is only a
        # fallback for rows that still lack an id.
        #
        # Do NOT restore the old `match_id or match_name` form. Name matching
        # normalises "&" to "and", which collapses two genuinely distinct chapters:
        #   mathematics "Relations & Functions"  (class 11)
        #   mathematics "Relations and Functions" (class 12)
        # and "Probability" exists verbatim in both classes. Under the permissive
        # OR, a row whose id correctly said class 12 was still admitted into a
        # class-11 session because its name normalised into the class-11 list --
        # measured 2026-08-29 against production: 131 class-12 maths questions
        # leaked into the class-11 filter and 139 class-11 into class-12.
        if valid_chapter_ids is not None:
            q_chap_id = q.get("chapter_id")
            q_chap_name = q.get("chapter_name")
            if q_chap_id:
                if q_chap_id not in valid_chapter_ids:
                    continue
            else:
                match_name = False
                if valid_chapter_names and q_chap_name:
                    match_name = any(
                        q_chap_name.strip().lower().replace("&", "and") == v_name.strip().lower().replace("&", "and")
                        for v_name in valid_chapter_names
                    )
                if not match_name:
                    continue

        # Biology's Botany/Zoology filter is applied by the query now — see
        # `_read_candidates`. Doing it here meant transferring the half of
        # biology this session cannot use in order to throw it away.

        # Quality (GATE 8.6) is checked on the chosen question, not here: it
        # reads question_text and options, which the light select above does
        # not carry.
        candidate_questions.append(q)

    # 6. Empty Pool Handling (GATE 8.5)
    if not candidate_questions:
        return {
            "exhausted": True,
            "reason": "pool_empty",
            "message": f"No eligible practice questions available for subject '{chosen_subject.capitalize()}' under selected exam/class filters.",
            "questions_used_today": used_today,
            "daily_limit": DAILY_QUESTION_LIMIT,
        }

    # 7. Tier-Based Selection (GATE 8.4)
    # Tier 1: Previously wrong questions eligible after 21 attempts (Prioritized)
    # Tier 2: Unseen questions (Never attempted by user)
    # Tier 3: Correctly answered or locked questions (Re-enter on pool exhaustion)
    tier1_wrong_eligible = []
    tier2_unseen = []
    tier3_fallback = []

    for q in candidate_questions:
        q_id = q["id"]
        if q_id not in latest_attempt_map:
            tier2_unseen.append(q)
        else:
            att_info = latest_attempt_map[q_id]
            is_corr = att_info["is_correct"]
            att_idx = att_info["attempt_index"]
            attempts_since = n_total_attempts - att_idx

            if not is_corr and attempts_since >= 21:
                tier1_wrong_eligible.append(q)
            else:
                tier3_fallback.append(q)

    # Select single question based on priority hierarchy, then read its full
    # row. The quality gate runs here rather than over every candidate: it
    # needs question_text and options, and it rejects 0% of servable rows, so
    # the loop below effectively never takes a second turn. It is a loop and
    # not a single read because "effectively never" is not never, and a
    # student must not be handed a corrupt row just because it was picked.
    full = None
    concept_task = None
    wave2_t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=2) as picked:
        for _ in range(QUALITY_RETRIES):
            pool = tier1_wrong_eligible or tier2_unseen or tier3_fallback
            if not pool:
                break
            candidate = random.choice(pool)
            # The full row and the display concept are both keyed on this id and
            # neither needs the other's answer, so they go out together instead
            # of one after the other. `concept` on the candidate is the same
            # column resolve_display_concept was being handed off the full row.
            # The default-arg binding is deliberate: a bare closure over
            # `candidate` in a loop would capture the variable, not this value.
            row_task = picked.submit(
                lambda cid=candidate["id"]: (
                    supabase.table("questions")
                    .select("id, question_text, question_type, options, "
                            "chapter_name, concept, difficulty, diagram")
                    .eq("id", cid)
                    .limit(1)
                    .execute()
                    .data
                )
            )
            pending_concept = picked.submit(
                resolve_display_concept, candidate["id"], candidate.get("concept")
            )
            row = row_task.result()
            if row and is_quality_question(row[0]):
                full = row[0]
                concept_task = pending_concept
                break
            # Drop it from every tier so the next turn cannot pick it again.
            for tier in (tier1_wrong_eligible, tier2_unseen, tier3_fallback):
                if candidate in tier:
                    tier.remove(candidate)

    if full is None:
        return {
            "exhausted": True,
            "reason": "pool_empty",
            "message": f"No eligible practice questions available for subject '{chosen_subject.capitalize()}' under selected exam/class filters.",
            "questions_used_today": used_today,
            "daily_limit": DAILY_QUESTION_LIMIT,
        }

    wave2_ms = int((time.perf_counter() - wave2_t0) * 1000)
    # The one line that makes a slow call diagnosable. `pool` says which tier
    # answered, so "2.4s" can be read as a cold pool, a Redis miss, or a slow
    # Supabase rather than guessed at.
    logger.info(
        "[PRACTICE NEXT] subject=%s pool=%s candidates=%d wave1=%dms wave2=%dms",
        chosen_subject, pool_tier, len(candidate_rows), wave1_ms, wave2_ms,
    )

    selected = full
    q_type = selected.get("question_type")
    options = selected.get("options") if q_type != "numerical" else None

    # question.served — burns the item and starts the silent pace timer.
    #
    # Deferred: it is two round trips (a count, then an insert) and the student
    # is waiting on none of it. The row still lands within a second, long
    # before any answer can close it, and the pace clock it starts has been
    # superseded by the client's own `elapsed_ms` anyway.
    background_tasks.add_task(_serve_quietly, user_id, selected["id"])

    diagram = selected.get("diagram")
    if isinstance(diagram, str):
        try:
            diagram = json.loads(diagram)
        except (TypeError, ValueError):
            diagram = None

    return {
        "question_id": selected["id"],
        "question_text": selected.get("question_text"),
        "question_type": q_type,
        "options": options,
        "chapter_name": selected.get("chapter_name"),
        # Resolved alongside the full-row read above, not after it.
        "concept": concept_task.result(),
        "difficulty": selected.get("difficulty"),
        "diagram": diagram,
        # So the client can show the day's remaining count without a second
        # call. `used_today` is the count BEFORE this question is answered.
        "questions_used_today": used_today,
        "daily_limit": DAILY_QUESTION_LIMIT,
    }


def _serve_quietly(user_id: str, question_id: str) -> None:
    """record_serve, after the response. Never allowed to break serving."""
    try:
        record_serve(user_id, question_id, context="practice")
    except Exception as e:
        print(f"[PRACTICE SERVE ERROR] Failed to record serve: {e}")


def _record_answer(user_id: str, req: PracticeAnswerRequest, is_correct: bool, raw_difficulty):
    """Scoring and the attempt row — everything the STUDENT is not waiting for.

    Runs after the response has gone out. Order still matters between these
    two: the first-attempt gate inside apply_answer_scoring counts prior
    attempts, so the current one must not be in the table yet.
    """
    try:
        apply_answer_scoring(
            user_id=user_id,
            question_id=req.question_id,
            is_correct=is_correct,
            raw_difficulty=raw_difficulty,
            mode="practice",
            elapsed_ms=req.elapsed_ms,
            gave_up=req.gave_up,
        )
    except Exception as e:
        print(f"[PRACTICE SCORING ERROR] Failed to score answer: {e}")

    try:
        supabase.table("practice_attempts").insert({
            "user_id": user_id,
            "question_id": req.question_id,
            "is_correct": is_correct,
            "mode": "practice",
            # Requires migration 0043. PostgREST rejects the WHOLE insert on
            # an unknown column, so this must not ship ahead of it.
            "gave_up": req.gave_up,
        }).execute()
    except Exception as e:
        print(f"[PRACTICE ANSWER ERROR] Failed to record attempt: {e}")


@router.post("/answer")
def submit_answer(
    req: PracticeAnswerRequest,
    background_tasks: BackgroundTasks,
    user_id: str = Depends(get_current_user_id)
):
    """
    Grades the answer and returns it; records it afterwards.

    Grading needs ONE round trip — the question's ground truth. Everything
    else this endpoint does (concept mastery, closing the serve, the attempt
    row) is bookkeeping the student is not waiting for, and it was five more
    sequential round trips at ~310ms each in front of the worked solution.
    Measured end to end at ~1.5s of pure waiting for something already known
    after the first 300ms.

    So the grade goes back immediately and the bookkeeping runs in a
    background task. `scoring` is no longer in the response: nothing reads it
    — not this app, not the web client — and returning it would mean waiting
    for the very work being moved off the path.
    """
    # 1. Fetch target question with ground truth answers
    q_res = (
        supabase.table("questions")
        .select("id, question_type, correct_option, correct_value, value_tolerance, solution, options, difficulty")
        .eq("id", req.question_id)
        .limit(1)
        .execute()
    )

    if not q_res.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Question with ID '{req.question_id}' not found."
        )

    q_data = q_res.data[0]
    q_type = q_data.get("question_type")

    is_correct = False
    correct_option = q_data.get("correct_option")
    correct_value = q_data.get("correct_value")
    solution = q_data.get("solution")

    # 2. Grade answer based on question_type
    if q_type == "numerical":
        if correct_value is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Numerical question lacks correct_value ground truth."
            )
        if req.chosen_value is not None:
            is_correct = grade_numerical(
                req.chosen_value, correct_value, q_data.get("value_tolerance")
            )
    else:
        if req.chosen_option and correct_option:
            is_correct = req.chosen_option.strip().lower() == correct_option.strip().lower()

    # 3. Everything else happens after the student has their answer.
    background_tasks.add_task(
        _record_answer, user_id, req, is_correct, q_data.get("difficulty")
    )

    return {
        "is_correct": is_correct,
        "correct_option": correct_option,
        "correct_value": correct_value,
        "solution": solution,
    }


@router.get("/stats")
def get_practice_stats(
    user_id: str = Depends(get_current_user_id)
):
    """
    Calculates lifetime practice statistics for the authenticated user.
    """
    # Counted by the database, not by fetching rows and calling len() on them.
    # The old read pulled every attempt row to produce two integers, and
    # PostgREST's silent 1000-row cap meant a student past 1000 attempts had
    # their LIFETIME stats frozen at "1000 attempted" forever. Two counts with
    # limit(0) return no rows at all, so this is both correct and lighter than
    # what it replaces. (Same shape as the ledger counts in routers/progress.py.)
    attempted_count = (
        supabase.table("practice_attempts").select("id", count="exact")
        .eq("user_id", user_id).limit(0).execute().count or 0
    )
    correct_count = (
        supabase.table("practice_attempts").select("id", count="exact")
        .eq("user_id", user_id).eq("is_correct", True).limit(0).execute().count or 0
    )

    accuracy = round((correct_count / attempted_count) * 100, 1) if attempted_count > 0 else 0.0

    return {
        "attempted": attempted_count,
        "correct": correct_count,
        "accuracy": accuracy
    }


class PracticeFollowUpTurn(BaseModel):
    role: str
    content: str


class PracticeFollowUpRequest(BaseModel):
    question: str
    history: List[PracticeFollowUpTurn] = []
    pcm: bool = False


def _question_as_followup_context(question_id: str) -> Dict[str, Any]:
    """A practice question in the shape `followup_context` reads.

    Built HERE from the stored row, never accepted from the request — the same
    rule the doubts endpoint states, for the same reason: a request that could
    carry its own question and answer could have the model explain a solution
    that was never given.

    The two stores disagree on shape and this is where they are reconciled:
    `questions.options` is a map {"A": "..."} where a doubt carries a list of
    {label, text}, and `solution.steps` is a list of strings where a doubt
    carries {n, text}.
    """
    res = (
        supabase.table("questions")
        .select("id, question_text, options, correct_option, correct_value, solution")
        .eq("id", question_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"Question with ID '{question_id}' not found.")
    q = res.data[0]

    options = q.get("options")
    if isinstance(options, str):
        try:
            options = json.loads(options)
        except json.JSONDecodeError:
            options = None
    opts = ([{"label": k, "text": v} for k, v in options.items()]
            if isinstance(options, dict) else [])

    solution = q.get("solution")
    if isinstance(solution, str):
        try:
            solution = json.loads(solution)
        except json.JSONDecodeError:
            solution = None
    raw_steps = (solution or {}).get("steps") if isinstance(solution, dict) else None
    # Strip the rendering marks before the model sees them. A stored step is
    # `Title.\nprose\n$maths$\nnote` — the `$` pair tells the app to draw the
    # line as a formula and `<b>` bolds a term. To the model they are noise it
    # would reasonably imitate, and a follow-up answer arriving full of `$`
    # would be read literally by a client that only slabs whole lines.
    steps = [
        {"n": i + 1,
         "text": re.sub(r"</?b>", "", str(t)).replace("$", "").strip()}
        for i, t in enumerate(raw_steps or [])
    ]

    answer = q.get("correct_option")
    if answer is None and q.get("correct_value") is not None:
        answer = str(q["correct_value"])

    return {
        "question_text": q.get("question_text") or "",
        "options": opts,
        "steps": steps,
        "answer": answer,
    }


@router.post("/{question_id}/ask")
def ask_about_question(question_id: str, body: PracticeFollowUpRequest,
                       user_id: str = Depends(get_current_user_id)):
    """POST /practice/{id}/ask — a question about the working already on screen.

    The Practice twin of `/doubts/{id}/ask`. A student who has just submitted an
    answer and is reading the solution wants to ask about THAT, and sending them
    into a live Drona session to do it takes away the very thing they are asking
    about — so the solution stays on screen and the answer comes to it.
    """
    question = (body.question or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="Ask something first.")
    context = _question_as_followup_context(question_id)
    voice, language = _tutor_prefs_for(user_id)
    return _followup_response(context, question_id, user_id, question,
                              [{"role": t.role, "content": t.content}
                               for t in body.history],
                              tutor_voice=voice, tutor_language=language,
                              use_pcm=body.pcm)


@router.post("/{question_id}/ask-voice")
async def ask_about_question_aloud(
    question_id: str,
    audio: UploadFile = File(..., description="The held recording"),
    history: str = Form("[]"),
    pcm: str = Form("0"),
    user_id: str = Depends(get_current_user_id),
):
    """POST /practice/{id}/ask-voice — the same thing, asked out loud."""
    context = await asyncio.to_thread(_question_as_followup_context, question_id)
    return await followup_voice_response(context, question_id, user_id,
                                         audio, history, pcm)


class PracticeSpeakRequest(BaseModel):
    """The `spoken` line from a follow-up answer just given."""
    text: str


@router.post("/{question_id}/speak-stream")
async def speak_practice_followup(question_id: str, body: PracticeSpeakRequest,
                                  user_id: str = Depends(get_current_user_id)):
    """POST /practice/{id}/speak-stream — the follow-up answer read aloud.

    The fallback for when the inline voice on `/ask` produced no chunks. There
    is no ownership row to check the way a doubt has one: the text being spoken
    came from our own stream a moment ago, and the endpoint synthesises whatever
    text a signed-in student hands it either way.
    """
    said = (body.text or "").strip()
    if not said:
        raise HTTPException(status_code=400, detail="Nothing to say.")
    return await speak_stream_response(said, question_id, user_id)


@router.post("/explain")
def explain_drona(
    req: PracticeExplainRequest,
    user_id: str = Depends(get_current_user_id)
):
    """
    Creates a practice_explain Drona session seeded with this question's full
    context (stem, options, the student's answer, the correct answer, the
    solution). The live tutor turn itself is generated over the WebSocket
    (POST /drona/session/{id}/live), not here — this endpoint only creates
    the session row and returns the session_id the frontend needs to open it.
    """
    q_res = (
        supabase.table("questions")
        .select("id, question_text, question_type, options, correct_option, correct_value, value_tolerance, solution, chapter_id")
        .eq("id", req.question_id)
        .limit(1)
        .execute()
    )
    if not q_res.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Question with ID '{req.question_id}' not found."
        )

    q = q_res.data[0]
    q_type = q.get("question_type")
    correct_option = q.get("correct_option")
    correct_value = q.get("correct_value")

    # Re-derive correctness with the same rule /practice/answer grades with,
    # rather than trusting the client — also makes this endpoint work even if
    # /practice/answer was never called for this question_id.
    is_correct = False
    if q_type == "numerical" and correct_value is not None and req.chosen_value is not None:
        is_correct = grade_numerical(req.chosen_value, correct_value, q.get("value_tolerance"))
    elif req.chosen_option and correct_option:
        is_correct = req.chosen_option.strip().lower() == correct_option.strip().lower()

    language = normalize_language(req.language)
    voice = normalize_voice(req.voice)

    practice_seed = {
        "question_text": q.get("question_text"),
        "question_type": q_type,
        "options": q.get("options"),
        "chosen_option": req.chosen_option,
        "chosen_value": req.chosen_value,
        "correct_option": correct_option,
        "correct_value": correct_value,
        "solution": q.get("solution"),
        "is_correct": is_correct,
    }

    session_row = {
        "user_id": user_id,
        "mode": "practice_explain",
        "question_id": req.question_id,
        "chapter_id": q.get("chapter_id"),
        "practice_seed": practice_seed,
        "language": language,
        "tutor_voice": voice,
        "phase": "teaching",  # WS auto-fires turn 1 on connect when phase == "teaching"
        "prompt_version": "practice_explain_v1",
    }

    sess_res = supabase.table("drona_sessions").insert([session_row]).execute()
    if not sess_res.data:
        raise HTTPException(status_code=500, detail="Failed to create practice-explain session")

    session_id = sess_res.data[0]["id"]
    return {
        "session_id": session_id,
        "phase": "teaching",
        "language": language,
        "tutor_voice": voice,
        "tutor_name": tutor_name(voice),
    }

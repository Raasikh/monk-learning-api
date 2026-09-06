"""The archetype classification, and the ONE question the runtime asks it.

WHY THIS FILE EXISTS
--------------------
`docs/widget-routing.md` (mobile repo) specifies a hybrid router whose FIRST
path is "`v2_confidence == "high"` -> route deterministically to
`archetype_v2`". That path was unimplemented server-side, and could not be
implemented, because this repo could not read the classification at all:

    concepts table columns: active, chapter_id, created_at, display_order,
                            exams, id, key, name, teach_order
    files matching *archetype* in this repo (before this one): none

The column lives in the mobile repo as `content/concept-archetypes.csv`, the
output of an 8-agent adversarial reclassification. `concept_archetypes.csv`
beside this file is a VERBATIM copy of it, refreshed only by
`scripts/sync_concept_archetypes.py` and drift-checked by
`tests/drona/test_concept_archetypes.py` — the same discipline as
`registry_manifest.json`, for the same reason.

ONLY `high` NAMES A WIDGET, AND THAT IS MEASURED
------------------------------------------------
From the mobile README's blind 50-row adjudication:

    high  21/21 = 100%      med  18/26 = 69%      low  1/3 = 33%

and the residual error has a DIRECTION: of ten disagreements, the classifier
claimed a diagram where the adjudicator said none 6 times against 3, and all
ten were `med` or `low`. So `med` leans toward FALSELY claiming a diagram. A
deterministic router built on `med` would put a wrong picture on a live board
with no path to notice. `high` is the gate; widening it is a re-measurement,
not a config change.

WHAT "UNREACHABLE" MUST LOOK LIKE
---------------------------------
The recurring defect in this project is a check that PASSES on absent
information. If the CSV cannot be read, every concept would look non-high and
the system would route exactly as it did before while reporting nothing wrong.
So a load failure is recorded in `LOAD_ERROR`, logged at ERROR once, and
carried into every verdict as `confidence == "table_unreadable"` — a value
that is not "not high", it is "we do not know". `tests/drona/
test_concept_archetypes.py::test_the_archetype_table_actually_loaded` FAILS
when it is set, so an unreadable table cannot ride a green test run.

A CONCEPT THE TABLE DOES NOT KNOW is a different, ordinary thing: it gets
`confidence == "unknown"` and falls to the non-high branch. It never crashes
and never claims a widget. Measured against the live `concepts` table:
1,153 of 1,154 active concepts join exactly on
(subject, class_level, chapter_order, name); the single miss is
physics 11 ch6 "Rigid Bodies & Types of Motion", which the CSV spells
"Rigid Bodies and Types of Motion". That `&` is NOT normalised here — a
normaliser is a widened gate, and the concept in question is
`not_in_scope` anyway, so the miss costs nothing and stays visible.
"""

import csv
import logging
import os
from typing import Dict, NamedTuple, Optional, Tuple

from app.drona.widget_registry import WIDGET_VERSIONS

logger = logging.getLogger(__name__)

CSV_PATH = os.path.join(os.path.dirname(__file__), "concept_archetypes.csv")

#: The four fields that identify a concept. Name ALONE is not the key: the
#: corpus has one collision ("Hydrogen Spectrum and Spectral Series" is both
#: physics 12 ch12 and chemistry 11 ch2), and `chapters` carries subject,
#: class_level and chapter_order already, so the wider key costs nothing.
Key = Tuple[str, int, int, str]

#: Confidence values that exist in the file. `not_in_scope` is 747 of 1,154
#: rows — the reclassification covered 35% of the corpus — and it is a
#: perfectly ordinary non-high value, not an error.
_FILE_CONFIDENCES = {"high", "med", "low", "none", "not_in_scope"}


class ArchetypeVerdict(NamedTuple):
    """What the column says about one concept, and whether it decides anything.

    `widget` is non-None ONLY when the row is `high` AND names an id the
    client registry actually ships. Everything else — med, low, none,
    not_in_scope, a concept the table does not know, an unreadable table, or a
    `high` row naming something that is not a registered widget — leaves it
    None and the caller falls to the model-choice branch.
    """
    widget: Optional[str]
    archetype: str
    confidence: str
    why: str


#: Set when the CSV could not be read or parsed. None means it loaded.
LOAD_ERROR: Optional[str] = None

TABLE: Dict[Key, Tuple[str, str]] = {}


def _load() -> None:
    global LOAD_ERROR
    try:
        with open(CSV_PATH, "r", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        if not rows:
            raise ValueError("file parsed to zero rows")
        required = {"subject", "class_level", "chapter_order", "concept",
                    "archetype_v2", "v2_confidence"}
        missing = required - set(rows[0].keys())
        if missing:
            raise ValueError(f"missing columns {sorted(missing)}")
        for r in rows:
            try:
                key = (r["subject"].strip().lower(), int(r["class_level"]),
                       int(r["chapter_order"]), r["concept"].strip())
            except (TypeError, ValueError):
                # A row whose class/chapter is not an integer cannot be joined
                # to a chapter, so it is dropped rather than stored under a key
                # nothing will ever ask for.
                continue
            TABLE[key] = ((r["archetype_v2"] or "").strip(),
                          (r["v2_confidence"] or "").strip())
    except Exception as exc:
        LOAD_ERROR = f"{type(exc).__name__}: {exc}"
        TABLE.clear()
        # ERROR, not warning: with no table every concept silently looks
        # non-high and the deterministic path disappears without a symptom.
        logger.error(
            f"⚠️ [ARCHETYPE TABLE UNREADABLE] {CSV_PATH}: {LOAD_ERROR}. "
            f"Path 1 of docs/widget-routing.md is OFF for this process — every "
            f"segment will fall to the model-choice branch, and that is NOT the "
            f"same as 'no high-confidence concepts found'. "
            f"Run scripts/sync_concept_archetypes.py."
        )


_load()


def _version() -> str:
    """An identifier of the classification PASS, computed rather than typed.

    `docs/widget-routing.md` requires every routed segment to record
    `archetype_version` beside `route`, and it is a component of the plan cache
    key so a reclassification invalidates the plans whose widget it chose.

    It is sha256 of the CSV, first 16 hex — the same discipline as `prompt_sha`
    in migrations/0035, and for the same reason: `prompt_version` failed in
    this project by being a version string somebody maintained, so it moved
    when unrelated things moved and stayed still when the thing it named
    changed. A hash of the actual file cannot do either.

    "unreadable" when the file could not be read: an archetype_version on a run
    with no archetype table would be a populated, plausible field asserting a
    classification that was never consulted.
    """
    if LOAD_ERROR is not None:
        return "unreadable"
    try:
        import hashlib
        with open(CSV_PATH, "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()[:16]
    except Exception:
        return "unreadable"


ARCHETYPE_VERSION: str = _version()


def verdict(subject: Optional[str], class_level, chapter_order,
            concept_name: Optional[str]) -> ArchetypeVerdict:
    """The column's verdict for one concept. Total — never raises.

    Pure: takes the four join fields, touches no database. The caller supplies
    them (`concept_archetype_for_session` below is the one that reads them).
    """
    if LOAD_ERROR is not None:
        return ArchetypeVerdict(None, "", "table_unreadable",
                                f"archetype table unreadable ({LOAD_ERROR[:60]})")
    try:
        key: Key = (str(subject or "").strip().lower(), int(class_level),
                    int(chapter_order), str(concept_name or "").strip())
    except (TypeError, ValueError):
        # No chapter metadata to join on. Distinct from "the table does not
        # know this concept": nobody asked it anything.
        return ArchetypeVerdict(None, "", "unjoinable",
                                "no subject/class/chapter to join on")
    if not key[0] or not key[3]:
        return ArchetypeVerdict(None, "", "unjoinable",
                                "no subject/class/chapter to join on")

    row = TABLE.get(key)
    if row is None:
        return ArchetypeVerdict(None, "", "unknown",
                                f"not in the archetype table: {key[0]} {key[1]} ch{key[2]} "
                                f"{key[3]!r}")
    archetype, confidence = row
    if confidence != "high":
        return ArchetypeVerdict(None, archetype, confidence or "blank",
                                f"{archetype or 'blank'}@{confidence or 'blank'} — "
                                f"only `high` names a widget")
    if archetype not in WIDGET_VERSIONS:
        # 143 rows are `high`, but only 53 of them name a widget the client
        # ships. The rest are `none_symbolic` (61 — the content genuinely wants
        # no picture), `labelled_figure` (27 — an offline-authored ASSET, which
        # is a different resolution slot entirely and deliberately absent from
        # the client registry), `apparatus`, and the `gap_*` placeholders for
        # widgets that do not exist yet. All of them fall through here, which is
        # correct: naming one would offer the model an id `lookup()` cannot
        # resolve, and the board would draw nothing.
        return ArchetypeVerdict(None, archetype, "high",
                                f"high, but `{archetype or 'blank'}` is not a "
                                f"registered widget")
    return ArchetypeVerdict(archetype, archetype, "high",
                            f"high -> `{archetype}`")


# ── the runtime lookup ──────────────────────────────────────────────────────
# One indexed read per concept, cached, and it must never be able to fail a
# lesson — the same contract as `_precomputed_diagram` in tutor.py.
_SESSION_CACHE: Dict[str, ArchetypeVerdict] = {}


def concept_archetype_for_session(chapter_id: Optional[str],
                                  subtopic_key: Optional[str]) -> ArchetypeVerdict:
    """The verdict for the concept a session is teaching. Never raises.

    The join needs four fields the session does not carry: the concept's NAME
    (the session has its slug) and the chapter's subject, class_level and
    chapter_order. Both are one indexed read, and both are cached for the
    process — a concept's name and a chapter's number do not change under a
    running server.
    """
    if not chapter_id or not subtopic_key:
        return ArchetypeVerdict(None, "", "unjoinable", "no chapter or concept key")
    ck = f"{chapter_id}|{subtopic_key}"
    if ck in _SESSION_CACHE:
        return _SESSION_CACHE[ck]

    result = ArchetypeVerdict(None, "", "unjoinable", "lookup failed")
    try:
        from app.db import supabase
        con = (supabase.table("concepts").select("name")
               .eq("chapter_id", chapter_id).eq("key", subtopic_key)
               .eq("active", True).limit(1).execute().data or [])
        chap = (supabase.table("chapters")
                .select("subject, class_level, chapter_order")
                .eq("id", chapter_id).limit(1).execute().data or [])
        if con and chap:
            result = verdict(chap[0].get("subject"), chap[0].get("class_level"),
                             chap[0].get("chapter_order"), con[0].get("name"))
        else:
            result = ArchetypeVerdict(
                None, "", "unjoinable",
                f"no active concept row for {subtopic_key!r} in this chapter"
                if chap else f"no chapter row for {str(chapter_id)[:8]}")
    except Exception as exc:
        # A lookup that failed is NOT a concept without an archetype. It is
        # reported as its own confidence value so the turn summary can say so.
        result = ArchetypeVerdict(None, "", "lookup_error", f"{str(exc)[:70]}")
        logger.info(f"[ARCHETYPE] lookup skipped for {subtopic_key}: {str(exc)[:70]}")
    # A `lookup_error` IS NOT CACHED, and that is the difference between a blip
    # and a permanent verdict. Measured on the first Ecosystem precompute run:
    # one transient "Server disconnected" from the shared PostgREST client on
    # the very first concept, cached here, made every later caller in that
    # process see `lookup_error` for `energy-flow-and-the-ten-per-cent-law` —
    # so all 8 of its segments were recorded as never-asked and the concept was
    # silently excluded from a run that reported itself complete.
    #
    # Every OTHER value is cached, including "unknown" and "unjoinable": those
    # are answers. A concept's name and a chapter's number do not change under
    # a running process, but a socket does.
    if result.confidence != "lookup_error":
        _SESSION_CACHE[ck] = result
    return result

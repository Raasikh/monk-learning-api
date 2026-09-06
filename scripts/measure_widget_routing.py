"""Does the model actually USE the widget manifest? Measured, per segment.

WHY THIS SCRIPT EXISTS
----------------------
Commit d280436 put all nine registered widgets into the turn prompt
(`render_manifest_block`), widened the sanitizer from a hardcoded
`field_lines` branch to the whole registry, and demoted the diagram-template
keyword cue from a DECISION to a DEFAULT. Nothing measured whether any of that
changes what the model emits. This does.

Probe: Maths class 12, chapter "Application of Integrals"
(4aeaa5f2-e183-530c-abca-da24207c63f9). Nine lesson_plans with
`plan_json._status == "complete"`, 70 segments between them. The tenth plan
(`areas-involving-greatest-integer-and-fractional-part-functions`) is
`_status: "failed"` with a single stub segment and is EXCLUDED — it is not a
short plan, it is an absent one.

Every one of this chapter's ten concepts is area-under/between-curves content,
so `xy_plot` is the only defensible widget id. Any other name is a routing
miss, and is recorded as such rather than argued about.

HOW THE TURNS ARE DRIVEN
------------------------
Board widget payloads come from LIVE TURNS. `_attach_example_diagram` is the
precompute path and goes through `diagram_author` (tier 3), which emits SVG,
never a payload — so precompute cannot answer this question and the turns have
to be run. One `drona_sessions` row per plan; before each segment the row's
`current_segment` is set and `phase` reset to `teaching`, then
`process_tutor_turn_stream` is driven to exhaustion. `turn_within_segment` is
computed from `drona_turns` filtered by `segment_index`, so each segment gets
its own turn 1 — the teaching turn, which is the only turn a diagram directive
is written for.

WHAT IS INSTRUMENTED, AND WHY IT IS NOT ENOUGH TO READ THE SSE
--------------------------------------------------------------
The emitted `board_events` frame answers "did a widget reach the client". It
cannot answer "did the model CHOOSE one", because three separate things in
`_sanitize_board_events` can eat a chosen payload before it is emitted:

  * `sanitize_widget_payload` drops an unknown id or an unresolvable version;
  * on a turn with assigned plan items the model's board_events are discarded
    wholesale, and only ONE diagram is appended back — and only if the plan
    items did not already contribute one;
  * NO LONGER TRUE as of the tier-precedence change: a precomputed SVG is
    slot 4 and no longer suppresses slots 1-3. `board_slot` records which
    tier actually won, which is the field that distinguishes the column
    branch from the manifest branch.
    entirely, so the model is never asked.

Those are four completely different findings with four different fixes, and a
script that reports only the emitted frame lumps them. So this monkeypatches,
in the harness process only, never in app/:

    tutor.suggest_diagram_template   -> record _diag_hint
    tutor.resolve_board_slot         -> record which of the 5 tiers won
    tutor.sanitize_widget_payload    -> record every payload the model authored
                                        AND the gate's verdict on it
    tutor.parse_tutor_json           -> record the model's RAW board_events
    tutor.record_call_bg             -> record this turn's token counts

All five delegate to the real implementation. Nothing in app/ is changed: a
measurement that alters the thing it measures is not a measurement.

WHAT IS NOT JUDGED HERE
-----------------------
Whether the params are SANE. The full params object is dumped verbatim beside
the segment's objective and title for a human to judge. A script that scored
its own sanity would be scoring its own opinion.

Usage:
    set -a; source .env; set +a
    python3 scripts/measure_widget_routing.py [--limit N] [--out PATH]
"""

import argparse
import asyncio
import json
import os
import sys
import time
import traceback
import uuid
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db import supabase  # noqa: E402
from app.drona import tutor  # noqa: E402

# Chapter is a CLI argument, not a constant. The first run of this harness
# measured only Maths 12 Ch8, where every concept is v2_confidence
# "not_in_scope" -- so it could only ever exercise the manifest branch, and a
# reader could mistake "the column named nothing" for "the column is broken".
# Both branches need their own chapter.
CHAPTER_ID = ""       # set in main() from --subject/--class-level/--chapter
CHAPTER_NAME = ""
EXPECTED_WIDGET = ""  # set from --expect
USER_ID = os.getenv("MEASURE_USER_ID", "ab1347ac-8756-45ba-9f97-2e0b5d7e1bdc")


# ── instrumentation ──────────────────────────────────────────────────────────
# Per-turn scratch, reset by `_reset_probe`. Module-level rather than passed
# around because the patched functions are called from deep inside
# process_tutor_turn_stream and have no channel back to the caller.
PROBE: Dict[str, Any] = {}


def _reset_probe() -> None:
    PROBE.clear()
    PROBE.update({
        "diag_hint": None,
        "board_slot": None,
        "sanitize_calls": [],
        "model_raw_board_events": None,
        "tokens": None,
    })


_real_suggest_template = tutor.suggest_diagram_template
_real_resolve_slot = tutor.resolve_board_slot
_real_sanitize = tutor.sanitize_widget_payload
_real_parse = tutor.parse_tutor_json
_real_record = tutor.record_call_bg


def _patched_suggest_template(*texts: str):
    out = _real_suggest_template(*texts)
    PROBE["diag_hint"] = out
    return out


def _patched_resolve_slot(*a, **kw):
    out = _real_resolve_slot(*a, **kw)
    PROBE["board_slot"] = out
    return out


def _patched_sanitize(*args: Any, **kwargs: Any):
    """Pass EVERYTHING through. Never restate the wrapped signature.

    This wrapper used to be `(raw_payload)`, matching sanitize_widget_payload
    at the time. The routing change then added an `archetype_widget` kwarg, and
    every call on the archetype branch raised

        TypeError: _patched_sanitize() got an unexpected keyword argument
                   'archetype_widget'

    which `process_tutor_turn_stream` catches as "Error during LLM turn",
    sets turn_failed, and returns NO board events. 33 of Ecosystem's 40
    archetype turns blanked -- and it looked exactly like the product
    suppressing the board on precisely the concepts the column had named.
    An instrument that fails closed, in the shape of the thing it measures.

    *args/**kwargs cannot drift out of step with the wrapped signature again.
    """
    out = _real_sanitize(*args, **kwargs)
    PROBE["sanitize_calls"].append({
        "raw": args[0] if args else kwargs.get("raw_payload"),
        "kwargs": {k: v for k, v in kwargs.items() if k != "raw_payload"},
        "accepted": out is not None,
        "gated": out,
    })
    return out


def _patched_parse(*args: Any, **kwargs: Any):
    out = _real_parse(*args, **kwargs)
    try:
        PROBE["model_raw_board_events"] = (out or {}).get("board_events")
    except Exception:
        PROBE["model_raw_board_events"] = None
    return out


def _patched_record(model, service, **kw):
    PROBE["tokens"] = dict(kw.get("tokens") or {})
    PROBE["model_id"] = model
    PROBE["llm_ok"] = kw.get("ok")
    return _real_record(model, service, **kw)


def install_probes() -> None:
    tutor.suggest_diagram_template = _patched_suggest_template
    tutor.resolve_board_slot = _patched_resolve_slot
    tutor.sanitize_widget_payload = _patched_sanitize
    tutor.parse_tutor_json = _patched_parse
    tutor.record_call_bg = _patched_record


# ── the four-way classification of a non-fire ────────────────────────────────
# Rule 4 of the brief. These four have completely different fixes: a model that
# never names a widget needs a prompt/routing change; a model that names the
# wrong one needs the manifest descriptions fixed; a refused payload needs the
# params fixed; and a concept xy_plot cannot express needs a NEW WIDGET, or
# nothing at all — that last one is the schema working, not a failure.
#
# `xy-plot/index.tsx`'s own header is the authority on the last category: it
# lists, concept by concept, which of this chapter's ten it can and cannot
# draw. Copied here by subtopic_key rather than re-derived, so the classifier
# and the widget agree by construction.
CANNOT_EXPRESS = {
    # "NO — not functions of x": a circle needs upper/lower branches and
    # segment arithmetic, not a difference of antiderivatives.
    "area-of-regions-bounded-by-circles-and-ellipses",
    # "NO — takes two payloads": needs an array of (breakpoint, curve, coeffs).
    "area-of-regions-involving-modulus-and-piecewise-defined-functions",
    # "NO, except by drawing the picture transposed": needs a transpose flag.
    "area-by-integration-along-the-y-axis",
    # (greatest-integer is the failed plan and is excluded outright.)
}


def classify_non_fire(rec: Dict[str, Any]) -> str:
    """Why no widget payload reached the client on this segment."""
    calls = rec["sanitize_calls"]
    if calls:
        if any(c["accepted"] for c in calls):
            # The gate passed it and it still did not reach the board — that is
            # _sanitize_board_events dropping it, not a routing miss.
            return "accepted_but_not_emitted"
        names = [(c["raw"] or {}).get("widget") for c in calls]
        if any(n == EXPECTED_WIDGET for n in names):
            return "chose_xy_plot_payload_refused"
        return "chose_wrong_widget"
    if rec["subtopic_key"] in CANNOT_EXPRESS:
        return "widget_cannot_express_concept"
    return "model_chose_no_widget"


# ── the driver ───────────────────────────────────────────────────────────────
async def drain(session_id: str, user_id: str) -> Dict[str, Any]:
    """Run one turn and return the SSE frames that matter."""
    emitted_board: Optional[List[Dict[str, Any]]] = None
    meta: Optional[Dict[str, Any]] = None
    turn_error = None
    async for chunk in tutor.process_tutor_turn_stream(session_id, user_id, None, "teaching"):
        if not chunk.startswith("event: "):
            continue
        head, _, body = chunk.partition("\n")
        name = head[len("event: "):].strip()
        data = body[len("data: "):].strip() if body.startswith("data: ") else "{}"
        try:
            parsed = json.loads(data)
        except Exception:
            continue
        if name == "board_events":
            # The early-flush path can emit this twice; the LAST one is what the
            # client ends the turn holding.
            emitted_board = parsed.get("events")
        elif name == "meta":
            meta = parsed
        elif name == "turn_error":
            turn_error = parsed
    return {"board_events": emitted_board, "meta": meta, "turn_error": turn_error}


def load_plans() -> List[Dict[str, Any]]:
    rows = (supabase.table("lesson_plans")
            .select("id,subtopic_key,plan_json,segment_count")
            .eq("chapter_id", CHAPTER_ID).execute().data or [])
    out = []
    for r in rows:
        pj = r.get("plan_json") or {}
        status = pj.get("_status")
        if status != "complete":
            print(f"  ⏭️  EXCLUDED {r['subtopic_key']} — plan_json._status={status!r} "
                  f"({len(pj.get('segments') or [])} segments authored of "
                  f"{r.get('segment_count')})", flush=True)
            continue
        out.append(r)
    out.sort(key=lambda r: r["subtopic_key"])
    return out


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="stop after N segments")
    ap.add_argument("--out", default="scripts/widget_routing_results.jsonl")
    ap.add_argument("--subject", required=True)
    ap.add_argument("--class-level", type=int, required=True)
    ap.add_argument("--chapter", required=True, help="chapter name, exact")
    ap.add_argument("--expect", required=True,
                    help="the widget this chapter's content defensibly wants")
    args = ap.parse_args()

    global CHAPTER_ID, CHAPTER_NAME, EXPECTED_WIDGET
    _rows = (supabase.table("chapters").select("id,name")
             .eq("subject", args.subject).eq("class_level", args.class_level)
             .execute().data or [])
    _match = [c for c in _rows if c["name"] == args.chapter]
    if not _match:
        # Loud, and it names what IS there. A silent zero-plan run would report
        # 0/0 and read like a result.
        raise SystemExit(f"no chapter {args.chapter!r} in {args.subject} class "
                         f"{args.class_level}; have: {[c['name'] for c in _rows][:8]}")
    CHAPTER_ID, CHAPTER_NAME = _match[0]["id"], _match[0]["name"]
    EXPECTED_WIDGET = args.expect
    print(f"chapter: {CHAPTER_NAME} ({CHAPTER_ID})  expecting: {EXPECTED_WIDGET}", flush=True)

    install_probes()
    plans = load_plans()
    total_segments = sum(len((p["plan_json"] or {}).get("segments") or []) for p in plans)
    print(f"\n▶ {CHAPTER_NAME}: {len(plans)} complete plans, {total_segments} segments\n", flush=True)

    out_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), args.out)
    written = 0
    created_sessions: List[str] = []
    t_all = time.time()

    with open(out_path, "w", encoding="utf-8") as fh:
        for plan in plans:
            segments = (plan["plan_json"] or {}).get("segments") or []
            session_id = str(uuid.uuid4())
            supabase.table("drona_sessions").insert({
                "id": session_id,
                "user_id": USER_ID,
                "mode": "chapter",
                "chapter_id": CHAPTER_ID,
                "subtopic_key": plan["subtopic_key"],
                "language": "hinglish",
                "plan_id": plan["id"],
                "phase": "teaching",
                "current_segment": 1,
                "prompt_version": "v1",
            }).execute()
            created_sessions.append(session_id)
            print(f"── {plan['subtopic_key']} ({len(segments)} segments) "
                  f"session={session_id[:8]}", flush=True)

            for seg_idx, seg in enumerate(segments, 1):
                if args.limit and written >= args.limit:
                    break
                _reset_probe()
                # Reset rather than advance: the state machine's own transition
                # would take a segment three turns and a graded checkpoint to
                # leave, and this measures the TEACHING turn of each segment,
                # not a session's arc through them.
                supabase.table("drona_sessions").update({
                    "phase": "teaching",
                    "current_segment": seg_idx,
                    "attempts_on_current_question": 0,
                }).eq("id", session_id).execute()

                rec: Dict[str, Any] = {
                    "chapter": CHAPTER_NAME,
                    "subtopic_key": plan["subtopic_key"],
                    "plan_id": plan["id"],
                    "session_id": session_id,
                    "segment_index": seg_idx,
                    "segment_title": seg.get("title") or seg.get("heading"),
                    "segment_objective": seg.get("objective"),
                    "has_example_diagram_svg": bool(seg.get("example_diagram_svg")),
                    "harness_error": None,
                }
                t0 = time.time()
                try:
                    res = await drain(session_id, USER_ID)
                except Exception:
                    # Rule 6: a harness bug is not `fired: false`.
                    rec["harness_error"] = traceback.format_exc()[-2000:]
                    res = {"board_events": None, "meta": None, "turn_error": None}
                rec["latency_s"] = round(time.time() - t0, 2)

                rec["diag_hint"] = PROBE.get("diag_hint")
                rec["board_slot"] = PROBE.get("board_slot")
                rec["tokens"] = PROBE.get("tokens")
                rec["model_id"] = PROBE.get("model_id")
                rec["llm_ok"] = PROBE.get("llm_ok")
                rec["turn_error"] = res["turn_error"]
                rec["sanitize_calls"] = PROBE.get("sanitize_calls") or []
                rec["model_raw_board_events"] = PROBE.get("model_raw_board_events")
                # What the model reached for INSTEAD of a payload. Rule 2: this
                # is a result. A template name here with no sanitize_calls means
                # the model took the `_diag_hint` default and never considered
                # the manifest — a different finding from emitting nothing.
                rec["model_named_templates"] = [
                    e.get("template")
                    for e in (rec["model_raw_board_events"] or [])
                    if isinstance(e, dict) and e.get("template")
                ]

                emitted = res["board_events"] or []
                rec["emitted_event_types"] = [e.get("type") for e in emitted if isinstance(e, dict)]
                widget_events = [e for e in emitted
                                 if isinstance(e, dict) and isinstance(e.get("payload"), dict)]
                svg_events = [e for e in emitted
                              if isinstance(e, dict) and e.get("svg")]

                rec["fired"] = bool(widget_events)
                if widget_events:
                    w = widget_events[0]["payload"]
                    rec["widget"] = w.get("widget")
                    rec["widget_version"] = w.get("version")
                    rec["params"] = w.get("params")
                    rec["caption"] = widget_events[0].get("caption")
                    rec["route"] = widget_events[0].get("route")
                    rec["correct_widget"] = (w.get("widget") == EXPECTED_WIDGET)
                    rec["server_validated"] = True
                    rec["non_fire_reason"] = None
                else:
                    rec["widget"] = None
                    rec["params"] = None
                    # Rule 2: what the turn emitted INSTEAD is the result.
                    rec["emitted_instead"] = (
                        "svg" if svg_events
                        else ("text_only" if emitted else "nothing")
                    )
                    rec["svg_source"] = (
                        ("segment_example_diagram_svg" if seg.get("example_diagram_svg")
                         else "template_or_live")
                        if svg_events else None
                    )
                    rec["correct_widget"] = False
                    rec["server_validated"] = any(
                        c["accepted"] for c in rec["sanitize_calls"])
                    rec["non_fire_reason"] = (
                        None if rec["harness_error"] else classify_non_fire(rec))
                # Judged by a human. Left null on purpose — see the module docstring.
                rec["sane"] = None
                rec["client_validate"] = None  # filled by the jest pass

                fh.write(json.dumps(rec, default=str) + "\n")
                fh.flush()
                written += 1
                flag = ("💥 HARNESS" if rec["harness_error"]
                        else (f"✅ {rec['widget']}" if rec["fired"]
                              else f"—  {rec.get('non_fire_reason')}"))
                print(f"   seg {seg_idx}/{len(segments)}  diag={rec['diag_hint']!s:22s} "
                      f"slot={rec['board_slot']!s:18s} ex_svg={int(rec['has_example_diagram_svg'])} "
                      f"{rec['latency_s']:5.1f}s  {flag}", flush=True)
            if args.limit and written >= args.limit:
                break

    # Every row this run wrote to the production DB. drona_turns cascades off
    # drona_sessions (migrations/0005_drona.sql), so this clears the turn
    # history too. lesson_plans are pre-existing and are NOT touched.
    for sid in created_sessions:
        try:
            supabase.table("drona_sessions").delete().eq("id", sid).execute()
        except Exception as e:
            print(f"  ⚠️ cleanup failed for {sid}: {e}", flush=True)
    print(f"\n🧹 cleaned up {len(created_sessions)} synthetic sessions", flush=True)
    print(f"📄 {written} records -> {out_path}  ({time.time() - t_all:.0f}s)", flush=True)


if __name__ == "__main__":
    asyncio.run(main())

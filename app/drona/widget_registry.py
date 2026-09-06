"""The closed set of client-rendered board widgets, and the turn-time gate on them.

WHY THIS FILE EXISTS
--------------------
The client (monklearning-mobile, `lib/widgets/registry.ts`) is the single
source of truth for which widgets exist. Its own header says the server "reads
the same id/version list", and until now that was aspirational: the server knew
exactly one widget name, `field_lines`, hardcoded in tutor.py. The model was
never shown the set, so it could not choose from it — nine verified widgets on
the client, one reachable from the server.

HOW DRIFT IS PREVENTED
----------------------
`registry_manifest.json` beside this file is a VERBATIM COPY of the mobile
repo's generated `build/registry-manifest.json` (produced by
`npm run export-registry`). It is never hand-edited. Two mechanisms keep it
honest, and they cover different failure modes:

  1. `tests/drona/test_widget_registry.py::test_server_manifest_matches_the_
     mobile_registry_export` compares this copy against the mobile repo's
     generated artifact when a checkout is reachable. When it is NOT reachable
     the test SKIPS with an explicit "drift unverified" reason — it does not
     pass. A green run with that skip in it means "not checked", which is a
     different thing from "checked and equal", and the test output says so.

  2. `WIDGET_SPECS` below is the one hand-written part — the manifest carries
     `{id, version, animatable}` and nothing about what a widget draws or what
     params it takes, which is precisely what the model needs. A test asserts
     `set(WIDGET_SPECS) == {every id in the manifest}` in BOTH directions, and
     that test needs no mobile checkout. So a widget added to the registry and
     re-exported fails the build until someone describes it, instead of
     staying invisible to the model forever; and a spec for a widget that has
     been removed fails too, instead of the model naming something the client
     cannot resolve.

Mechanism 2 is the load-bearing one. Mechanism 1 catches a stale copy, but
only on a machine that has both repos.

ONE TRAP
--------
`labelled_figure` is deliberately ABSENT from the client registry (see
`registry.ts`'s comment): its payload names an offline-authored ASSET rather
than a drawing the model composes, and `BoardWidget` dispatches it as its own
tier BEFORE consulting `lookup()`. Nothing in this repo emits one today, so the
gate below cannot drop one — but it WOULD, because the manifest is the closed
set and `labelled_figure` is not in it. If a labelled-figure path is ever added
server-side it needs its own branch in tutor.py's diagram handling, above this
gate, mirroring the client's dispatch order. It must not be added to
WIDGET_SPECS: that would offer the model an id `lookup()` cannot resolve.

WHAT THIS IS NOT
----------------
This is a COARSE gate. The authoritative validator is each widget's own
`validate()` on the client (e.g. `lib/widgets/field-lines/index.tsx`), which
clamps ranges and rejects on device. Nothing here should grow into a second
copy of those rules: two validators that disagree is worse than one that is
coarse. What this file must guarantee is only that a payload names a widget
the client HAS, at a version the client can RESOLVE — because those two
failures are silent on the client (`lookup()` returns null and the board draws
nothing) and loud here.
"""

import json
import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

MANIFEST_PATH = os.path.join(os.path.dirname(__file__), "registry_manifest.json")

with open(MANIFEST_PATH, "r", encoding="utf-8") as _f:
    MANIFEST: List[Dict[str, Any]] = json.load(_f)

#: id -> the version the client ships. `registry.ts::lookup` is
#: forward-compatible WITHIN a major: a payload may target an older version,
#: never a newer one (`if (version > mod.version) return null`). The same
#: comparison is mirrored below so a too-new version is dropped and logged
#: here rather than silently rendering nothing on the board.
WIDGET_VERSIONS: Dict[str, int] = {w["id"]: int(w["version"]) for w in MANIFEST}

#: id -> animatable param names, straight from the manifest.
WIDGET_ANIMATABLE: Dict[str, List[str]] = {
    w["id"]: list(w.get("animatable") or []) for w in MANIFEST
}


#: What each widget DRAWS and what params it takes, for the turn prompt.
#:
#: Hand-written, and the only hand-written thing here — the generated manifest
#: does not carry it. Kept to one line per widget on purpose: this rides every
#: turn's system prompt (see the token note in `render_manifest_block`). The
#: ranges named are the client validator's own caps, quoted so the model does
#: not have to guess; they are NOT re-enforced server-side, because a second
#: enforcement that drifts from the first is the failure this whole file is
#: written against.
WIDGET_SPECS: Dict[str, str] = {
    "projectile_motion": (
        "flight of a body launched at an angle — exact parabola, range and peak "
        "readout. params: launch_angle_deg, initial_speed_ms, gravity_ms2, "
        'body ("earth"|"moon"|"mars"|"jupiter", label only).'
    ),
    "molecule_3d": (
        "rotatable 3-D molecule fetched by public id. params: structure_ref "
        '("pubchem:<cid>" or "pdb:<id>"), label, representation '
        '("ball_and_stick"|"space_filling"|"wireframe"|"cartoon"), auto_rotate (bool).'
    ),
    "field_lines": (
        "electric field lines and their geometry. params: configuration "
        '("point"|"dipole"|"like_charges"|"parallel_plates"), charge_uc (4-20 — '
        'a "how strong" magnitude; doubling it turn to turn shows the line count '
        'scaling with charge), show_arrows (bool), annotate '
        '(null|"neutral_point"|"termination").'
    ),
    "xy_plot": (
        "a curve y=f(x), the EXACT area under it, the area between two curves, "
        "or a plotted dataset — integrals and areas included, computed, not "
        'sketched. params: mode ("curve"|"area"|"area_between"|"data"), curve and '
        'curve2 ("line"|"parabola"|"sine"|"exponential"|"reciprocal"; '
        "area_between accepts line/parabola only), coefficients a,b,c and "
        "a2,b2,c2, x_min, x_max, shade_from, shade_to, values (data mode), "
        "x_label, y_label."
    ),
    "data_table_trend": (
        "a small table of measured values with the trend down one column called "
        'out. params: cell_kind ("numeric"|"categorical"), row_labels (2-8), '
        "col_labels (max 4 numeric / 3 categorical), values (row-major numbers) "
        "or text_values (row-major strings), trend_col, highlight_row (-1 none), "
        "unit, caption."
    ),
    "process_flow": (
        "an ordered pathway or closed cycle of named steps. params: layout "
        '("ring"|"chain"), nodes (3-8 ring / 3-10 chain labels), closes (bool), '
        "branch_at (-1 none), active_node (-1 none), caption. NOT the same shape "
        "as the server `process_flow` TEMPLATE, which takes `stages`."
    ),
    "reaction_scheme": (
        "a multi-step reaction as a labelled graph. params: species (max 8 "
        "labels), index-aligned step_from, step_to, step_reagent, step_kind "
        '("plain"|"major"|"minor") (max 8 steps), highlight_step (-1 none), '
        "step_progress (0-1), caption."
    ),
    "molecule_struct": (
        "2-D structure of one species — VSEPR geometry, lone pairs, bond angle. "
        'params: mode ("electron_domain"|"coordination"|"interaction"), centre '
        "(element symbol), bond_pairs (2-6), lone_pairs (0-3, plus bond_pairs "
        "<=6), ligands / bond_orders (1|2|3) / bond_styles "
        '("plain"|"wedge"|"dash"|"dative"|"hbond") each of length bond_pairs, '
        "charge (-4..4), bracket (bool), show_lone_pairs, show_angle, label, "
        "highlight_site (-1 none), and OPTIONALLY angle_override "
        "({bond, secondary}) — the MEASURED angles of a named exception; omit "
        "it unless you know the species' real angle differs from the VSEPR "
        "table."
    ),
    "circuit_network": (
        "a circuit network with computed R_eq, C_eq, current and terminal "
        'voltage. params: topology ("series" 1-4 elements|"parallel" 2-3|'
        '"series_parallel" 4|"ladder" 4|"bridge" 5|"two_loop" 6), elements '
        '([{kind: "resistor"|"capacitor"|"inductor"|"cell"|"switch"|'
        '"galvanometer"|"lamp", name (<=3 chars), value (>0)}]), source_v '
        "(0.1-500), internal_r (0-100), bridge_null_cm, show_current (bool), "
        "t_frac (0-1), bridge_delta (-1..1), caption."
    ),
}


def render_manifest_block() -> str:
    """The REGISTRY_MANIFEST block injected into prompts/tutor.md.

    Generated from MANIFEST rather than written out in the markdown, so the
    ids and versions the model is shown cannot drift from the ids and versions
    the sanitizer accepts — they are the same list, read once.

    Cost, measured with cl100k_base against the pre-change prompt: the block is
    1,123 tokens, and it REPLACES the 126-token field_lines paragraph it
    generalises, so the system prompt goes 13,886 -> 14,883 — a net +997, or
    +7.2%. Header 173 tokens, then ~105 per widget, so a tenth widget costs
    about 105 more. It lands in the SYSTEM message, which is the cached prefix
    (tutor.py logs `cache_hit_tokens`), so that is paid in full once per prompt
    version and at the cache rate on every turn after.
    tests/drona/test_widget_registry.py caps it so a future widget cannot
    quietly multiply the per-turn bill.
    """
    lines = [
        "       * **LIVE WIDGETS — a CLOSED set, not templates.** The STUDENT'S "
        "APP draws these itself from your parameters, with exact maths, so a "
        "value read off the picture is computed rather than sketched. Prefer "
        "one over a template whenever its params genuinely describe the "
        "content. Emit a `\"payload\"` instead of `\"template\"`/`\"params\"`: "
        "`{\"seq\": N, \"type\": \"diagram\", \"payload\": {\"widget\": \"<id>\", "
        "\"version\": <as listed>, \"params\": { … }}, \"caption\": \"one short "
        "line\"}`. Never combine `payload` with `template`, `params` or `svg`. "
        "**This list is everything that exists** — an id not on it is "
        "DISCARDED. Never invent one, and never stretch one whose params do "
        "not fit; use a template above or emit no diagram instead.",
    ]
    for entry in MANIFEST:
        wid = entry["id"]
        spec = WIDGET_SPECS.get(wid)
        if spec is None:
            # Unreachable while test_every_manifest_widget_has_a_prompt_spec
            # passes. If it ever is reached, the widget would be named to the
            # model with no params — worse than omitting it — so omit it and
            # say so, rather than emitting a half-described entry.
            logger.warning(
                f"⚠️ [WIDGET REGISTRY] '{wid}' is in the manifest with no "
                f"WIDGET_SPECS entry; omitted from the turn prompt."
            )
            continue
        anim = WIDGET_ANIMATABLE.get(wid) or []
        anim_note = f" animates: {', '.join(anim)}." if anim else ""
        lines.append(f"         - `{wid}` v{entry['version']} — {spec}{anim_note}")
    return "\n".join(lines)


def render_single_widget_block(widget_id: str) -> str:
    """The REGISTRY_MANIFEST replacement for a concept the column NAMES.

    `docs/widget-routing.md` path 1: when `v2_confidence == "high"` the
    archetype column names the widget, and the classification was right 21/21
    against blind adjudication at that confidence. So the model is not asked to
    CHOOSE — offering it nine alternatives invites it to overrule a
    measurement with a guess, and it pays 1,123 tokens for the privilege.

    It IS still asked one thing the column cannot answer: whether THIS SEGMENT
    wants a board at all. The column classifies a CONCEPT; a segment inside
    that concept may be a definition, a recap or a checkpoint, and forcing a
    picture onto it is how a widget ends up beside a sentence that does not
    need one. So the block asks exactly two things — yes/no, and if yes, the
    params.

    Falls back to the full manifest for an id with no spec. That is
    unreachable while test_every_manifest_widget_has_a_prompt_spec passes, and
    the fallback is the full list rather than nothing because a turn with no
    widget list at all is the degradation this block exists to avoid.
    """
    spec = WIDGET_SPECS.get(widget_id)
    version = WIDGET_VERSIONS.get(widget_id)
    if spec is None or version is None:
        logger.warning(
            f"⚠️ [WIDGET REGISTRY] archetype named '{widget_id}', which has no "
            f"spec or no registry entry; falling back to the full manifest."
        )
        return render_manifest_block()
    anim = WIDGET_ANIMATABLE.get(widget_id) or []
    anim_note = f" animates: {', '.join(anim)}." if anim else ""
    return (
        f"       * **THE LIVE WIDGET FOR THIS CONCEPT — it is already chosen.** "
        f"This concept was classified from the book's own text, and at this "
        f"confidence that classification was correct on every row checked. Do "
        f"not pick a different widget and do not go looking for one: "
        f"`{widget_id}` is the only widget available to you this turn.\n"
        f"         - `{widget_id}` v{version} — {spec}{anim_note}\n"
        # WAS "ANSWER TWO QUESTIONS", question 1 being "does this segment want a
        # picture at all? ... that is a correct answer, not a failure". Measured
        # on Ecosystem: the archetype branch fired on 40 segments and the model
        # emitted ZERO diagrams -- and zero TEMPLATES on those turns either,
        # though it named 68 templates on a chapter without this block. The
        # opt-out was the last thing it read about diagrams and it took it every
        # time. It also contradicted the template rule twenty lines above:
        # "Only skip the diagram if no template fits ... do not skip it because
        # the parameters feel approximate." Same bar for both now.
        f"         EMIT IT unless this segment genuinely has nothing to draw — "
        f"the same bar as a template: do not skip because the parameters feel "
        f"approximate. A definition, a recap or a pure checkpoint may want no "
        f"picture; explaining, deriving or working the concept does.\n"
        # v5, and it is a REFERENCE, not a copy. v4 interpolated the segment's
        # objective TEXT into this block. The block lands in the system
        # message, which is the cached prefix, so every segment got its own
        # prefix: uncached input per archetype turn went 1,939 -> 19,822, a
        # 10.2x cache collapse, to carry a string the per-turn user message
        # was already carrying verbatim twenty lines further down. A pointer
        # is one static sentence and caches; the objective costs its own
        # length on every turn forever.
        #
        # The decline is a SOFT ASK, and it is not the mechanism. Implicit
        # decline — no payload at all on an archetype turn — is detected in
        # code (classify_widget_decline) and logged there. v4 shipped this
        # ask alone and it fired zero times in 40 turns, which is why the
        # code path exists. This stays only because when the model DOES
        # volunteer a reason, that sentence is worth more than the inference.
        f"         Judge that against the objective in [CURRENT SEGMENT] "
        f"below, not the concept as a whole. If it wants none, say so: "
        f"`{{\"seq\": N, \"type\": \"widget_decline\", \"reason\": \"<one "
        f"line>\"}}` — it never reaches the board; it records WHY.\n"
        f"         Emit ONE board_event: "
        f"`{{\"seq\": N, \"type\": \"diagram\", \"payload\": {{\"widget\": "
        f"\"{widget_id}\", \"version\": {version}, \"params\": {{ … }}}}, "
        f"\"caption\": \"one short line\"}}`. Never combine `payload` with "
        f"`template`, `params` or `svg`. This is IN ADDITION to your normal "
        f"board lines, never instead of them."
    )


# ── REPETITION ───────────────────────────────────────────────────────────────
# Three segments in a row drawing the same five-step chain is not a widget
# failure; it is the model never being told what it drew last time. These are
# the three pieces that make "what did I already draw" answerable, and each one
# is a fix to a specific way the answer came out wrong.

#: The params that carry the CONTENT a student reads off the picture, in the
#: order they are serialised into the prior-payload summary. Everything else is
#: a knob — a layout flag, a highlight index, a caption.
#:
#: THIS ORDER IS THE FIX. `json.dumps(params, sort_keys=True)` put `nodes`
#: LAST for `process_flow`, because `active_node`, `branch_at`, `caption`,
#: `closes` and `layout` all sort before `n`. The character cap on the summary
#: line then truncated at exactly the word `"nodes"`: the model was shown every
#: knob of the picture it drew last segment and none of what was in it, and
#: went on to draw the same five steps again. Content first, knobs after, and
#: the cap eats the knobs.
CONTENT_FIRST_PARAMS = (
    "nodes",          # process_flow
    "species",        # reaction_scheme
    "row_labels",     # data_table_trend
    "col_labels",     # data_table_trend
    "elements",       # circuit_network
    "ligands",        # molecule_struct
    "centre",         # molecule_struct
    "values",         # data_table_trend / xy_plot
    "text_values",    # data_table_trend
    "curve",          # xy_plot
    "curve2",         # xy_plot
    "structure_ref",  # molecule_3d
    "configuration",  # field_lines
    "topology",       # circuit_network
)

#: Per-payload cap on the summary line. Four of these ride the per-turn USER
#: message, so this is paid uncached on every turn that has priors: 4 x ~180
#: chars is ~200 tokens against v3's 1,939-token uncached baseline.
PRIOR_PAYLOAD_CHARS = 180

#: How many prior payloads the model is shown. FOUR. v4 cut it to three for
#: token headroom and that is precisely what broke the succession case, where
#: seg 3 and seg 7 of the same plan drew the same chain with three unrelated
#: segments between them.
PRIOR_PAYLOAD_WINDOW = 4

#: The board_event type a model uses to decline the named widget out loud.
#: Stripped before the board — nothing in the client registry renders it.
DECLINE_EVENT_TYPE = "widget_decline"


def order_params_content_first(params: Any) -> Dict[str, Any]:
    """`params`, with CONTENT_FIRST_PARAMS hoisted, then everything else sorted.

    Deterministic in both halves: a summary line that reorders itself turn to
    turn is a diff nobody can read.
    """
    if not isinstance(params, dict):
        return {}
    out: Dict[str, Any] = {}
    for key in CONTENT_FIRST_PARAMS:
        if key in params:
            out[key] = params[key]
    for key in sorted(params):
        if key not in out:
            out[key] = params[key]
    return out


def payload_node_list(payload: Any) -> tuple:
    """The list a STUDENT actually sees, as a comparable tuple. `()` if none.

    Two payloads are the same picture when this matches. Comparing SERIALISED
    PARAMS instead reported "byte-identical groups: 0" across three
    consecutive decomposition segments that each drew the same five-step
    chain — the captions differed, so the params were not byte-identical. A
    student does not see the caption key. They see the five steps.

    Lowercased and stripped because "Detritus" and "detritus " are the same
    node to a reader and a different string to `==`.
    """
    if not isinstance(payload, dict):
        return ()
    params = payload.get("params")
    if not isinstance(params, dict):
        return ()
    for key in CONTENT_FIRST_PARAMS:
        val = params.get(key)
        if not isinstance(val, list) or not val:
            continue
        items = []
        for v in val:
            if isinstance(v, dict):
                # circuit_network's `elements` are objects; the NAME is the
                # thing on the picture.
                v = v.get("name") or v.get("label") or json.dumps(
                    v, sort_keys=True, default=str)
            items.append(str(v).strip().lower())
        return tuple(items)
    return ()


def render_prior_payload_line(entry: Dict[str, Any]) -> str:
    """One prior payload, content first, capped."""
    widget = entry.get("widget") or "?"
    body = json.dumps(order_params_content_first(entry.get("params")),
                      ensure_ascii=False, default=str)
    if len(body) > PRIOR_PAYLOAD_CHARS:
        body = body[:PRIOR_PAYLOAD_CHARS] + "…"
    return f"  segment {entry.get('segment_index', '?')} — `{widget}` {body}"


def render_prior_payload_block(entries: List[Dict[str, Any]]) -> str:
    """The per-turn USER-message block. Empty string when there are no priors.

    Deliberately in the user message, not the system prefix: it changes every
    turn, and a per-turn string in the cached prefix is exactly the mistake
    that cost v4 a 10.2x cache collapse.
    """
    if not entries:
        return ""
    lines = ["", "[WIDGETS ALREADY DRAWN IN THIS SESSION — MOST RECENT FIRST]"]
    lines += [render_prior_payload_line(e) for e in entries]
    lines.append(
        "Do not draw one of these again. A picture whose content repeats one "
        "above teaches nothing the student has not already seen: draw the part "
        "THIS segment adds, or emit no diagram."
    )
    return "\n".join(lines) + "\n"


def classify_widget_decline(archetype_widget: Optional[str],
                            board_events: Any) -> Optional[Dict[str, Any]]:
    """Did this archetype turn decline the named widget, and did it say why.

    `None` means it drew one. Otherwise `{"kind": "implicit"|"explicit",
    "reason": str|None}`.

    A turn on the archetype branch that emits NO widget payload IS a decline —
    the model was shown one widget, told to emit it unless the segment has
    nothing to draw, and emitted nothing. That is a judgement, not an absence,
    and it is the only signal for where the archetype column is too coarse for
    a segment. v4 asked for the decline to be stated out loud and it was stated
    ZERO times in 40 turns, so inferring it from the payload's absence is the
    mechanism and the explicit event is the bonus: when the model does
    volunteer a sentence, that sentence beats the inference.

    Called with `archetype_widget=None` on every other branch and returns None
    there: on the manifest branch no widget was named, so nothing was declined.
    """
    if not archetype_widget:
        return None
    events = [e for e in (board_events or []) if isinstance(e, dict)]
    for evt in events:
        payload = evt.get("payload")
        if isinstance(payload, dict) and payload.get("widget"):
            return None
    for evt in events:
        if evt.get("type") == DECLINE_EVENT_TYPE:
            reason = str(evt.get("reason") or "").strip()
            return {"kind": "explicit", "reason": reason or "(no reason given)"}
    return {"kind": "implicit", "reason": None}


def _field_lines_shape_ok(params: Dict[str, Any]) -> bool:
    """The coarse check tutor.py already applied to field_lines, carried over
    VERBATIM so the one widget that was already live keeps behaving identically.

    New widgets deliberately get NO entry in `_COARSE_PARAM_CHECKS`. Writing one
    per widget would rebuild each client validator badly on this side, and the
    first time the two disagreed the server would be the one that was wrong —
    the client's `validate()` is the gate that runs against the actual renderer.
    This table exists to preserve an existing behaviour, not to be extended.
    """
    return (
        params.get("configuration")
        in ("point", "dipole", "like_charges", "parallel_plates")
        and isinstance(params.get("charge_uc"), (int, float))
    )


_COARSE_PARAM_CHECKS = {"field_lines": _field_lines_shape_ok}


#: docs/widget-routing.md, "what each path must record". Path 2 of the hybrid:
#: the model chose from REGISTRY_MANIFEST. Tier 3 is the `svg` branch in
#: tutor.py, so it never reaches this gate at all.
ROUTE_MODEL_CHOICE = "model_choice"

#: Path 1: `v2_confidence == "high"` named this widget and the model filled in
#: its params. Stamped ONLY when the emitted id is the one the column named —
#: a model that was shown `reaction_scheme` and emitted something else did not
#: take path 1, and recording it as though it had would be a provenance field
#: that is populated, plausible, and asserts a decision nobody made. That is
#: the exact failure shape migrations/0035 was written against.
ROUTE_ARCHETYPE_HIGH = "archetype_high"


def sanitize_widget_payload(raw_payload: Any,
                            archetype_widget: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Coarse gate on a model-authored widget payload. None means DROP.

    Returns the BOARD-EVENT FIELDS to merge, not a bare payload:
    `{"payload": {widget, version, params}, "route": "model_choice"}`.

    `archetype_widget` is the id the archetype column NAMED for this concept,
    or None. It decides `route` and nothing else — it never admits or rejects
    a payload, because a model that ignored the named widget still emitted
    something the client may well be able to draw, and dropping it would trade
    a wrong provenance label for a blank board.

    `route` is a sibling of `payload`, deliberately NOT a key inside it.
    `WidgetPayload` in the client's `lib/widgets/types.ts` is a declared shape
    the cofounder owns; adding an undeclared key to it would be a wire-contract
    change made from this side. `BoardEvent` already carries server-owned
    optional metadata beside the payload (`tier`), which is where routing
    provenance belongs.

    The client's own `validate()` for each widget is the real, authoritative
    gate — it clamps and rejects on device — so this deliberately checks only
    the two things the client CANNOT report back:

      * the widget id is in the registry, and
      * the version is one `registry.ts::lookup` will resolve (<= the shipped
        version; older is fine, newer is not).

    Both of those fail SILENTLY on the client: `lookup()` returns null and the
    board simply draws nothing. Every rejection here is logged for that reason,
    the same way the original field_lines branch logged a malformed payload —
    a widget the client cannot render must never be emitted, and must never
    vanish without a trace.

    `params` is checked only for being a non-empty object. Re-implementing
    per-widget ranges here would build a second validator that drifts from the
    first, and a gate widened or narrowed on one side only is worse than a
    coarse one on both.
    """
    if not isinstance(raw_payload, dict):
        return None

    widget = raw_payload.get("widget")
    if not isinstance(widget, str) or widget not in WIDGET_VERSIONS:
        logger.warning(
            f"⚠️ [DIAGRAM DROPPED] widget {widget!r} is not in the client "
            f"registry (have: {', '.join(sorted(WIDGET_VERSIONS))}); "
            f"payload={json.dumps(raw_payload, default=str)[:200]}"
        )
        return None

    shipped = WIDGET_VERSIONS[widget]
    # `or 1` rather than a default: the replaced field_lines branch read
    # `int(raw_payload.get("version") or 1)`, so an absent, null or 0 version
    # meant v1. Kept identical rather than tightened — a version the model
    # omits is not the failure this gate is for.
    raw_version = raw_payload.get("version") or 1
    try:
        version = int(raw_version)
    except (TypeError, ValueError):
        logger.warning(
            f"⚠️ [DIAGRAM DROPPED] {widget} version {raw_version!r} is not an integer."
        )
        return None
    if version < 1 or version > shipped:
        logger.warning(
            f"⚠️ [DIAGRAM DROPPED] {widget} v{version} — the client ships v{shipped} "
            f"and lookup() refuses anything newer, so this would render nothing."
        )
        return None

    params = raw_payload.get("params")
    if not isinstance(params, dict) or not params:
        logger.warning(
            f"⚠️ [DIAGRAM DROPPED] {widget} v{version} params missing or not an "
            f"object: {json.dumps(raw_payload, default=str)[:200]}"
        )
        return None

    coarse = _COARSE_PARAM_CHECKS.get(widget)
    if coarse is not None and not coarse(params):
        logger.warning(
            f"⚠️ [DIAGRAM DROPPED] {widget} payload malformed: "
            f"{json.dumps(raw_payload, default=str)[:200]}"
        )
        return None

    return {
        "payload": {"widget": widget, "version": version, "params": params},
        "route": (ROUTE_ARCHETYPE_HIGH if archetype_widget and widget == archetype_widget
                  else ROUTE_MODEL_CHOICE),
    }

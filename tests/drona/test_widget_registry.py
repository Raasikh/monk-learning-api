"""The server's widget list, the block the model is shown, and the turn-time gate.

Three separable failures live here, and they need different tests:

  1. THE COPY GOES STALE. `app/drona/registry_manifest.json` is a verbatim copy
     of the mobile repo's generated `build/registry-manifest.json`. A version
     bumped on the client with nobody telling this repo is not hypothetical —
     `xy_plot` went 1 -> 2 the same day this was written. Only a comparison
     against the real generated artifact catches that, so the comparison is by
     FULL CONTENT (ids, versions and animatable lists), never by names.

  2. A NEW WIDGET STAYS INVISIBLE. The manifest carries no description and no
     params, so a widget can be present in the list and still be unusable by
     the model. `WIDGET_SPECS` must cover the manifest exactly, in both
     directions, and that check needs no mobile checkout.

  3. THE GATE LETS THROUGH SOMETHING THE CLIENT CANNOT DRAW, or drops something
     without saying so. Both are silent on the client: `registry.ts::lookup`
     returns null for an unknown id or a too-new version and the board simply
     draws nothing.
"""

import json
import logging
import os
import re
from pathlib import Path

import pytest

from app.drona import widget_registry as wr
from app.drona.widget_registry import (
    MANIFEST,
    WIDGET_SPECS,
    WIDGET_VERSIONS,
    render_manifest_block,
    sanitize_widget_payload,
)

API_ROOT = Path(__file__).resolve().parents[2]
SERVER_MANIFEST = API_ROOT / "app" / "drona" / "registry_manifest.json"
PROMPT = (API_ROOT / "prompts" / "tutor.md").read_text()
TUTOR_SRC = (API_ROOT / "app" / "drona" / "tutor.py").read_text()

# Same candidates as scripts/sync_widget_manifest.py.
MOBILE_CANDIDATES = [
    os.environ.get("MONK_MOBILE_REPO", ""),
    str(API_ROOT.parent / "monk-learning-mobile" / "monklearning-mobile"),
    str(API_ROOT.parent / "monklearning-mobile"),
]


def _mobile_checkout() -> Path | None:
    """A mobile checkout on this machine, or None.

    Identified by `lib/widgets/registry.ts` — the source of truth itself — not
    by the generated file, so a checkout whose manifest was never generated is
    FOUND and then FAILED rather than mistaken for "no checkout here".
    """
    for root in MOBILE_CANDIDATES:
        if root and (Path(root) / "lib" / "widgets" / "registry.ts").is_file():
            return Path(root)
    return None


# ── 1. drift ────────────────────────────────────────────────────────────────

def test_server_manifest_matches_the_mobile_registry_export():
    """The whole point of the copy: it must equal what the client generated.

    Compared as parsed JSON content — ids AND versions AND animatable lists.
    A names-only comparison would have passed straight through xy_plot@1 ->
    xy_plot@2, which is the exact event this test exists for: the client's
    `lookup()` still resolves a payload pinned @1 against the v2 module, so
    nothing breaks at runtime and the staleness is invisible until
    `scripts/validate-lesson-plan.mjs` — which matches `id@version` as an exact
    string — reports a live payload as "not in the client registry".

    NOT REACHABLE IS NOT PASSING. With no mobile checkout on this machine this
    SKIPS with an explicit reason. `788 passed, 1 skipped` says "drift
    unverified" out loud; it does not say "verified equal".
    """
    mobile = _mobile_checkout()
    if mobile is None:
        pytest.skip(
            "DRIFT UNVERIFIED: no monklearning-mobile checkout found (tried "
            f"{[c for c in MOBILE_CANDIDATES if c]}). app/drona/registry_manifest.json "
            "was NOT compared against the client's generated export on this run. "
            "Set MONK_MOBILE_REPO to check it."
        )

    generated = mobile / "build" / "registry-manifest.json"
    assert generated.is_file(), (
        f"{mobile} is a mobile checkout but {generated} does not exist. The "
        f"manifest is generated, so this means `npm run export-registry` has "
        f"never been run there — which makes the server's copy unverifiable "
        f"rather than correct. Run it, then re-run this test."
    )

    theirs = json.loads(generated.read_text())
    ours = json.loads(SERVER_MANIFEST.read_text())
    if ours != theirs:
        old = {e["id"]: e["version"] for e in ours}
        new = {e["id"]: e["version"] for e in theirs}
        diff = [
            f"{wid}: server={old.get(wid, '(absent)')} client={new.get(wid, '(absent)')}"
            for wid in sorted(set(old) | set(new))
            if old.get(wid) != new.get(wid)
        ]
        pytest.fail(
            "app/drona/registry_manifest.json has drifted from the client's "
            "generated registry export. Run `python3 scripts/sync_widget_manifest.py`.\n"
            + ("\n".join(diff) if diff else
               "ids and versions agree; the `animatable` lists differ.")
        )


def test_the_copy_is_never_hand_maintained():
    """There is a mechanical way to refresh it, so nobody has an excuse to type one."""
    assert (API_ROOT / "scripts" / "sync_widget_manifest.py").is_file()


def test_the_sanitizer_matches_no_widget_id_by_name():
    """The bug this whole file replaces.

    tutor.py used to gate on `raw_payload.get("widget") == "field_lines"` — a
    widget id typed into Python, so eight of the nine registered widgets were
    unreachable and a ninth could never be added without editing this file.
    The payload branch must now decide from the manifest alone.

    Scoped to the diagram branch on purpose: `_WIDGET_CUES` legitimately names
    `field_lines` (it is a keyword ROUTING table, not a gate), and
    `_DIAGRAM_CUES` names the `process_flow` TEMPLATE, which collides with the
    widget id but is a different thing entirely.
    """
    start = TUTOR_SRC.index('if e_type == "diagram":')
    branch = TUTOR_SRC[start:TUTOR_SRC.index('elif e_type == "formula":', start)]
    assert 'raw_payload.get("widget") ==' not in branch, (
        "the sanitizer compares the widget id against a literal again"
    )
    for wid in WIDGET_VERSIONS:
        assert f'"{wid}"' not in branch, f"'{wid}' is hardcoded in the diagram branch"
    assert "sanitize_widget_payload(" in branch


# ── 2. the model must be told what exists ───────────────────────────────────

def test_every_manifest_widget_has_a_prompt_spec():
    """A widget with no spec is in the registry and invisible to the model."""
    missing = sorted(set(WIDGET_VERSIONS) - set(WIDGET_SPECS))
    assert not missing, (
        f"{missing} are in the manifest with no WIDGET_SPECS entry, so the model "
        f"is never told what they draw or what params they take. Add a one-line "
        f"spec in app/drona/widget_registry.py."
    )


def test_every_prompt_spec_names_a_real_widget():
    """The converse: a spec for a removed widget invites the model to name it."""
    extra = sorted(set(WIDGET_SPECS) - set(WIDGET_VERSIONS))
    assert not extra, (
        f"{extra} have a WIDGET_SPECS entry but are not in the manifest — the "
        f"model would be offered a widget the client cannot resolve."
    )


def test_the_manifest_block_names_every_widget_at_its_manifest_version():
    block = render_manifest_block()
    for wid, version in WIDGET_VERSIONS.items():
        assert f"`{wid}` v{version}" in block, (
            f"{wid} v{version} is not offered to the model at its manifest version"
        )


def test_the_manifest_block_is_generated_not_written_into_the_prompt():
    """prompts/tutor.md must carry the marker and no baked-in widget list.

    A prose copy of the ids in the markdown is the drift this design exists to
    remove: it would still read correctly after a version bump.
    """
    assert "{{REGISTRY_MANIFEST}}" in PROMPT
    assert "render_manifest_block()" in TUTOR_SRC
    assert "{{REGISTRY_MANIFEST}}" in TUTOR_SRC, "the marker is never substituted"


def test_the_manifest_block_stays_cheap():
    """It rides every turn's system prompt, so its size is a per-call bill.

    Measured with cl100k_base: 1,123 tokens for nine widgets — a 173-token
    header plus ~105 each — against a 13,886-token prompt, net +997 after the
    field_lines paragraph it replaces. The chars/4 estimate below reads ~1,050,
    close enough for a CAP and it keeps tiktoken out of the test dependencies.

    A cap, not a target: this fails if a tenth widget multiplies the block
    rather than adding a line to it.
    """
    approx_tokens = len(render_manifest_block()) / 4
    assert approx_tokens < 1500, f"manifest block is ~{approx_tokens:.0f} tokens"


# ── 3. the gate ─────────────────────────────────────────────────────────────

VALID_XY_PLOT = {
    "widget": "xy_plot",
    "version": 2,
    "params": {"mode": "area", "curve": "parabola", "a": 1, "b": 0, "c": 0,
               "x_min": 0, "x_max": 3, "shade_from": 0, "shade_to": 2,
               "x_label": "x", "y_label": "y"},
}


def test_a_valid_non_field_lines_payload_is_accepted():
    """The gap this work closes: nine widgets on the client, one on the server."""
    out = sanitize_widget_payload(VALID_XY_PLOT)
    assert out is not None, "xy_plot is in the registry and must be emittable"
    assert out["payload"] == VALID_XY_PLOT
    assert out["route"] == "model_choice", (
        "docs/widget-routing.md requires the routing path to be recorded"
    )


def test_the_route_is_a_sibling_of_the_payload_not_a_key_inside_it():
    """`WidgetPayload` in lib/widgets/types.ts is the client's declared shape.

    Adding `route` inside it would be a wire-contract change made from this
    side; it belongs beside the payload, where BoardEvent already carries
    server-owned metadata.
    """
    out = sanitize_widget_payload(VALID_XY_PLOT)
    assert set(out["payload"]) == {"widget", "version", "params"}


@pytest.mark.parametrize("wid", sorted(WIDGET_VERSIONS))
def test_every_registered_widget_can_reach_the_board(wid):
    """No widget may be registered, described, and still unemittable."""
    params = ({"configuration": "point", "charge_uc": 8}
              if wid == "field_lines" else {"any": "shape"})
    out = sanitize_widget_payload(
        {"widget": wid, "version": WIDGET_VERSIONS[wid], "params": params}
    )
    assert out is not None and out["payload"]["widget"] == wid


def test_an_unknown_widget_is_dropped_and_logged(caplog):
    """Silence is the failure. The client's lookup() returns null and draws
    nothing, so if the server drops quietly nobody ever learns the model named
    a widget that does not exist."""
    with caplog.at_level(logging.WARNING, logger=wr.__name__):
        out = sanitize_widget_payload(
            {"widget": "phase_diagram", "version": 1, "params": {"x": 1}}
        )
    assert out is None
    assert "phase_diagram" in caplog.text
    assert "DIAGRAM DROPPED" in caplog.text


def test_a_version_the_client_cannot_resolve_is_dropped_and_logged(caplog):
    """`lookup()` refuses `version > mod.version`. A payload one ahead of the
    client renders nothing, and nothing is reported — so it is refused here."""
    too_new = WIDGET_VERSIONS["xy_plot"] + 1
    with caplog.at_level(logging.WARNING, logger=wr.__name__):
        out = sanitize_widget_payload(
            {"widget": "xy_plot", "version": too_new, "params": {"mode": "area"}}
        )
    assert out is None
    assert f"v{too_new}" in caplog.text and "DIAGRAM DROPPED" in caplog.text


def test_an_older_version_is_still_accepted():
    """lookup() is forward-compatible within a major: older is fine, newer is not.

    This is why the version must come from the manifest rather than a literal —
    a payload pinned xy_plot@1 renders, so the staleness would be invisible.
    """
    assert WIDGET_VERSIONS["xy_plot"] > 1, "xy_plot@2 is what makes this case real"
    out = sanitize_widget_payload({"widget": "xy_plot", "version": 1,
                                   "params": {"mode": "curve"}})
    assert out is not None and out["payload"]["version"] == 1


def test_params_must_be_a_non_empty_object(caplog):
    with caplog.at_level(logging.WARNING, logger=wr.__name__):
        assert sanitize_widget_payload({"widget": "xy_plot", "version": 2}) is None
        assert sanitize_widget_payload(
            {"widget": "xy_plot", "version": 2, "params": {}}) is None
    assert "DIAGRAM DROPPED" in caplog.text


# ── field_lines, unchanged ──────────────────────────────────────────────────

FIELD_LINES_OK = {
    "widget": "field_lines",
    "version": 1,
    "params": {"configuration": "dipole", "charge_uc": 8,
               "show_arrows": True, "annotate": None},
}


def test_field_lines_still_passes_unchanged():
    out = sanitize_widget_payload(FIELD_LINES_OK)
    assert out["payload"] == FIELD_LINES_OK


@pytest.mark.parametrize("params", [
    {"configuration": "quadrupole", "charge_uc": 8},   # not one of the four
    {"configuration": "point", "charge_uc": "strong"},  # not a number
    {"charge_uc": 8},                                   # no configuration
])
def test_field_lines_keeps_its_own_coarse_shape_check(params, caplog):
    """The check tutor.py already applied, carried over verbatim.

    Generalising the branch must not LOOSEN the one widget that was already
    live — a payload the old code refused must still be refused.
    """
    with caplog.at_level(logging.WARNING, logger=wr.__name__):
        out = sanitize_widget_payload(
            {"widget": "field_lines", "version": 1, "params": params})
    assert out is None
    assert "field_lines payload malformed" in caplog.text


def test_an_absent_or_zero_version_still_means_v1():
    """`int(raw_payload.get("version") or 1)` was the original behaviour.

    Kept rather than tightened: a version the model omitted is not the failure
    this gate is for, and refusing it would be a new drop the old code did not
    make.
    """
    absent = {k: v for k, v in FIELD_LINES_OK.items() if k != "version"}
    for payload in (absent, {**absent, "version": None}, {**absent, "version": 0}):
        out = sanitize_widget_payload(payload)
        assert out is not None, payload
        assert out["payload"]["version"] == 1


def test_new_widgets_deliberately_get_no_server_side_param_check():
    """The coarse table preserves field_lines; it is not a place to add rules.

    A second validator per widget on this side would drift from the client's
    `validate()`, and the client's is the one that runs against the renderer.
    """
    assert set(wr._COARSE_PARAM_CHECKS) == {"field_lines"}


# ── 4. precedence: the template cue is a default, not a decision ────────────
#
# `_WIDGET_CUES` was consulted ONLY when `suggest_diagram_template` found
# nothing, so a template cue silently hid the whole widget registry. Measured
# on Maths 12 Ch8 (real functions, bare concept names): 6 of 10 concepts were
# claimed by a template and never reached widget routing at all — including
# "Area Bounded by a Parabola and a Line", the canonical xy_plot case, routed
# to `conic_figure` on the literal word "parabola".
#
# The fix is NOT to invert the order. `projectile_scene` beating
# `vector_resolution` is a measured lesson recorded in _DIAGRAM_CUES' own
# comments, and template-vs-template order is deliberately untouched here.
# What changed is that a keyword no longer DECIDES: below `v2_confidence ==
# "high"` the template cue is a DEFAULT, the full manifest is in the system
# prompt, and the model picks — which is what docs/widget-routing.md mandates.
#
# `_WIDGET_CUES` itself is now DELETED, and the archetype column names the
# widget on the high-confidence path instead. Its own tests live in
# tests/drona/test_concept_archetypes.py; what stays here is everything about
# the template side and the directive shapes.

MATHS_12_CH8 = [
    "Area Under a Simple Curve Bounded by the Axes",
    "Area by Integration Along the y-axis",
    "Area Bounded by a Parabola and a Line",
    "Area Between Two Intersecting Curves",
    "Area of Regions Bounded by Circles and Ellipses",
    "Area Bounded by a Curve and Its Tangent or Normal",
    "Area Between a Function and Its Inverse",
    "Area of Regions Involving Modulus and Piecewise-Defined Functions",
    "Areas Involving Greatest Integer and Fractional Part Functions",
    "Area of Regions Described by Inequalities",
]


def test_the_widget_path_is_no_longer_suppressed_by_the_template_cue():
    """The template cue must not be able to hide the registry.

    It used to in two ways: `_WIDGET_CUES` was consulted only when no template
    cue fired, and the template directive named one template and said nothing
    about widgets. The first is gone with the table; the second is asserted
    below.
    """
    assert "None if _diag_hint else" not in TUTOR_SRC, (
        "the template cue is deciding again; it must be a default, not a gate"
    )
    # The full manifest reaches every non-archetype turn regardless of cue.
    assert "else render_manifest_block()" in TUTOR_SRC


def test_the_template_directive_says_a_widget_may_be_used_instead():
    """Without this, the manifest is in the prompt and unreachable in practice.

    The measured lesson in this codebase is that a general rule loses to the
    per-turn directive next to it — diagrams went 2/4 -> 4/4 only once the
    directive named the template. A directive that names ONE template and says
    nothing else is therefore an instruction to ignore the registry.
    """
    start = TUTOR_SRC.index("diagram_directive = (")
    block = TUTOR_SRC[start:start + 2200]
    assert "LIVE WIDGETS" in block, "the template directive never mentions the registry"
    assert "is the DEFAULT, not the only option" in block


def test_the_directives_are_mutually_exclusive_branches():
    """Two 'emit ONE diagram' directives in one turn is worse than a bad pick.

    THREE branches now, and the chain IS the tier order: a segment whose
    payload was already precomputed asks for no picture at all; a concept the
    column NAMES gets the widget directive; everything else gets the template
    directive if a cue fired, and the manifest either way.
    """
    assert re.search(r'\n    if _board_slot == "widget_precomputed":\n', TUTOR_SRC)
    assert re.search(r"\n    elif _archetype_widget:\n", TUTOR_SRC)
    assert re.search(r"\n    elif _diag_hint:\n", TUTOR_SRC)
    # and none is gated on the cached SVG any more — that was the
    # timing-over-tier bug.
    assert "and not _precomputed_svg:" not in TUTOR_SRC


def test_slot_one_precedes_slot_two_in_the_directive_chain():
    """The resolver having the right order is not enough: whichever branch runs
    FIRST is the one that decides what the model is asked for. Slot 1 outranks
    slot 2, so its branch must come first — and it must ask for NO diagram,
    because the picture already exists and the board carries one per turn."""
    pre = TUTOR_SRC.index('if _board_slot == "widget_precomputed":')
    arch = TUTOR_SRC.index("elif _archetype_widget:")
    tmpl = TUTOR_SRC.index("elif _diag_hint:")
    assert pre < arch < tmpl
    block = TUTOR_SRC[pre:arch]
    assert "ALREADY DRAWN" in block
    assert "Emit NO board_event" in block


def test_the_widget_directive_takes_its_params_from_the_registry():
    """It used to spell out field_lines' four configurations inline.

    A second widget would then have been handed field_lines' params — the same
    hardcoding, one level up from the sanitizer. The archetype column now
    names widgets the registry has never described in a literal here.

    Scoped to the SLOT 2 branch: slot 1's directive names no params at all (its
    payload is already authored), so starting at the first `widget_directive =`
    would read the wrong block.
    """
    start = TUTOR_SRC.index("elif _archetype_widget:")
    block = TUTOR_SRC[start:start + 3000]
    assert "WIDGET_SPECS.get(_archetype_widget" in block
    assert "WIDGET_VERSIONS.get(_archetype_widget" in TUTOR_SRC
    assert "like_charges" not in block, "field_lines params are hardcoded again"


def test_tier_three_kickoff_still_precedes_the_llm_call():
    """The guard changed with the resolution order; the POSITION must not have.

    Tier 3 is started before the LLM call and cannot be started after — a turn
    emits exactly ONE board_events event. The guard is now the resolved slot,
    which is "slots 1-4 all empty" by construction, so a segment that falls
    through to slot 5 still gets a figure started rather than nothing.
    """
    idx = TUTOR_SRC.index("_live_diagram_future = None")
    block = TUTOR_SRC[idx:idx + 260]
    assert '_board_slot == "svg_live"' in block
    assert TUTOR_SRC.index("start_live_diagram(\n") < TUTOR_SRC.index("diagram_directive = (")


def test_every_maths_12_ch8_concept_now_reaches_the_widget_registry():
    """The measurement that motivated the precedence change, pinned.

    Before: 6 of 10 were claimed by a template cue, which suppressed
    suggest_widget AND left the model with no widget list at all — the manifest
    did not exist server-side. Now the manifest is in the system prompt on
    every turn, so all ten see it; the six with a template cue see that
    template as a default they may override.
    """
    from app.drona.tutor import suggest_diagram_template

    claimed = [c for c in MATHS_12_CH8 if suggest_diagram_template(c)]
    assert len(claimed) == 6, (
        f"the _DIAGRAM_CUES table changed shape: {len(claimed)} of 10 claimed. "
        f"Re-measure before assuming the precedence reasoning still holds."
    )
    # Not "the widget wins" — that is the model's call, per docs/widget-routing.md.
    # What is asserted is that the list is never hidden from it.
    block = render_manifest_block()
    assert "`xy_plot` v" in block and "area between two curves" in block
    assert "{{REGISTRY_MANIFEST}}" in PROMPT, (
        "the manifest reaches every turn regardless of which cue fired"
    )


# ── 4. v5: repetition and the implicit decline ───────────────────────────────
# Four mechanical fixes, each written against a specific way the previous
# attempt got the answer wrong. Each one gets the test that would have caught
# it, because "the model repeated itself" is not a failure any assertion about
# widget ids can see.

def test_the_node_list_is_serialised_before_the_knobs():
    """`sort_keys=True` put `nodes` LAST, and the cap ate the content.

    Reproduced literally: for `process_flow`, `active_node`, `branch_at`,
    `caption`, `closes` and `layout` all sort before `n`. At a 180-char cap the
    sorted line stops inside the word `"nodes"` — the model is shown every knob
    of the picture it drew last segment and none of what was in it.
    """
    params = {
        "active_node": -1, "branch_at": -1,
        "caption": "Energy flow through the ecosystem",
        "closes": False, "layout": "chain",
        "nodes": ["Sun", "Producers", "Primary consumers",
                  "Secondary consumers", "Decomposers"],
    }
    sorted_line = json.dumps(params, sort_keys=True)[:wr.PRIOR_PAYLOAD_CHARS]
    assert "Decomposers" not in sorted_line, (
        "the sorted serialisation now fits; re-derive the cap before trusting this"
    )

    line = wr.render_prior_payload_line(
        {"segment_index": 3, "widget": "process_flow", "params": params})
    assert list(wr.order_params_content_first(params))[0] == "nodes"
    for node in params["nodes"]:
        assert node in line, f"{node!r} was truncated out of the summary line"


def test_two_payloads_that_draw_the_same_picture_compare_equal():
    """v4 reported "byte-identical groups: 0" while three consecutive
    decomposition segments drew the same five-step chain. The CAPTIONS
    differed, so the params were not byte-identical. A student sees nodes."""
    nodes = ["Detritus", "Fragmentation", "Leaching", "Catabolism", "Humus"]
    a = {"widget": "process_flow",
         "params": {"nodes": list(nodes), "layout": "chain",
                    "caption": "Steps in decomposition"}}
    b = {"widget": "process_flow",
         "params": {"nodes": list(nodes), "layout": "chain",
                    "caption": "How detritus breaks down", "active_node": 2}}
    assert json.dumps(a["params"], sort_keys=True) != json.dumps(b["params"], sort_keys=True)
    assert wr.payload_node_list(a) == wr.payload_node_list(b) != ()


def test_the_node_list_reads_names_out_of_object_params():
    """circuit_network's `elements` are objects; the NAME is what is drawn."""
    got = wr.payload_node_list({"params": {
        "topology": "series",
        "elements": [{"kind": "resistor", "name": "R1", "value": 4},
                     {"kind": "cell", "name": "E", "value": 6}],
    }})
    assert got == ("r1", "e")


def test_a_payload_with_no_list_param_has_no_node_list():
    """`()` rather than a guess. projectile_motion draws no list of anything,
    so two projectile payloads must never compare equal on node list alone."""
    assert wr.payload_node_list({"params": {"launch_angle_deg": 45,
                                            "initial_speed_ms": 20}}) == ()


def test_the_prior_payload_window_is_four():
    """v4 cut it to three for token headroom and that broke the succession
    case: seg 3 and seg 7 of one plan drew the same chain with three unrelated
    segments between them, and a window of three could not see it."""
    assert wr.PRIOR_PAYLOAD_WINDOW == 4
    assert "PRIOR_PAYLOAD_WINDOW" in TUTOR_SRC


def test_the_prior_payload_query_is_ordered():
    """PostgREST returns rows in NO guaranteed order without `.order()`, so
    "the four most recent payloads" was whatever the planner handed back."""
    assert re.search(
        r'table\("drona_turns"\)[\s\S]{0,400}?\.order\("turn_index",\s*desc=True\)',
        TUTOR_SRC,
    ), "the prior-payload query lost its .order()"


def test_the_prior_payload_block_rides_the_user_message_not_the_prefix():
    """The one thing that cost v4 a 10.2x cache collapse: a per-turn string in
    the SYSTEM message, which is the cached prefix."""
    assert "{prior_payload_block}" in TUTOR_SRC
    sys_line = re.search(r"system_content = f\".*?\"", TUTOR_SRC, re.S)
    assert sys_line and "prior_payload_block" not in sys_line.group(0)
    assert wr.render_prior_payload_block([]) == "", (
        "a session with no prior payloads must add nothing to the turn"
    )


def test_the_single_widget_block_references_the_segment_and_never_carries_it():
    """v4 interpolated the objective TEXT into the cached prefix. The block
    must POINT at [CURRENT SEGMENT], which the user message already carries."""
    block = wr.render_single_widget_block("process_flow")
    assert "[CURRENT SEGMENT]" in block
    # It takes no segment argument, so it CANNOT embed one.
    import inspect
    assert list(inspect.signature(wr.render_single_widget_block).parameters) == ["widget_id"]


def test_an_archetype_turn_with_no_payload_is_a_decline():
    """The whole of change 2. v4 asked for the decline out loud and got zero
    in 40 turns while six turns silently drew nothing."""
    assert wr.classify_widget_decline("process_flow", [
        {"seq": 1, "type": "heading", "text": "Secondary Productivity"},
    ]) == {"kind": "implicit", "reason": None}


def test_a_volunteered_reason_beats_the_inference():
    got = wr.classify_widget_decline("process_flow", [
        {"seq": 1, "type": "widget_decline", "reason": "this segment only defines a term"},
    ])
    assert got == {"kind": "explicit", "reason": "this segment only defines a term"}
    bare = wr.classify_widget_decline("process_flow", [{"type": "widget_decline"}])
    assert bare == {"kind": "explicit", "reason": "(no reason given)"}


def test_a_turn_that_drew_the_widget_is_not_a_decline():
    assert wr.classify_widget_decline("process_flow", [
        {"seq": 1, "type": "diagram",
         "payload": {"widget": "process_flow", "version": 1, "params": {"nodes": ["a"]}}},
    ]) is None


def test_nothing_is_declined_on_the_manifest_branch():
    """No widget was NAMED there, so an absent payload is a choice from nine,
    not a refusal of one. Folding the two together would drown the signal."""
    assert wr.classify_widget_decline(None, []) is None
    assert wr.classify_widget_decline("", [{"type": "text", "text": "x"}]) is None


def test_the_decline_log_carries_the_concept_and_the_objective():
    """The log IS the deliverable — it is the only signal for where the
    archetype column is too coarse. A count without these is unactionable."""
    block = re.search(r"\[WIDGET DECLINE\][\s\S]{0,900}?\n\s*\)", TUTOR_SRC)
    assert block, "the decline log is gone"
    src = block.group(0)
    for field in ("subtopic_key", "objective", "reason", "_decline['kind']"):
        assert field in src, f"the decline log no longer reports {field}"

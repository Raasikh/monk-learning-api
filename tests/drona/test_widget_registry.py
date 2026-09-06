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
# on Maths 12 Ch8 (`suggest_diagram_template` / `suggest_widget`, real
# functions, bare concept names): 6 of 10 concepts were claimed by a template
# and never reached widget routing at all — including "Area Bounded by a
# Parabola and a Line", the canonical xy_plot case, routed to `conic_figure`
# on the literal word "parabola".
#
# The fix is NOT to invert the order. `projectile_scene` beating
# `vector_resolution` is a measured lesson recorded in _DIAGRAM_CUES' own
# comments, and template-vs-template order is deliberately untouched here.
# What changed is that a keyword no longer DECIDES: both hints are computed,
# both are shown, and the model picks — which is what docs/widget-routing.md
# already mandates for everything below `v2_confidence == "high"`.

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


def test_the_widget_cue_is_no_longer_suppressed_by_the_template_cue():
    """`_widget_hint = None if _diag_hint else …` was the suppression."""
    assert "None if _diag_hint else suggest_widget" not in TUTOR_SRC, (
        "the template cue is deciding again; it must be a default, not a gate"
    )
    assert re.search(r"_widget_hint = suggest_widget\(", TUTOR_SRC)


def test_the_template_directive_says_a_widget_may_be_used_instead():
    """Without this, the manifest is in the prompt and unreachable in practice.

    The measured lesson in this codebase is that a general rule loses to the
    per-turn directive next to it — diagrams went 2/4 -> 4/4 only once the
    directive named the template. A directive that names ONE template and says
    nothing else is therefore an instruction to ignore the registry.
    """
    start = TUTOR_SRC.index("diagram_directive = (")
    block = TUTOR_SRC[start:TUTOR_SRC.index("widget_directive = ", start)]
    assert "LIVE WIDGETS" in block, "the template directive never mentions the registry"
    assert "{_widget_hint}" in block, (
        "a widget cue that also fired is not surfaced, so it fires into nothing"
    )


def test_the_standalone_widget_directive_still_only_fires_without_a_template():
    """Two 'emit ONE diagram' directives in one turn is worse than a bad pick.

    When both cues fire the alternative rides inside diagram_directive instead,
    which is also what keeps every field_lines turn behaving exactly as before.
    """
    assert re.search(
        r"if _widget_hint and not _diag_hint and not _precomputed_svg:", TUTOR_SRC
    )


def test_the_widget_directive_takes_its_params_from_the_registry():
    """It used to spell out field_lines' four configurations inline.

    A second row in `_WIDGET_CUES` would then have been handed field_lines'
    params — the same hardcoding, one level up from the sanitizer.
    """
    start = TUTOR_SRC.index("widget_directive = (")
    block = TUTOR_SRC[start:start + 1400]
    assert "WIDGET_SPECS.get(_widget_hint" in block
    assert "WIDGET_VERSIONS.get(_widget_hint" in TUTOR_SRC
    assert "like_charges" not in block, "field_lines params are hardcoded again"


def test_tier_three_kickoff_is_unchanged_by_the_precedence_change():
    """Un-suppressing _widget_hint must not change WHEN tier 3 starts.

    Tier 3 starts only when neither hint fired; a widget hint could previously
    only be non-None where `_diag_hint` was already None, so the guard's value
    is identical either way. It is asserted rather than argued because tier 3
    is started before the LLM call and cannot be started after — losing it
    would mean turns with no fallback at all.
    """
    idx = TUTOR_SRC.index("_live_diagram_future = None")
    block = TUTOR_SRC[idx:idx + 260]
    assert "not _precomputed_svg and not _diag_hint and not _widget_hint" in block


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

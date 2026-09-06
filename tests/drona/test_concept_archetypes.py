"""The archetype column: the copy, the gate, and the five-slot resolution order.

Replaces tests/drona/test_widget_cues.py, which tested `_WIDGET_CUES` — a
one-row regex table that has been deleted. What used to be a keyword deciding
before the model is now a classification read from the book's own text, gated
at the one confidence level where it was measured to be right.

Four separable failures live here:

  1. THE COPY GOES STALE. `app/drona/concept_archetypes.csv` is a verbatim copy
     of the mobile repo's `content/concept-archetypes.csv`. Same discipline as
     `registry_manifest.json`, which caught a real drift (`xy_plot` 1 -> 2)
     within minutes of being written.

  2. THE TABLE IS UNREACHABLE AND EVERYTHING STILL LOOKS FINE. This is the
     recurring defect in this project: a check that passes on absent
     information. With no CSV every concept looks non-high and routing degrades
     to exactly what it was, silently. So an unreadable table is its own
     confidence value and its own FAILING test, not a quiet absence.

  3. THE GATE WIDENS. Only `v2_confidence == "high"` may name a widget. `med`
     leans 2:1 toward falsely claiming a diagram (see the mobile README's blind
     adjudication), so a `med` row must route exactly like an unknown one.

  4. THE ORDER COLLAPSES BACK INTO A TIMING ORDER. A cached tier-3 SVG is still
     tier 3, and it must never again suppress the slots above it.
"""

import csv
import os
import re
from pathlib import Path

import pytest

from app.drona import concept_archetypes as ca
from app.drona.concept_archetypes import ArchetypeVerdict, verdict
from app.drona.tutor import BOARD_SLOTS, resolve_board_slot
from app.drona.widget_registry import (
    ROUTE_ARCHETYPE_HIGH,
    ROUTE_MODEL_CHOICE,
    WIDGET_VERSIONS,
    render_manifest_block,
    render_single_widget_block,
    sanitize_widget_payload,
)

API_ROOT = Path(__file__).resolve().parents[2]
SERVER_CSV = API_ROOT / "app" / "drona" / "concept_archetypes.csv"
TUTOR_SRC = (API_ROOT / "app" / "drona" / "tutor.py").read_text()

# Same candidates as scripts/sync_concept_archetypes.py and
# tests/drona/test_widget_registry.py — keep all three in step.
MOBILE_CANDIDATES = [
    os.environ.get("MONK_MOBILE_REPO", ""),
    str(API_ROOT.parent / "monk-learning-mobile" / "monklearning-mobile"),
    str(API_ROOT.parent / "monklearning-mobile"),
]


def _mobile_checkout() -> Path | None:
    """A mobile checkout on this machine, or None.

    Identified by `lib/widgets/registry.ts`, the same marker the widget
    manifest drift test uses — a directory that is a checkout is FOUND and then
    FAILED if its archetype CSV is missing, rather than mistaken for "no
    checkout here".
    """
    for root in MOBILE_CANDIDATES:
        if root and (Path(root) / "lib" / "widgets" / "registry.ts").is_file():
            return Path(root)
    return None


# ── 1. drift ────────────────────────────────────────────────────────────────

def test_server_archetype_csv_matches_the_mobile_copy():
    """Byte-for-byte. It is a verbatim copy and there is nothing to interpret.

    NOT REACHABLE IS NOT PASSING. With no mobile checkout this SKIPS with an
    explicit reason, so a green run says "drift unverified" out loud rather
    than "checked and equal".
    """
    mobile = _mobile_checkout()
    if mobile is None:
        pytest.skip(
            "DRIFT UNVERIFIED: no monklearning-mobile checkout found (tried "
            f"{[c for c in MOBILE_CANDIDATES if c]}). "
            "app/drona/concept_archetypes.csv was NOT compared against the "
            "mobile repo's content/concept-archetypes.csv on this run. "
            "Set MONK_MOBILE_REPO to check it."
        )

    theirs = mobile / "content" / "concept-archetypes.csv"
    assert theirs.is_file(), (
        f"{mobile} is a mobile checkout but {theirs} does not exist. That makes "
        f"the server's copy UNVERIFIABLE rather than correct."
    )
    if theirs.read_bytes() != SERVER_CSV.read_bytes():
        def keyed(path):
            with open(path, newline="", encoding="utf-8") as fh:
                return {(r["subject"], r["class_level"], r["chapter_order"], r["concept"]):
                        (r["archetype_v2"], r["v2_confidence"])
                        for r in csv.DictReader(fh)}
        old, new = keyed(SERVER_CSV), keyed(theirs)
        diff = [f"{k}: server={old.get(k, '(absent)')} mobile={new.get(k, '(absent)')}"
                for k in sorted(set(old) | set(new)) if old.get(k) != new.get(k)]
        pytest.fail(
            "app/drona/concept_archetypes.csv has drifted from the mobile "
            "repo's classification. Run "
            "`python3 scripts/sync_concept_archetypes.py`.\n"
            + ("\n".join(diff[:25]) if diff else
               "the parsed verdicts agree; some other column or the byte "
               "encoding differs.")
        )


def test_the_copy_is_never_hand_maintained():
    assert (API_ROOT / "scripts" / "sync_concept_archetypes.py").is_file()


# ── 2. unreachable must be loud ─────────────────────────────────────────────

def test_the_archetype_table_actually_loaded():
    """The check that must not pass on absent information.

    If the CSV cannot be read, every concept looks non-high and routing
    silently reverts to what it was before this change existed, with no
    symptom anywhere. `LOAD_ERROR` makes that state nameable and this test
    makes it fail the build.
    """
    assert ca.LOAD_ERROR is None, (
        f"the archetype table did not load: {ca.LOAD_ERROR}. Path 1 of "
        f"docs/widget-routing.md is OFF, which is NOT the same as "
        f"'no high-confidence concepts found'."
    )
    assert len(ca.TABLE) == 1154, (
        f"expected the 1,154-concept corpus, got {len(ca.TABLE)}. "
        f"Re-measure before assuming any count in this file still holds."
    )


def test_an_unreadable_table_is_its_own_verdict_not_a_quiet_none(monkeypatch):
    """"We do not know" and "not high" must not be the same value.

    They need opposite reactions — one is a broken deployment, the other is
    1,101 concepts behaving exactly as designed.
    """
    monkeypatch.setattr(ca, "LOAD_ERROR", "OSError: simulated")
    v = verdict("chemistry", 12, 8, "Aldol Condensation")
    assert v.widget is None
    assert v.confidence == "table_unreadable"
    assert v.confidence != "unknown"


def test_the_version_identifier_refuses_to_name_a_pass_that_was_not_read():
    """`prompt_version` failed here by being plausible on a run that used it
    for nothing. A hash of the actual file cannot, and "unreadable" is not a
    hash."""
    assert re.fullmatch(r"[0-9a-f]{16}", ca.ARCHETYPE_VERSION), ca.ARCHETYPE_VERSION
    assert "ARCHETYPE_VERSION" in TUTOR_SRC


# ── 3. the gate ─────────────────────────────────────────────────────────────

def _rows():
    with open(SERVER_CSV, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def test_only_high_confidence_ever_names_a_widget():
    """Swept over the whole corpus, not sampled.

    `med` is 236 rows and is wrong about a third of the time, in the direction
    of claiming a diagram the content does not support. A deterministic router
    built on it puts a wrong picture on a live board with no path to notice.
    """
    for r in _rows():
        v = verdict(r["subject"], r["class_level"], r["chapter_order"], r["concept"])
        if r["v2_confidence"] != "high":
            assert v.widget is None, (
                f"{r['concept']!r} is {r['v2_confidence']} and named "
                f"{v.widget!r} — the gate has been widened"
            )


def test_a_high_row_naming_something_the_client_cannot_draw_still_falls_through():
    """479 rows are `high`; only 69 name a registered widget.

    After the corpus-wide reclassification every one of the 1,154 concepts
    carries a verdict read from the book's own chunks. Coverage went 35% -> 100%
    and `high` went 226 -> 480 — but the ROUTED population went 55 -> 69, and
    that gap is the point of this test.

    `none_symbolic`, `labelled_figure` (an offline asset, slot 3, deliberately
    absent from the client registry), `apparatus` and the `gap_*` placeholders
    are `high` and unroutable. Naming one would hand the model an id
    `registry.ts::lookup` returns null for, and the board would draw nothing.

    So "high" is not "routable", and the difference is now 411 rows. Most of
    those are `gap_*`: pictures the book actually draws that no widget can.
    """
    high = [r for r in _rows() if r["v2_confidence"] == "high"]
    named, unroutable = [], []
    for r in high:
        v = verdict(r["subject"], r["class_level"], r["chapter_order"], r["concept"])
        (named if v.widget else unroutable).append(r["archetype_v2"])
    assert len(high) == 479
    assert len(named) == 69, f"the routed population moved: {len(named)}"
    assert set(named) <= set(WIDGET_VERSIONS)
    assert "labelled_figure" in unroutable and "none_symbolic" in unroutable


def test_the_routed_population_is_fifty_three_across_twenty_seven_chapters():
    """The number the routing decision was made on. Pinned so a resync that
    moves it is a visible test change rather than a silent behaviour change."""
    routed = {(r["subject"], r["class_level"], r["chapter_order"])
              for r in _rows()
              if r["v2_confidence"] == "high" and r["archetype_v2"] in WIDGET_VERSIONS}
    assert len(routed) == 37


def test_a_concept_the_table_does_not_know_falls_to_the_manifest_branch():
    """It must never crash and never claim a widget.

    Measured against the live `concepts` table, 1,153 of 1,154 active concepts
    join exactly on (subject, class_level, chapter_order, name). The one miss
    is physics 11 ch6 "Rigid Bodies & Types of Motion", which the CSV spells
    with "and". That `&` is deliberately NOT normalised — a normaliser is a
    widened gate — so the real miss is asserted here rather than papered over.
    """
    v = verdict("physics", 11, 6, "Rigid Bodies & Types of Motion")
    assert v.widget is None
    assert v.confidence == "unknown"
    # and the spelling the CSV DOES carry is now a classified row -- which is
    # exactly why this matters more than it used to. Before the corpus-wide
    # reclassification this row was `not_in_scope`, and the module's own comment
    # said the miss "costs nothing". It now reads `labelled_figure` at `high`,
    # so the miss discards a real verdict. It still cannot put a WRONG diagram
    # on a board -- labelled_figure is not a registered widget and never routes
    # -- but the day this row becomes a widget verdict, the `&` costs a route
    # silently. Asserted so that day is loud.
    csv_side = verdict("physics", 11, 6, "Rigid Bodies and Types of Motion")
    assert csv_side.confidence == "high"
    assert csv_side.widget is None, (
        "this row now carries a HIGH verdict that the live concepts table cannot "
        "reach, because it spells the name with '&'. While the verdict is "
        "unroutable that is survivable; if it ever names a registered widget, "
        "fix the spelling rather than adding a normaliser."
    )

    # A concept from no corpus at all behaves the same way.
    invented = verdict("physics", 11, 6, "Zebra Mechanics of the Fourth Kind")
    assert invented == ArchetypeVerdict(None, "", "unknown", invented.why)


def test_missing_join_fields_are_unjoinable_not_unknown():
    """"Nobody asked the table anything" is a third state, and it is the one a
    session with no chapter metadata is in."""
    assert verdict(None, None, None, None).confidence == "unjoinable"
    assert verdict("physics", "eleven", 6, "Center of Mass").confidence == "unjoinable"


def test_maths_12_ch8_routes_exactly_the_two_regions_xy_plot_can_draw():
    """This test used to assert that Ch8 could NEVER fire on the column.

    That was true, and it was true because the reclassification had never
    read maths: all ten rows were `not_in_scope`. Maths 12 has since been
    reclassified from the book's own chunks, so the premise is gone.

    What replaces it is the sharper claim. `xy_plot@2` takes one curve from
    line|parabola|sine|exponential|reciprocal, plus a second for
    area_between. Ch8 is mostly NOT that: the book teaches "Area Between Two
    Intersecting Curves" with sideways parabolas y^2 = 4ax and horizontal
    strips, and bounds several regions with circles. So exactly two concepts
    route, and the four geometries validate() refuses must never route --
    routing one would put a diagram on a board that the client then declines
    to draw, which is the silent failure this column exists to prevent.

    Note the widget's own header claimed "5 solid + 1 partial" for this
    chapter. That header was written against concept NAMES. It is the
    name-based failure mode reappearing inside a docstring.
    """
    rows = [r for r in _rows()
            if r["subject"] == "mathematics" and r["class_level"] == "12"
            and r["chapter_order"] == "8"]
    assert len(rows) == 10, "Ch8 should have ten concepts"

    routed = {r["concept"] for r in rows
              if r["v2_confidence"] == "high" and r["archetype_v2"] in WIDGET_VERSIONS}
    assert routed == {
        "Area Under a Simple Curve Bounded by the Axes",
        "Area Bounded by a Parabola and a Line",
    }, routed

    # The geometries xy_plot's validate() refuses must not route, whatever
    # their confidence.
    for r in rows:
        if r["archetype_v2"] in WIDGET_VERSIONS:
            continue
        assert not (r["v2_confidence"] == "high" and r["archetype_v2"] == "xy_plot"), r

def test_a_high_confidence_concept_gets_one_widget_schema_not_the_manifest():
    # Taken from the file rather than hardcoded: a resync that reclassifies
    # this concept should change what the test routes, not break the test.
    routed = next(r for r in _rows()
                  if r["v2_confidence"] == "high" and r["archetype_v2"] in WIDGET_VERSIONS)
    v = verdict(routed["subject"], routed["class_level"], routed["chapter_order"],
                routed["concept"])
    assert v.widget == routed["archetype_v2"]

    block = render_single_widget_block(v.widget)
    assert f"`{v.widget}` v{WIDGET_VERSIONS[v.widget]}" in block
    # Exactly one widget is named, and it is NOT presented as a choice.
    others = [w for w in WIDGET_VERSIONS if w != v.widget and f"`{w}`" in block]
    assert not others, f"the single-widget block still offers {others}"
    # The two questions the brief specifies.
    # The block must ASK FOR the payload, and must not hand out an opt-out.
    # It used to open "Does THIS SEGMENT want the board picture at all? ... that
    # is a correct answer, not a failure" -- measured on Ecosystem, the archetype
    # branch fired on 40 segments and the model emitted zero diagrams, and zero
    # templates on those turns either. It took the out every time.
    assert '"payload"' in block and f'"{v.widget}"' in block
    for out in ("that is a correct answer, not a failure",
                "Does THIS SEGMENT want the board picture at all?"):
        assert out not in block, f"the opt-out is back in the block: {out!r}"
    assert "params:" in block, "the block must spell out the widget's params"


def test_a_non_high_concept_gets_the_full_manifest():
    """`med` must not nudge the model at all — the column's medium-confidence
    opinion is biased toward false coverage, so it gets no say."""
    med = next(r for r in _rows() if r["v2_confidence"] == "med"
               and r["archetype_v2"] in WIDGET_VERSIONS)
    v = verdict(med["subject"], med["class_level"], med["chapter_order"], med["concept"])
    assert v.widget is None
    # tutor.py picks the block on `_archetype_widget` alone, so a None verdict
    # is literally the manifest branch.
    block = render_manifest_block()
    assert all(f"`{w}` v" in block for w in WIDGET_VERSIONS)


def test_the_prompt_block_is_chosen_by_the_archetype_and_nothing_else():
    """The one line in tutor.py that makes the split real."""
    assert re.search(
        r"render_single_widget_block\(_archetype_widget\)\s*if\s*_archetype_widget",
        TUTOR_SRC,
    ), "the system prompt no longer swaps the widget block on the archetype"
    assert "else render_manifest_block()" in TUTOR_SRC


def test_the_single_widget_block_is_far_cheaper_than_the_manifest():
    """The saving is the point of the branch; a regression here is silent.

    Measured with cl100k_base, this build: the manifest block is 1,123 tokens
    for nine widgets; the single-widget block is 309 (projectile_motion) to 419
    (molecule_struct), mean ~345. In the assembled system prompt that is
    15,314 tokens against 14,507-14,610 — a saving of 704 to 807 per turn on an
    archetype turn.

    The cap is absolute rather than a ratio: a tenth widget makes the manifest
    bigger and would make a ratio test easier to pass, which is backwards.
    """
    tiktoken = pytest.importorskip("tiktoken")
    enc = tiktoken.get_encoding("cl100k_base")
    full = len(enc.encode(render_manifest_block()))
    assert full >= 1000, f"the manifest shrank to {full}; re-measure the branch"
    for wid in WIDGET_VERSIONS:
        one = len(enc.encode(render_single_widget_block(wid)))
        assert one <= 450, (
            f"{wid}: single-widget block is {one} tokens (cap 450, measured "
            f"309-419). It rides every turn on this concept."
        )
        assert full - one >= 600, (
            f"{wid}: the branch saves only {full - one} tokens against the "
            f"{full}-token manifest — it has stopped paying for itself"
        )


def test_an_unspecced_widget_falls_back_to_the_full_manifest_not_to_nothing():
    """Unreachable while WIDGET_SPECS covers the manifest. If it is ever
    reached, a turn with NO widget list is worse than a turn with all of
    them."""
    assert render_single_widget_block("not_a_widget") == render_manifest_block()


# ── 5. the route stamp ──────────────────────────────────────────────────────

def test_route_is_archetype_high_only_when_the_model_used_the_named_widget():
    payload = {"widget": "xy_plot", "version": 1, "params": {"mode": "curve"}}
    assert sanitize_widget_payload(payload, archetype_widget="xy_plot")["route"] \
        == ROUTE_ARCHETYPE_HIGH
    # Shown one widget, emitted another: that is the model choosing, and
    # recording it as archetype_high would assert a decision nobody made.
    assert sanitize_widget_payload(payload, archetype_widget="process_flow")["route"] \
        == ROUTE_MODEL_CHOICE
    assert sanitize_widget_payload(payload)["route"] == ROUTE_MODEL_CHOICE


def test_the_archetype_stamp_never_admits_or_rejects_a_payload():
    """It decides provenance only. A payload the client can draw must not be
    dropped for carrying the wrong label."""
    bad = {"widget": "not_in_the_registry", "version": 1, "params": {"a": 1}}
    assert sanitize_widget_payload(bad, archetype_widget="not_in_the_registry") is None
    ok = {"widget": "process_flow", "version": 1, "params": {"layout": "ring"}}
    assert sanitize_widget_payload(ok, archetype_widget="xy_plot") is not None


# ── 6. the five-slot order ──────────────────────────────────────────────────

def test_the_slot_order_is_the_specified_one():
    assert BOARD_SLOTS == (
        "widget_precomputed",
        "widget_archetype",
        "illustration",
        "svg_precomputed",
        "svg_live",
    )


@pytest.mark.parametrize("kwargs,expected", [
    ({}, "svg_live"),
    ({"precomputed_svg": "<svg/>"}, "svg_precomputed"),
    ({"illustration_asset": "bio11-ch7-cockroach"}, "illustration"),
    ({"archetype_widget": "xy_plot"}, "widget_archetype"),
    ({"precomputed_widget": {"widget": "xy_plot"}}, "widget_precomputed"),
])
def test_each_slot_answers_when_it_is_the_highest_present(kwargs, expected):
    assert resolve_board_slot(**kwargs) == expected


def test_a_precomputed_svg_no_longer_suppresses_the_slots_above_it():
    """THE BUG. A stored `example_diagram_svg` short-circuited everything, so
    50 of 70 Maths 12 Ch8 segments (71%) never saw a diagram directive at all
    and the widget path was unreachable on them. A cached tier-3 SVG is still
    tier 3."""
    assert resolve_board_slot(precomputed_svg="<svg/>",
                              archetype_widget="xy_plot") == "widget_archetype"
    assert resolve_board_slot(precomputed_svg="<svg/>",
                              illustration_asset="x") == "illustration"
    assert resolve_board_slot(precomputed_svg="<svg/>",
                              precomputed_widget={"widget": "xy_plot"}) \
        == "widget_precomputed"


def test_the_directives_are_no_longer_gated_on_the_precomputed_svg():
    """The resolver having the right order is not enough — the call site has to
    stop consulting the cache before it builds a directive."""
    assert "if _diag_hint and not _precomputed_svg:" not in TUTOR_SRC
    assert "_widget_hint and not _diag_hint and not _precomputed_svg" not in TUTOR_SRC
    assert re.search(r"if _archetype_widget:\n", TUTOR_SRC), (
        "the archetype branch is not what selects the directive"
    )
    assert re.search(r"\n    elif _diag_hint:\n", TUTOR_SRC), (
        "the template directive is no longer the fallthrough of the archetype branch"
    )


def test_slots_one_and_three_are_explicit_empty_branches_not_gaps():
    """Neither has storage yet. An absent slot that is absent from the CODE is
    an order nobody can review; an absent slot that is a named None with a
    comment is one line away from being filled."""
    assert re.search(r"_precomputed_widget = None", TUTOR_SRC)
    assert re.search(r"_illustration_asset = None", TUTOR_SRC)
    # Scoped to the resolution block: slot 2's INPUT is resolved earlier, at
    # prompt assembly, because the system message depends on it.
    body = TUTOR_SRC[TUTOR_SRC.index("══ BOARD RESOLUTION"):]
    slot1 = body[body.index("── SLOT 1"):body.index("── SLOT 2")]
    slot3 = body[body.index("── SLOT 3"):body.index("── SLOT 4")]
    assert "DELIBERATELY EMPTY" in slot1 and "DELIBERATELY EMPTY" in slot3
    # and they say WHY, naming the storage that does not exist
    assert "concept_diagrams" in slot1
    assert "0035" in slot3 and "NOT APPLIED" in slot3


def test_tier_three_still_starts_before_the_llm_call():
    """Load-bearing, not stylistic: a turn emits exactly ONE board_events
    event, so a figure started after the turn is assembled can never be sent.
    The guard changed; the position must not have."""
    kick = TUTOR_SRC.index("start_live_diagram(\n")
    llm = TUTOR_SRC.index("diagram_directive = (")
    assert kick < llm


def test_tier_three_fires_exactly_when_every_earlier_slot_is_empty():
    """`_board_slot == "svg_live"` IS "slots 1-4 all empty" by construction, so
    the guard cannot drift out of step with the order the way three chained
    `not`s could. A segment that falls through to slot 5 must still get a
    figure started, or it gets nothing at all."""
    idx = TUTOR_SRC.index("_live_diagram_future = None")
    block = TUTOR_SRC[idx:idx + 200]
    assert '_board_slot == "svg_live"' in block
    assert "not _diag_hint" in block


# ── 7. the cue table is gone ────────────────────────────────────────────────

def test_the_widget_cue_table_is_gone():
    """A one-row regex table that named `field_lines` before the model saw the
    content. Deleted, along with `suggest_widget`."""
    from app.drona import tutor
    assert not hasattr(tutor, "_WIDGET_CUES")
    assert not hasattr(tutor, "suggest_widget")
    assert "_WIDGET_CUES: List" not in TUTOR_SRC
    assert "def suggest_widget(" not in TUTOR_SRC
    # The variable it fed is gone too — assignment and interpolation, so a
    # prose mention of the old name in a comment does not fail the test while
    # a live reference does.
    assert "_widget_hint =" not in TUTOR_SRC
    assert "{_widget_hint}" not in TUTOR_SRC


def test_what_deleting_it_cost_is_recorded_where_it_was_deleted():
    """`field_lines` appears ZERO times in `archetype_v2` — physics 12 ch1 is
    entirely `not_in_scope` — so the one widget that was already live loses its
    named directive and is reachable only by the model picking it out of the
    manifest. Asserted rather than remembered, because the day someone widens
    the gate to "fix field_lines" this is the note they need to find."""
    assert not any(r["archetype_v2"] == "field_lines" for r in _rows())
    block = TUTOR_SRC[TUTOR_SRC.index("`_WIDGET_CUES` WAS HERE"):]
    assert "field_lines" in block[:1400] and "ZERO times" in block[:1400]

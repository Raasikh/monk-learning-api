#!/usr/bin/env python3
"""H7 — put every proposed-n row into exactly one of three kinds.

    (i)   WRONG WIDGET for the objective. The objective asks to compare, rank,
          distinguish or list, and a schematic or sequence widget was chosen.
          Fixed at the SOURCE: such objectives should decline (or route to a
          table widget once one exists). A correct decline is a sane row.
    (ii)  RIGHT WIDGET, WRONG PAYLOAD. The picture is the right kind; its
          parameters are wrong. Re-authorable against the corrected spec.
    (iii) NEEDS A WIDGET THAT DOES NOT EXIST. Stays n, and the segment is added
          to the matching spec in docs/.

Classified from the proposal's own written reason plus the objective, by rules
that are printed with every row so a wrong call is visible rather than buried.
Ambiguous rows are marked and listed rather than silently bucketed — the whole
value of this pass is that Raasikh can disagree with a specific row.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

META = Path("/tmp/sane-review-meta.json")

# The objective asks for something TABULAR or a SELECTION — not a picture with
# a geometry. Measured against the corpus: these verbs are why 15 of bio's
# segments asked for a comparison_table by diag_hint.
TABULAR = re.compile(r"\b(compare|contrast|distinguish|differentiate|rank|list|"
                     r"classify|tabulate|types of|which can be|identify which|"
                     r"choose the correct|decision tree|advantages|limitations|"
                     r"factors that|key factors)\b", re.I)

# The reason names a PARAMETER fault: the right sort of picture, filled wrong.
PARAM_FAULT = re.compile(r"\b(arrow|label|caption|node|reagent|product name|"
                         r"shifted|blank|recycled|identical|axis|curve|value|"
                         r"active_node|param|prefix of the chain|highlight|"
                         r"units|missing|wrong direction|plateau)\b", re.I)

# The reason says nothing was drawn at all, or names a widget that does not exist.
NO_WIDGET = re.compile(r"\bnothing drawn\b|\bno widget\b|\bcomparison[_ ]table\b|"
                       r"\bdecision tree\b|\bpyramid\b|\bcannot (be )?draw\b|"
                       r"\bdoes not draw\b|\bnothing to draw\b", re.I)

# The reason says the CHOSEN widget is the wrong kind for the content.
WRONG_KIND = re.compile(r"\bfree_body_diagram for\b|\bcaptioned as\b|"
                        r"\bdrawn as a\b|\bforced into\b|\bray_diagram\b|"
                        r"\bvector_resolution\b|\binvented\b|\bmis-?teach\b|"
                        r"\bis a force diagram\b|\bwrong picture\b|"
                        r"\bdrawn as a reaction sequence\b", re.I)

SPEC = {"comparison_table": "docs/comparison-table-spec.md",
        "ecological_pyramid": "docs/ecological-pyramid-spec.md",
        "reaction_scheme_width": "docs/reaction-scheme-width-limit.md"}


#: Rows no rule matched, read individually and assigned here so the call is
#: visible and arguable rather than a default. (key, seg) -> (kind, spec, why).
MANUAL = {
    ("electric-field", 1): ("i", None,
        "conceptual segment about the two-stage field mechanism; a "
        "vector_resolution triangle is a computational device for a different "
        "skill. The correct move is a DECLINE — nothing in the registry draws "
        "'a charge modifies space and a second charge responds'."),
    ("electric-field-lines", 6): ("iii", "apparatus",
        "a gold-leaf electroscope is APPARATUS. There is no apparatus widget in "
        "the registry's twelve, so this cannot be drawn today; the sheet calls it "
        "the strongest decline-where-a-picture-was-needed case."),
    ("gauss-s-law-and-its-applications", 4): ("ii", None,
        "right widget, wrong configuration: parallel_plates for a SINGLE sheet. "
        "ALREADY FIXED in e518fab -> gaussian_pillbox, and counted in the "
        "physics 30 -> 32 reconciliation."),
    ("nomenclature-and-structure-of-carbonyl-compounds", 7): ("iii", "comparison_table",
        "two isomers shown side by side. molecule_struct draws ONE structure; "
        "nothing draws two compared, and a comparison_table of text cells is not "
        "a structure either. Needs a multi-structure figure that does not exist."),
    ("decomposition", 8): ("ii", None,
        "the closed loop is the same loop the subtopic drew earlier — a repeat "
        "figure, which is a parameter choice, not a missing widget."),
    ("eco-pyramids", 4): ("iii", "ecological_pyramid",
        "an ecological pyramid, which is the gap docs/ecological-pyramid-spec.md "
        "is written for."),
    ("phosphorus-cycle", 6): ("ii", None,
        "the chain stops at 'Locked for millions of years' and omits geological "
        "uplift — a missing node, which is a payload fault."),
}

#: Rows with NO recorded objective and only a criterion letter. There is nothing
#: to classify from. Listed rather than bucketed: guessing here would be the
#: check-that-passes-on-absent-information defect wearing a classifier's clothes.
NO_EVIDENCE = {("succession", 2), ("succession", 5), ("succession", 7)}


def classify(row):
    k = (row.get("key"), row.get("seg"))
    if k in MANUAL:
        kind, spec, why = MANUAL[k]
        return kind, spec, f"read by hand: {why}"
    if k in NO_EVIDENCE:
        return "no-evidence", None, ("the sheet records no objective and no written "
                                     "reason for this row")
    obj, why = row.get("objective") or "", row.get("reason") or ""
    declined = "decline" in (row.get("widget_sheet") or "").lower() \
        or "no widget" in (row.get("widget_sheet") or "").lower()
    tab = bool(TABULAR.search(obj))
    nw = bool(NO_WIDGET.search(why))
    wk = bool(WRONG_KIND.search(why))
    pf = bool(PARAM_FAULT.search(why))

    # (iii) first: if what it needs does not exist, nothing else matters.
    if nw or (tab and declined):
        want = ("ecological_pyramid" if re.search(r"pyramid", obj + why, re.I)
                else "reaction_scheme_width"
                if re.search(r"scheme|species|mechanism", why, re.I)
                else "comparison_table")
        return "iii", want, f"tabular={tab} no-widget-language={nw}"
    # (i): a widget fired but it is the wrong KIND for this objective.
    if wk or (tab and not declined):
        return "i", None, f"wrong-kind-language={wk} tabular-objective={tab}"
    # (ii): the right sort of picture, wrongly filled.
    if pf:
        return "ii", None, "names a parameter fault"
    return "?", None, "no rule matched — read this one"


def main() -> int:
    meta = json.loads(META.read_text())
    out, counts = [], Counter()
    for r in meta:
        kind, want, evidence = classify(r)
        counts[(r["sheet"], kind)] += 1
        out.append({**r, "v2_kind": kind, "v2_spec": want, "v2_evidence": evidence})
    Path("/tmp/sane-v2.json").write_text(json.dumps(out, indent=1))

    sheets = sorted({r["sheet"] for r in meta})
    print(f"{'sheet':<24}{'n':>4}{'(i) wrong widget':>18}{'(ii) payload':>14}"
          f"{'(iii) no widget':>17}{'no evidence':>13}")
    for s in sheets:
        n = sum(counts[(s, k)] for k in ('i', 'ii', 'iii', '?', 'no-evidence'))
        print(f"{s:<24}{n:>4}{counts[(s,'i')]:>18}{counts[(s,'ii')]:>14}"
              f"{counts[(s,'iii')]:>17}{counts[(s,'no-evidence')]:>13}")
    tot = Counter(r['v2_kind'] for r in out)
    print(f"\n{'total':<24}{len(out):>4}{tot['i']:>18}{tot['ii']:>14}"
          f"{tot['iii']:>17}{tot['no-evidence']:>13}")

    # What each chapter would reach IF every (i) row becomes a correct decline.
    # (ii) is deliberately NOT counted: a re-authored payload is not
    # automatically right — nucleophilic-addition seg 3 was re-authored and is
    # still n — so those rows are a possibility, not a number.
    BASE = {"physics 12 ch1": (32, 40), "chem 12 ch8": (94, 113),
            "maths 12 ch8": (31, 71), "biology 12 Ecosystem": (53, 70)}
    print(f"\n{'sheet':<24}{'now':>10}{'+(i) only':>12}{'clears 85?':>12}"
          f"{'(ii) still in play':>20}")
    for s in sheets:
        y, n = BASE[s]
        after = (y + counts[(s, 'i')]) / n * 100
        print(f"{s:<24}{y/n*100:>9.1f}%{after:>11.1f}%"
              f"{('yes' if after >= 85 else 'no'):>12}{counts[(s,'ii')]:>20}")
    if tot['?']:
        print(f"\n{tot['?']} row(s) no rule matched — these need reading, not a default:")
        for r in out:
            if r["v2_kind"] == "?":
                print(f"   [{r['sheet']}] {r['key']} seg{r['seg']}")
                print(f"      obj: {(r['objective'] or '(none)')[:96]}")
                print(f"      why: {(r['reason'] or '(none)')[:96]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

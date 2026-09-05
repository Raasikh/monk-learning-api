"""Measure what the tier-3 layout post-pass is worth, on one frozen sample.

    # 1. capture — the only step that costs model calls
    python3 scripts/measure_tier3_layout.py --capture --sample bio  --out /tmp/t3_bio.jsonl
    python3 scripts/measure_tier3_layout.py --capture --sample mixed --out /tmp/t3_mixed.jsonl

    # 2. score — free, offline, repeatable
    python3 scripts/measure_tier3_layout.py --score /tmp/t3_bio.jsonl

WHY TWO STEPS AND NOT ONE END-TO-END RUN
========================================
The obvious measurement is "run the authoring loop with the post-pass off, then
with it on, compare". It does not work. Authoring is a live model call at
temperature 0.2, and attempt 2 is CONDITIONED on attempt 1's rejection reason —
so turning the post-pass on changes the model's own input and the two runs are
not measuring the same thing. The difference you would report is the post-pass
plus whatever the model happened to draw differently.

So: capture every attempt's RAW SVG once, freeze it, and score validate() over
the identical bytes with the post-pass off and on. The only thing that differs
between before and after is the post-pass. That is the comparison the number is
supposed to mean, and it re-runs for free.

Attempt 2 is captured even when attempt 1 passed, so the sample is always
10 x 2. Production would have stopped; this is a measurement, and a 20-cell
sample that sometimes has 12 cells is not a sample.

TWO NUMBERS, BOTH REPORTED
==========================
per-attempt  — of 20 raw SVGs, how many pass validate(). The clean A/B.
per-concept  — of 10 concepts, how many end up with a diagram (attempt 1 OR 2).
               This is the one a student experiences, because the loop retries.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from dotenv import load_dotenv  # noqa: E402

# Path-based, like app/main.py: the script must find the repo's .env whatever
# directory it was launched from.
load_dotenv(os.path.join(ROOT, ".env"))

from app.drona.diagram_author import (  # noqa: E402
    _strip_fence, repair_layout, spec_for, validate,
)
from app.drona.models import get_drona_client, get_model_name, thinking_off  # noqa: E402

# The five biology concepts the live precompute rejected (from /tmp/c1b.log),
# verbatim, plus five more from the same chapter. Verbatim matters: the concept
# string IS the prompt, and paraphrasing it measures a different diagram.
BIO = [
    ("biology", "Taxonomic Hierarchy: Categories from Kingdom to Species — Define and differentiate between monotypic and polytypic genera, providing correct examples for each."),
    ("biology", "Taxonomic Hierarchy: Categories from Kingdom to Species — Use the downward-implies-upward rule and the master trend to solve typical NEET and board exam questions on taxonomic hierarchy."),
    ("biology", "Binomial Nomenclature: Rules and Conventions — Determine the relationship between two organisms by comparing their scientific names (genus and species)."),
    ("biology", "Binomial Nomenclature: Rules and Conventions — List and apply the five conventions for writing a scientific name correctly in print and handwriting."),
    ("biology", "Characteristics of Living Organisms — Recall the 'MCC' defining bundle and apply the two-gate test to solve typical NEET/CBSE MCQs on defining properties."),
    ("biology", "Taxonomic Aids: Herbarium, Botanical Garden, Museum and Zoological Park — Describe how a herbarium sheet is prepared and what information its label carries."),
    ("biology", "Taxonomic Keys, Flora, Manuals and Monographs — Work through a two-step dichotomous key to identify an unknown specimen."),
    ("biology", "Concept of Species and Taxon — Distinguish a species from a taxon using the biological species concept."),
    ("biology", "Biodiversity and the Need for Classification — Show why 1.7 million described species require a hierarchical classification."),
    ("biology", "Taxonomy, Systematics and Classification: Scope and Definitions — Separate taxonomy, systematics and classification by what each one does."),
]

# The same size sample spread across all four subjects, to test whether one
# chapter's failure mix is the corpus's failure mix. If these two disagree, the
# disagreement is the finding.
MIXED = [
    ("physics", "Equilibrium of Rigid Bodies — A ladder leaning on a smooth wall: draw the forces that hold it in equilibrium."),
    ("physics", "Projectile Motion — Draw the trajectory of a ball thrown at 20 m/s at 30 degrees, marking range and maximum height."),
    ("physics", "Ohm's Law — Draw a simple circuit with a 6 V cell and a 3 ohm resistor and mark the current."),
    ("chemistry", "Ionic Bond Formation — Draw the electron transfer from sodium to chlorine and the resulting ions."),
    ("chemistry", "Hybridisation — Draw the sp3 hybridised orbitals of methane with the bond angle marked."),
    ("chemistry", "Le Chatelier's Principle — Draw what happens to an equilibrium when pressure is increased."),
    ("mathematics", "Derivative as the Slope of a Tangent — Draw a curve, a secant and the tangent it approaches."),
    ("mathematics", "Definite Integral as Area — Draw the area under y = x squared between x = 0 and x = 2."),
    ("biology", "Structure of the Human Heart — Draw the four chambers and label the direction of blood flow."),
    ("biology", "Mitosis vs Meiosis — Draw the chromosome count at each stage of both."),
]

SAMPLES = {"bio": BIO, "mixed": MIXED}


def capture(sample_name: str, out_path: str, model: str | None, attempts: int) -> int:
    """Author every concept `attempts` times and write the RAW SVGs to jsonl.

    Faithful to author_diagram's loop, including the retry that feeds the
    previous rejection reason back — except that it never stops early, because
    a measurement needs every cell.
    """
    cases = SAMPLES[sample_name]
    client = get_drona_client()
    model_name = model or get_model_name("tutor")
    print(f"capturing {len(cases)} concepts x {attempts} attempts  model={model_name}\n")
    n = 0
    with open(out_path, "w") as fh:
        for ci, (subject, concept) in enumerate(cases, 1):
            explanation = f"Teaching {concept}."
            ask = (f"Subject: {subject}\nConcept: {concept}\n"
                   f"What is being explained: {explanation}\n\n"
                   f"Draw the diagram that makes this concept click for a student "
                   f"seeing it for the first time.")
            last = ""
            for attempt in range(1, attempts + 1):
                messages = [{"role": "system", "content": spec_for("simple")},
                            {"role": "user", "content": ask}]
                if attempt > 1:
                    messages.append({
                        "role": "user",
                        "content": f"Your previous SVG was rejected: {last}. "
                                   f"Return a corrected SVG obeying every rule.",
                    })
                t0 = time.time()
                err, raw, finish = "", "", ""
                try:
                    res = client.chat.completions.create(
                        model=model_name, messages=messages, temperature=0.2,
                        max_tokens=3500, timeout=120, extra_body=thinking_off())
                    raw = res.choices[0].message.content or ""
                    finish = getattr(res.choices[0], "finish_reason", "") or ""
                except Exception as exc:
                    err = f"call failed: {exc}"
                # _strip_fence is normalisation, not repair — it runs in both arms.
                from app.drona.diagram_author import _strip_fence
                svg = _strip_fence(raw)
                ok, reason = validate(svg)
                last = reason or err or "rejected"
                fh.write(json.dumps({
                    "subject": subject, "concept": concept, "attempt": attempt,
                    "svg": svg, "finish_reason": finish, "err": err,
                    "raw_chars": len(raw), "secs": round(time.time() - t0, 1),
                }) + "\n")
                fh.flush()
                n += 1
                print(f"  [{ci:>2}/{len(cases)}] a{attempt}  {time.time()-t0:5.1f}s  "
                      f"{len(raw):>5}ch  finish={finish or '-':10} "
                      f"{'PASS' if ok else 'fail: ' + last[:52]}")
    print(f"\ncaptured {n} attempts -> {out_path}")
    return 0


# validate()'s rejection strings, bucketed into the classes we are arguing about.
def classify(reason: str) -> str:
    r = reason.lower()
    if "outside the viewbox" in r:
        return "labels outside viewBox"
    if "overlapping labels" in r:
        return "overlapping labels"
    if "over filled shapes" in r:
        return "labels over filled shapes"
    if "font-family" in r:
        return "font-family present"
    if "not well-formed" in r:
        return "malformed XML"
    if "empty response" in r or "call failed" in r:
        return "empty / call failed"
    if "off-palette" in r:
        return "off-palette colours"
    if "does not start with" in r:
        return "not an SVG"
    if "draw steps" in r or "budget" in r:
        return "over budget"
    return "other: " + reason[:40]


def score(path: str) -> int:
    rows = [json.loads(l) for l in open(path) if l.strip()]
    by_concept: dict[str, list] = {}
    before_cls, after_cls, repaired, resisted = Counter(), Counter(), Counter(), Counter()
    new_failures, unlabelled, truncated, unrepairable = [], [], [], Counter()
    n_before = n_after = n_fence = 0

    for r in rows:
        # The corpus stores what the OLD _strip_fence produced, so the two arms
        # are separable: arm 0 is that byte-for-byte, arm F re-normalises it.
        svg = r["svg"]
        ok0, why0 = validate(svg)
        n_fence += validate(_strip_fence(svg))[0]
        fixed, rep = repair_layout(_strip_fence(svg))
        ok1, why1 = validate(fixed)
        n_before += ok0
        n_after += ok1
        by_concept.setdefault(r["concept"], []).append((ok0, ok1))

        if not ok0:
            c0 = classify(why0)
            before_cls[c0] += 1
            if ok1:
                repaired[c0] += 1
            else:
                resisted[c0] += 1
                after_cls[classify(why1)] += 1
        elif not ok1:
            # The post-pass broke something that was passing. This must be zero.
            new_failures.append((r["concept"][:50], why1[:70]))

        if rep["no_labels"]:
            unlabelled.append((r["concept"][:50], r["attempt"], ok0))
        for u in rep["unrepairable"]:
            unrepairable[u.split("(")[0].strip()[:60]] += 1
        # A response the model did not finish. finish_reason is definitive;
        # a missing </svg> is the fallback for providers that omit it.
        if r.get("finish_reason") == "length" or (svg and "</svg>" not in svg):
            truncated.append((r["concept"][:44], r["attempt"], r.get("finish_reason"),
                              r["raw_chars"]))

    n = len(rows)
    print(f"\n=== {path} — {n} attempts, {len(by_concept)} concepts ===\n")
    print(f"PER ATTEMPT   raw                       {n_before:>2}/{n} = {100*n_before/n:3.0f}%")
    print(f"              + trailing-prose strip    {n_fence:>2}/{n} = {100*n_fence/n:3.0f}%")
    print(f"              + layout post-pass        {n_after:>2}/{n} = {100*n_after/n:3.0f}%")
    cb = sum(1 for v in by_concept.values() if any(a for a, _ in v))
    ca = sum(1 for v in by_concept.values() if any(b for _, b in v))
    m = len(by_concept)
    print(f"PER CONCEPT   before {cb}/{m} = {100*cb/m:.0f}%"
          f"    after {ca}/{m} = {100*ca/m:.0f}%   (passes if either attempt does)")

    print("\nPER FAILURE CLASS (of the before-failures)")
    print(f"  {'class':30} {'before':>7} {'repaired':>9} {'resisted':>9}")
    for cls, cnt in before_cls.most_common():
        print(f"  {cls:30} {cnt:>7} {repaired[cls]:>9} {resisted[cls]:>9}")

    if after_cls:
        print("\nWHAT THE RESISTERS FAIL ON AFTER THE POST-PASS")
        for cls, cnt in after_cls.most_common():
            print(f"  {cls:44} {cnt}")

    print(f"\nNEW FAILURES INTRODUCED BY THE POST-PASS: {len(new_failures)}")
    for c, w in new_failures:
        print(f"  {c:52} {w}")

    print(f"\nUNREPAIRABLE (post-pass declined to touch it): {sum(unrepairable.values())}")
    for u, c in unrepairable.most_common():
        print(f"  {c:>3}  {u}")

    # Its own line, always printed, including when it is zero. A diagram with no
    # <text> PASSES validate() — nothing in the gate requires a label — so this
    # is a silent pass that has to be counted, not a clean layout.
    print(f"\nDIAGRAMS WITH NO LABELS AT ALL: {len(unlabelled)}"
          f"  (validate() passes these; they teach nothing)")
    for c, a, ok in unlabelled:
        print(f"  {c:52} attempt {a}  validate={ok}")

    print(f"\nTRUNCATED RESPONSES (not a layout failure — no post-pass can fix): "
          f"{len(truncated)}")
    for c, a, fr, ch in truncated:
        print(f"  {c:46} attempt {a}  finish_reason={fr!r}  {ch} chars")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--capture", action="store_true")
    ap.add_argument("--sample", choices=sorted(SAMPLES), default="bio")
    ap.add_argument("--attempts", type=int, default=2)
    ap.add_argument("--out", default="/tmp/t3_sample.jsonl")
    ap.add_argument("--model", default=None)
    ap.add_argument("--score", default=None, metavar="JSONL")
    a = ap.parse_args()
    if a.capture:
        return capture(a.sample, a.out, a.model, a.attempts)
    if a.score:
        return score(a.score)
    ap.error("give --capture or --score")


if __name__ == "__main__":
    sys.exit(main())

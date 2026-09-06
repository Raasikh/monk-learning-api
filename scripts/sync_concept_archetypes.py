#!/usr/bin/env python3
"""Re-copy the mobile repo's archetype classification into this repo.

    python3 scripts/sync_concept_archetypes.py [--mobile-repo PATH]

`app/drona/concept_archetypes.csv` is a VERBATIM, byte-for-byte copy of the
mobile repo's `content/concept-archetypes.csv`, which is the output of the
8-agent adversarial reclassification described in
`content/concept-archetypes.README.md` there. This script is the only supported
way to refresh it — the point is that nobody ever types an archetype or a
confidence into this repo.

WHY A COPY AND NOT A COLUMN ON `concepts`
-----------------------------------------
The `concepts` table has no `archetype_v2`. Adding one needs production DDL,
which this project does not apply without a written, reviewed migration — so
the code would have to work without the column anyway, which means it would
have to read the file anyway. The migration would then be a second copy of a
fact whose source of truth is a CSV in another repo, re-derived by a
reclassification pass whose own README says the verdicts "should be re-run
against the current corpus". A second copy with no drift check is exactly how
the widget manifest went stale (`xy_plot` 1 -> 2). So: one copy, with a drift
check that fails on a machine that has both checkouts.

Exit codes: 0 changed or already current, 1 could not find the source.
"""
import argparse
import collections
import csv
import io
import os
import shutil
import sys

API_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEST = os.path.join(API_ROOT, "app", "drona", "concept_archetypes.csv")
REL_SOURCE = os.path.join("content", "concept-archetypes.csv")

# Same candidate list scripts/sync_widget_manifest.py and the drift tests use —
# keep all three in step.
CANDIDATES = [
    os.environ.get("MONK_MOBILE_REPO", ""),
    os.path.join(os.path.dirname(API_ROOT), "monk-learning-mobile", "monklearning-mobile"),
    os.path.join(os.path.dirname(API_ROOT), "monklearning-mobile"),
]


def find_source(explicit: str = "") -> str:
    for root in ([explicit] if explicit else []) + CANDIDATES:
        if not root:
            continue
        candidate = os.path.join(root, REL_SOURCE)
        if os.path.isfile(candidate):
            return candidate
    return ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mobile-repo", default="", help="path to the monklearning-mobile checkout")
    args = ap.parse_args()

    source = find_source(args.mobile_repo)
    if not source:
        print(
            "sync_concept_archetypes: could not find content/concept-archetypes.csv.\n"
            "  Pass --mobile-repo PATH, or set MONK_MOBILE_REPO.",
            file=sys.stderr,
        )
        return 1

    before = ""
    if os.path.isfile(DEST):
        with open(DEST, "r", encoding="utf-8") as f:
            before = f.read()
    with open(source, "r", encoding="utf-8") as f:
        after = f.read()

    if before == after:
        print(f"sync_concept_archetypes: already current ({source}).")
    else:
        shutil.copyfile(source, DEST)
        print(f"sync_concept_archetypes: updated {DEST}\n  from {source}")

    rows = list(csv.DictReader(io.StringIO(after)))
    conf = collections.Counter(r["v2_confidence"] for r in rows)
    print(f"  {len(rows)} concepts; confidence " +
          "  ".join(f"{k}={v}" for k, v in sorted(conf.items())))

    # The only population the runtime acts on deterministically. Printed so a
    # sync that changes it is visible in the terminal rather than only in a diff.
    from app.drona.widget_registry import WIDGET_VERSIONS  # noqa: E402
    routed = [r for r in rows
              if r["v2_confidence"] == "high" and r["archetype_v2"] in WIDGET_VERSIONS]
    chapters = {(r["subject"], r["class_level"], r["chapter_order"]) for r in routed}
    print(f"  ROUTED DETERMINISTICALLY: {len(routed)} concepts across {len(chapters)} chapters — "
          + "  ".join(f"{k}={v}" for k, v in
                      sorted(collections.Counter(r["archetype_v2"] for r in routed).items())))

    if before and before != after:
        def keyed(text):
            return {(r["subject"], r["class_level"], r["chapter_order"], r["concept"]):
                    (r["archetype_v2"], r["v2_confidence"])
                    for r in csv.DictReader(io.StringIO(text))}
        old, new = keyed(before), keyed(after)
        changed = [k for k in sorted(set(old) | set(new)) if old.get(k) != new.get(k)]
        for k in changed[:40]:
            print(f"  CHANGED {k[0]} {k[1]} ch{k[2]} {k[3]!r}: "
                  f"{old.get(k, '(absent)')} -> {new.get(k, '(absent)')}")
        if len(changed) > 40:
            print(f"  ... and {len(changed) - 40} more")
        print("  A reclassification invalidates cached plans whose widget it chose — "
              "see the mobile repo's docs/plan-invalidation.md.")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, API_ROOT)
    raise SystemExit(main())

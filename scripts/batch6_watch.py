#!/usr/bin/env python3
"""Are the four Gemini batch-6 plates here yet, and what runs when they are?

    python3 scripts/batch6_watch.py            # status only
    python3 scripts/batch6_watch.py --plan     # status + the exact commands

ARRIVAL IS NOT THE SAME QUESTION FOR ALL FOUR, and getting that wrong is how a
watcher reports a plate that never came. Three of these slugs have no file at
all today, so for them "a file exists" IS arrival. The fourth is a REPLACEMENT:
`bio11-ch7-earthworm--morphology-and-digestive-system--a` already has a raw
file, ingested 2026-09-08, and a naive existence check calls it arrived the
moment you look. Measured: it did exactly that.

So the replacement carries a BASELINE sha of the raw file as it stands before
batch 6. Arrival means the bytes CHANGED, not that bytes are present.

Nothing here writes anything. It reports, and with --plan it prints the
commands to run, in order, so the ingest is one paste rather than one
recollection.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path

API = Path(__file__).resolve().parent.parent
MOB = Path("/Users/raasikhnaveed/Desktop/monk-learning-mobile/monklearning-mobile")
RAW = MOB / "content/illustrations/v1/raw"
MANIFEST = MOB / "content/illustrations/v1/illustration-manifest.csv"
BASELINE = API / "content/widget-payload-fixes/batch6-baseline.json"

#: slug -> ("new"|"replace"). A replacement is judged on CHANGE, a new slug on
#: presence, and the distinction is the whole reason this file exists.
TARGETS = {
    "bio11-ch7-earthworm--morphology-and-digestive-system--a": "replace",
    "bio11-ch7-cockroach--nervous-system-and-reproduction--b": "new",
    "bio11-ch7-cockroach--nervous-system-and-reproduction--c": "new",
    "bio11-ch7-frog--external-morphology-and-digestive-system--b": "new",
    # Added 2026-09-13 as "new": the Taenia plate, so platyhelminthes --b (a
    # planarian under a Taenia term list) can stay bare instead of being
    # mislabelled. It arrived 2026-09-14 and was INGESTED AND POINTED, then
    # HELD: the strobila is drawn in two disconnected pieces (the upper strand
    # ends in a closed terminal proglottid; the lower ribbon is a separate
    # closed shape). Raasikh ruled that a defect and a replacement is coming on
    # the same slug, so this flips to "replace" — arrival now means the bytes
    # CHANGED against the plate that is there, not that a file exists. Left as
    # "new" it would report ARRIVED forever against the defective plate.
    "bio11-ch4-phylum-platyhelminthes--c": "replace",
}


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def load_baseline() -> dict:
    return json.loads(BASELINE.read_text()) if BASELINE.exists() else {}


def save_baseline(b: dict) -> None:
    BASELINE.parent.mkdir(parents=True, exist_ok=True)
    BASELINE.write_text(json.dumps(b, indent=1) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", action="store_true", help="print the ingest commands too")
    args = ap.parse_args()

    base = load_baseline()
    arrived, waiting = [], []

    for slug, kind in sorted(TARGETS.items()):
        p = RAW / f"{slug}.png"
        if not p.exists():
            waiting.append((slug, kind, "no file"))
            continue
        h = sha(p)
        when = datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
        if kind == "new":
            arrived.append((slug, kind, h, when))
            continue
        # replacement: record the pre-batch-6 bytes once, then compare
        if slug not in base:
            base[slug] = {"baseline_sha": h, "seen": when}
            save_baseline(base)
            waiting.append((slug, kind, f"baseline recorded ({h[:12]}, {when}) — "
                                        f"this is the OLD file, not the new plate"))
            continue
        if h == base[slug]["baseline_sha"]:
            waiting.append((slug, kind, f"unchanged since {base[slug]['seen']} "
                                        f"— still the old plate"))
        else:
            arrived.append((slug, kind, h, when))

    print(f"batch 6 — {len(arrived)} arrived, {len(waiting)} waiting\n")
    for slug, kind, h, when in arrived:
        print(f"  ARRIVED  [{kind}] {slug}\n           sha {h[:16]}  {when}")
    for slug, kind, why in waiting:
        print(f"  waiting  [{kind}] {slug}\n           {why}")

    if args.plan and arrived:
        print("\n" + "=" * 72)
        print("run, in order (each step refuses rather than guesses):\n")
        print("  # 1. flip the manifest row to 'accepted' — ingest skips anything else")
        for slug, *_ in arrived:
            print(f"  #    {slug}")
        print(f"\n  # 2. ingest: strips labels from raw/, normalises, runs the corner and")
        print(f"  #    text checks, uploads master + @2x, writes the row")
        print(f"  python3 scripts/ingest_asset.py ingest \\")
        print(f"      --dir {MOB}/content/illustrations/v1/masters \\")
        print(f"      --manifest {MANIFEST} \\")
        print(f"      --work-order batch6 --generator-model gemini \\")
        print(f"      --strip {RAW} --execute")
        print(f"\n  # 3. reconciliation must be 0/0 in both directions")
        print(f"  python3 scripts/ingest_asset.py verify --manifest {MANIFEST}")
        print(f"\n  # 4. point it exactly as ch7, then regenerate the contact sheet")
        print(f"  python3 scripts/draft_anchors_pointed.py --set <slug> \\")
        print(f"      --in <points>.json --source claude-pointed --allow-unplaced")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

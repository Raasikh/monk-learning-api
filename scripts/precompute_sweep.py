#!/usr/bin/env python3
"""Precompute every chapter that has authored plans, in batches of ten.

    python3 scripts/precompute_sweep.py            # all of them
    python3 scripts/precompute_sweep.py --batch 10 --only physics

Authoring is UNGATED since 2026-09-15: every eligible routed row gets a payload
stored whatever its chapter's SANE verdict says. The verdict is applied later,
in `resolve_board_slot`, so this sweep is about filling slot 1, not about
deciding what the board will show.

Batches of ten with a summary per batch, because a 29-chapter run read as one
wall of lines is a thing nobody checks. Resumable: a chapter whose plans are
already current is skipped by `get_or_create_plan` itself, so re-running after
an interruption costs a read per concept rather than a re-author.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", type=int, default=10)
    ap.add_argument("--only", default="", help="substring filter on subject")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    from app.db import fetch_all

    chapters = {c["id"]: c for c in fetch_all("chapters", "id,name,subject,class_level")}
    with_plans = {p["chapter_id"] for p in fetch_all("lesson_plans", "id,chapter_id")}
    targets = sorted((c for cid, c in chapters.items() if cid in with_plans),
                     key=lambda c: (c["subject"], c["class_level"], c["name"]))
    if args.only:
        targets = [c for c in targets if args.only.lower() in c["subject"].lower()]

    print(f"{len(targets)} chapters, batches of {args.batch}\n", flush=True)
    done = failed = 0
    t_all = time.time()
    for i, ch in enumerate(targets):
        if i % args.batch == 0:
            print(f"── batch {i // args.batch + 1} "
                  f"(chapters {i + 1}-{min(i + args.batch, len(targets))})", flush=True)
        label = f"{ch['subject'][:4]} {ch['class_level']} {ch['name'][:40]}"
        if args.dry_run:
            print(f"   would run: {label}", flush=True)
            continue
        t0 = time.time()
        r = subprocess.run(
            [sys.executable, "-u", str(REPO / "scripts/precompute_chapter.py"),
             "--subject", ch["subject"], "--class-level", str(ch["class_level"]),
             "--chapter", ch["name"]],
            capture_output=True, text=True, cwd=str(REPO))
        dt = time.time() - t0
        tail = [l for l in r.stdout.splitlines() if "complete" in l]
        ok = r.returncode == 0
        done += ok
        failed += (not ok)
        print(f"   {'ok  ' if ok else 'FAIL'} {label:<48} {dt:6.0f}s  "
              f"{tail[-1].strip() if tail else ''}", flush=True)
        if not ok:
            for line in (r.stderr or r.stdout).splitlines()[-4:]:
                print(f"        {line}", flush=True)

    print(f"\n{done} chapter(s) complete, {failed} failed, "
          f"{(time.time() - t_all) / 60:.0f} min total", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

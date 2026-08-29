"""Author and store a board diagram for every concept in a chapter, or in all.

    # one chapter
    python3 scripts/precompute_diagrams.py --chapter "Units & Measurements" --class 11 --subject physics

    # the whole corpus — about 23 min at 8 workers, well under a dollar
    python3 scripts/precompute_diagrams.py --all --workers 8

    # a subject or a class at a time
    python3 scripts/precompute_diagrams.py --all --subject biology --workers 8
    python3 scripts/precompute_diagrams.py --all --class 11 --workers 8

Resumable by design: a concept that already has an active diagram is skipped
unless --force, so an interrupted run costs nothing to restart. That matters
more than it sounds for a 1,100-concept job.

This is the precompute lane, so per AGENTS.md it may use a stronger model than
the live tutor path. --model overrides it.

Concepts that already have an active diagram are skipped unless --force, so a
partial run can be resumed without paying for the work twice.
"""
import argparse
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db import supabase  # noqa: E402
from app.drona.diagram_author import author_diagram, validate  # noqa: E402
from app.drona.models import get_model_name  # noqa: E402


def resolve_chapter(name: str, subject: str, class_level: int) -> dict:
    rows = (supabase.table("chapters").select("id, name, subject, class_level")
            .eq("name", name).eq("subject", subject)
            .eq("class_level", class_level).limit(2).execute().data or [])
    if not rows:
        raise SystemExit(f"no chapter {name!r} in {subject} class {class_level}")
    if len(rows) > 1:
        # Three chapter names collide across subjects/classes; this is why the
        # lookup takes all three fields rather than a name.
        raise SystemExit(f"{name!r} is ambiguous — {len(rows)} matches")
    return rows[0]


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--chapter", default=None)
    p.add_argument("--subject", default=None)
    p.add_argument("--class", dest="class_level", type=int, default=None)
    p.add_argument("--all", action="store_true",
                   help="every chapter; combine with --subject or --class to narrow")
    p.add_argument("--workers", type=int, default=1,
                   help="concepts authored concurrently. 8 is comfortable; the "
                        "job is model-bound, not CPU-bound")
    p.add_argument("--model", default=None, help="override the authoring model")
    p.add_argument("--dry-run", action="store_true", help="author but do not store")
    p.add_argument("--force", action="store_true", help="re-author concepts that already have one")
    p.add_argument("--out", default=None, help="also write each svg here to eyeball")
    p.add_argument("--detail", default="simple", choices=["simple", "rich"],
                   help="simple = one concrete worked example (default); rich = a full illustration")
    args = p.parse_args()

    if not args.all and not (args.chapter and args.subject and args.class_level):
        raise SystemExit("give --chapter --subject --class, or --all")

    q = supabase.table("chapters").select("id, name, subject, class_level, chapter_order")
    if args.subject:
        q = q.eq("subject", args.subject)
    if args.class_level:
        q = q.eq("class_level", args.class_level)
    if args.chapter:
        q = q.eq("name", args.chapter)
    chapters = sorted(q.execute().data or [],
                      key=lambda c: (c["subject"], c["class_level"], c.get("chapter_order") or 0))
    if not chapters:
        raise SystemExit("no chapters matched")

    concepts = []
    by_chapter = {}
    for ch in chapters:
        rows = (supabase.table("concepts").select("id, name, teach_order, active")
                .eq("chapter_id", ch["id"]).eq("active", True).execute().data or [])
        for c in sorted(rows, key=lambda c: c.get("teach_order") or 0):
            concepts.append((ch, c))
        by_chapter[ch["id"]] = len(rows)

    try:
        existing = {
            r["concept_id"] for r in
            (supabase.table("concept_diagrams").select("concept_id")
             .eq("active", True).execute().data or [])
        }
    except Exception as exc:
        if not args.dry_run:
            raise SystemExit(
                f"concept_diagrams is not available ({str(exc)[:80]}). "
                f"Run migrations/0029_concept_diagrams.sql first, or use --dry-run."
            )
        print("(concept_diagrams not present — dry run only)\n")
        existing = set()

    todo = [(ch, c) for ch, c in concepts if args.force or c["id"] not in existing]
    model = args.model or get_model_name("tutor")
    if args.out:
        os.makedirs(args.out, exist_ok=True)

    print(f"{len(chapters)} chapter(s), {len(concepts)} concepts, {len(todo)} to author")
    print(f"model={model}  detail={args.detail}  workers={args.workers}  "
          f"dry_run={args.dry_run}  force={args.force}\n")

    lock = threading.Lock()
    counts = {"made": 0, "failed": 0}
    t_all = time.time()

    def work(item):
        ch, c = item
        t0 = time.time()
        svg, reason = author_diagram(
            subject=ch["subject"], concept=c["name"],
            explanation=f"Teaching {c['name']} in {ch['name']}, class {ch['class_level']}.",
            model=args.model, detail=args.detail,
        )
        dt = time.time() - t0
        label = f'{ch["subject"][:4]}{ch["class_level"]} {c["name"][:38]}'
        if not svg:
            with lock:
                counts["failed"] += 1
                n = counts["made"] + counts["failed"]
                print(f'  [{n:>4}/{len(todo)}] FAIL {dt:5.1f}s  {label:46} {reason[:40]}')
            return
        if args.out:
            with open(os.path.join(args.out, f'{c["id"][:8]}.svg'), "w") as fh:
                fh.write(svg)
        if not args.dry_run:
            # Serialised: PostgREST is happy enough concurrently, but a partial
            # write racing its own retire would leave two active diagrams for
            # one concept, and the reader takes the newest of those blindly.
            with lock:
                if args.force:
                    supabase.table("concept_diagrams").update({"active": False}) \
                        .eq("concept_id", c["id"]).eq("active", True).execute()
                supabase.table("concept_diagrams").insert([{
                    "concept_id": c["id"], "svg": svg, "source_model": model,
                    "drawn_for": f'[{args.detail}] {c["name"]}',
                }]).execute()
        with lock:
            counts["made"] += 1
            n = counts["made"] + counts["failed"]
            rate = n / max(1e-6, time.time() - t_all)
            eta = (len(todo) - n) / rate / 60 if rate else 0
            print(f'  [{n:>4}/{len(todo)}] ok   {dt:5.1f}s  {label:46} '
                  f'{len(svg):>5}ch  eta {eta:.0f}m')

    if args.workers > 1:
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            list(ex.map(work, todo))
    else:
        for item in todo:
            work(item)

    mins = (time.time() - t_all) / 60
    print(f'\n{counts["made"]} authored, {len(concepts) - len(todo)} skipped, '
          f'{counts["failed"]} failed in {mins:.1f} min')
    if counts["failed"]:
        print("  re-run the same command to retry only the failures — "
              "successes are skipped automatically")
    if args.out:
        print(f"svgs written to {args.out}")
    return 1 if counts["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())

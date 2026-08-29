"""Author and store a board diagram for every concept in a chapter.

    python3 scripts/precompute_diagrams.py --chapter "Units & Measurements" --class 11 --subject physics
    python3 scripts/precompute_diagrams.py --chapter "Units & Measurements" --class 11 --subject physics --dry-run
    python3 scripts/precompute_diagrams.py ... --out /tmp/preview   # also write .svg files to look at

This is the precompute lane, so per AGENTS.md it may use a stronger model than
the live tutor path. --model overrides it.

Concepts that already have an active diagram are skipped unless --force, so a
partial run can be resumed without paying for the work twice.
"""
import argparse
import os
import sys
import time

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
    p.add_argument("--chapter", required=True)
    p.add_argument("--subject", required=True)
    p.add_argument("--class", dest="class_level", type=int, required=True)
    p.add_argument("--model", default=None, help="override the authoring model")
    p.add_argument("--dry-run", action="store_true", help="author but do not store")
    p.add_argument("--force", action="store_true", help="re-author concepts that already have one")
    p.add_argument("--out", default=None, help="also write each svg here to eyeball")
    args = p.parse_args()

    ch = resolve_chapter(args.chapter, args.subject, args.class_level)
    concepts = sorted(
        (supabase.table("concepts")
         .select("id, name, teach_order, active")
         .eq("chapter_id", ch["id"]).eq("active", True).execute().data or []),
        key=lambda c: c.get("teach_order") or 0,
    )
    # Tolerated rather than required, so --dry-run works before migration 0029
    # has been applied — which is exactly when you want to look at the output.
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
    model = args.model or get_model_name("tutor")
    if args.out:
        os.makedirs(args.out, exist_ok=True)

    print(f"{ch['name']} (class {ch['class_level']} {ch['subject']}) — {len(concepts)} concepts")
    print(f"model={model}  dry_run={args.dry_run}  force={args.force}\n")

    made = skipped = failed = 0
    t_all = time.time()
    for c in concepts:
        if c["id"] in existing and not args.force:
            print(f"  {c['teach_order']:>2}. {c['name'][:52]:54} SKIP (already has one)")
            skipped += 1
            continue
        t0 = time.time()
        # The concept name IS the explanation for a precomputed diagram — there
        # is no student question yet. Live authoring passes the real utterance.
        svg, reason = author_diagram(
            subject=ch["subject"], concept=c["name"],
            explanation=f"Teaching {c['name']} in {ch['name']}, class {ch['class_level']}.",
            model=args.model,
        )
        dt = time.time() - t0
        if not svg:
            print(f"  {c['teach_order']:>2}. {c['name'][:52]:54} FAIL {dt:5.1f}s  {reason[:44]}")
            failed += 1
            continue
        if args.out:
            open(os.path.join(args.out, f"{c['teach_order']:02d}_{c['id'][:8]}.svg"), "w").write(svg)
        if not args.dry_run:
            if args.force:
                supabase.table("concept_diagrams").update({"active": False}) \
                    .eq("concept_id", c["id"]).eq("active", True).execute()
            supabase.table("concept_diagrams").insert([{
                "concept_id": c["id"], "svg": svg, "source_model": model,
                "drawn_for": c["name"],
            }]).execute()
        print(f"  {c['teach_order']:>2}. {c['name'][:52]:54} OK   {dt:5.1f}s  {len(svg):>5}ch")
        made += 1

    print(f"\n{made} authored, {skipped} skipped, {failed} failed "
          f"in {time.time() - t_all:.0f}s")
    if args.out:
        print(f"svgs written to {args.out}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

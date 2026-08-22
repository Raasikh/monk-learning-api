"""
seed_doubt_of_the_day.py — load the curated doubt pool into `doubt_of_the_day`.

Source is dotd_all.json in the content repo: 1000 doubts, 250 each of physics,
chemistry, mathematics and biology, each with a verified answer and
explanation.

Two things this script decides that the source file does not:

1. `subject_ordinal` — rows are numbered 1..N within each subject, in the
   file's own order, so the app can address one exact doubt with an indexed
   lookup instead of counting and paging. Ordinals are assigned to the sorted
   question text rather than to file position, so re-running after the JSON is
   re-ordered or appended to does not silently reshuffle what every student
   sees tomorrow.

2. `exam_tracks` — the JSON's `_exam_track` marks all physics and chemistry
   "JEE" purely because of where those rows were authored. Taken literally, a
   NEET student would only ever be served biology. Physics and chemistry are
   tagged for both tracks here; mathematics stays JEE-only and biology stays
   NEET-only, which is the real syllabus split.

Idempotent: upserts on (subject, subject_ordinal). Because ordinals are derived
from the sorted question text, re-running over unchanged content maps every
doubt back onto its own row, so ids survive and any drona_sessions pointing at
them stay valid. If the pool itself changes, ordinals shift and rows are
rewritten in place by position — use --replace for a clean rebuild instead.

Usage:
    python scripts/seed_doubt_of_the_day.py [path/to/dotd_all.json] [--dry-run] [--replace]
"""

import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, ".")

from app.db import supabase  # noqa: E402

DEFAULT_SOURCE = Path(
    "/Users/raasikhnaveed/Desktop/dronav1project/apps_and_demos/Doubt_Of_The_Day/dotd_all.json"
)

VALID_SUBJECTS = {"physics", "chemistry", "mathematics", "biology"}

# Which tracks each subject's doubts are eligible for. Physics and chemistry
# are shared; see the module docstring on why `_exam_track` is not trusted.
SUBJECT_TRACKS = {
    "physics": ["JEE", "NEET"],
    "chemistry": ["JEE", "NEET"],
    "mathematics": ["JEE"],
    "biology": ["NEET"],
}

BATCH = 200


def load_rows(source: Path) -> list[dict]:
    raw = json.loads(source.read_text())
    if not isinstance(raw, list):
        raise SystemExit(f"Expected a JSON array in {source}, got {type(raw).__name__}")

    by_subject: dict[str, list[dict]] = defaultdict(list)
    skipped = 0

    for item in raw:
        subject = (item.get("subject") or "").strip().lower()
        question = (item.get("question_text") or "").strip()
        answer = (item.get("_answer") or "").strip()
        explanation = (item.get("_explanation") or "").strip()

        # Every field below is fed to the tutor prompt as ground truth. A row
        # missing any of them would produce a doubt the teacher cannot resolve,
        # so drop it here rather than discovering it live in a student's chat.
        if subject not in VALID_SUBJECTS or not question or not answer or not explanation:
            skipped += 1
            continue

        by_subject[subject].append({
            "subject": subject,
            "chapter": (item.get("_chapter") or "").strip() or None,
            "concept": (item.get("_concept") or "").strip() or None,
            "question_text": question,
            "answer": answer,
            "explanation": explanation,
            "difficulty": (item.get("difficulty") or "").strip() or None,
            "exam_tracks": SUBJECT_TRACKS[subject],
        })

    rows: list[dict] = []
    for subject in sorted(by_subject):
        # Sorted by question text, not file order — see the docstring.
        ordered = sorted(by_subject[subject], key=lambda r: r["question_text"])
        for ordinal, row in enumerate(ordered, start=1):
            rows.append({**row, "subject_ordinal": ordinal})

    if skipped:
        print(f"  skipped {skipped} incomplete/unknown-subject rows")
    return rows


def main():
    flags = {"--dry-run", "--replace"}
    args = [a for a in sys.argv[1:] if a not in flags]
    dry_run = "--dry-run" in sys.argv
    replace = "--replace" in sys.argv
    source = Path(args[0]) if args else DEFAULT_SOURCE

    if not source.exists():
        raise SystemExit(f"Source not found: {source}")

    print(f"Reading {source}")
    rows = load_rows(source)

    counts = defaultdict(int)
    for r in rows:
        counts[r["subject"]] += 1
    print(f"  {len(rows)} doubts: " + ", ".join(f"{s}={counts[s]}" for s in sorted(counts)))

    dupes = len(rows) - len({r["question_text"] for r in rows})
    if dupes:
        # Duplicates each take an ordinal of their own, so nothing is lost --
        # but a student would eventually see the same doubt twice in one
        # rotation, which is worth knowing about before it happens.
        print(f"  warning: {dupes} rows share their question_text with another row")

    if dry_run:
        print("--dry-run: nothing written")
        return

    if replace:
        # drona_sessions.doubt_id is ON DELETE SET NULL, so old chat sessions
        # survive this with a null pointer rather than being cascaded away.
        print("  --replace: clearing existing rows")
        supabase.table("doubt_of_the_day").delete().neq(
            "id", "00000000-0000-0000-0000-000000000000"
        ).execute()

    written = 0
    for i in range(0, len(rows), BATCH):
        chunk = rows[i:i + BATCH]
        supabase.table("doubt_of_the_day").upsert(
            chunk, on_conflict="subject,subject_ordinal"
        ).execute()
        written += len(chunk)
        print(f"  upserted {written}/{len(rows)}")

    total = supabase.table("doubt_of_the_day").select("*", count="exact", head=True).execute()
    print(f"Done. doubt_of_the_day now holds {total.count} rows.")


if __name__ == "__main__":
    main()

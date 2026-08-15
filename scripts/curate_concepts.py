"""
curate_concepts.py — draft the canonical concepts taxonomy for one subject.

For each chapter of the subject, DeepSeek v4 Flash reads:
  (a) the chapter's Drona subtopics (subtopic_index),
  (b) the question bank's free-text concept tags for that chapter (with counts),
  (c) its own knowledge of what JEE Main / NEET actually ask,
and drafts 10–15 concepts ranked by exam importance (display_order = 1 is the
most-asked). Every provided subtopic and question tag is mapped onto exactly
one concept and written to concept_aliases — that mapping is what lets Drona
lessons credit concepts and lets existing questions resolve without a rewrite.

Writes straight to Supabase (concepts + concept_aliases) so the review surface
is the table editor. Chapters that already have concepts are SKIPPED unless
--replace is passed, so re-runs are safe and partial failures resume cleanly.

Usage:
  python scripts/curate_concepts.py physics            # draft missing chapters
  python scripts/curate_concepts.py physics --replace  # redo all chapters
  python scripts/curate_concepts.py physics --chapter "Rotational Motion"

Env: DEEPSEEK_API_KEY (already in .env), SUPABASE_* (already in .env).
"""

import argparse
import json
import re
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, ".")

from app.db import supabase                      # noqa: E402
from app.drona.models import get_drona_client, get_model_name  # noqa: E402

CONCURRENCY = 6
MIN_CONCEPTS, MAX_CONCEPTS = 8, 16   # prompt asks for 10–15; tolerate the edges


def norm(s: str) -> str:
    """Same normalization the practice router uses for chapter-name matching."""
    return (s or "").strip().lower().replace("&", "and")


# subtopic_index carries ingestion junk: dozens of "X RW-909755" duplicates,
# "X (Cache Miss 020000)" artifacts, and navigation filler rows. The model sees
# only the cleaned base names; aliases are expanded back to every raw variant
# afterwards so all real subtopic rows still resolve to a concept.
_JUNK_SUFFIX = re.compile(r"\s*(RW-\d+|\(Cache Miss \d+\))\s*$")
_FILLER = {"chapter wrap-up", "chapter recap and revision", "chapter recap", "revision"}


def clean_subtopics(raw_names):
    """Returns (base_names_for_prompt, {base_name: [raw variants]})."""
    variants = {}
    for raw in raw_names:
        base = raw
        while True:
            stripped = _JUNK_SUFFIX.sub("", base)
            if stripped == base:
                break
            base = stripped
        if norm(base) in _FILLER:
            continue  # lesson navigation, not a teachable skill — no concept credit
        variants.setdefault(base, []).append(raw)
    return list(variants), variants


def slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s[:80] or "concept"


SYSTEM_PROMPT = """You are the head of academics at a JEE/NEET coaching institute, \
building the canonical concept taxonomy for one chapter. A "concept" is a separately \
testable skill — one line on a student's report card — NOT a lesson section and NOT a \
question type. You know the last decade of JEE Main and NEET papers intimately."""

USER_PROMPT = """Chapter: "{chapter}" (Class {class_level} {subject})

Draft the definitive list of 10-15 concepts for this chapter. Rules:

1. Each concept is a distinct, testable skill. Never split one skill into parts
   ("Torque - Part 1/2" is wrong). Never merge two skills the exam tests separately.
   NO overlapping or near-duplicate concepts: "Angular Momentum", "Torque and Angular
   Momentum" and "Angular Momentum Conservation" side by side is wrong - pick clean,
   mutually exclusive boundaries so every question has exactly one home.
2. Order by exam importance: display_order 1 = most frequently asked in JEE Main /
   NEET over the last decade. This ordering is shown to students, take it seriously.
3. Small chapters genuinely have fewer testable skills - 10 is a target, not a quota.
   Never invent filler to reach it.
4. "exams": which exams test this concept - ["jee","neet"], ["jee"], or ["neet"].
   {exam_hint}
5. Map EVERY item below onto exactly one concept (the one it teaches/tests most).
   Copy alias strings VERBATIM - character for character - from the lists below.

Drona lesson subtopics for this chapter (map each one):
{subtopics_json}

Question-bank tags for this chapter, with question counts (map each one):
{tags_json}

Return ONLY JSON, exactly this shape:
{{
  "concepts": [
    {{
      "name": "Angular Momentum Conservation",
      "exams": ["jee", "neet"],
      "display_order": 1,
      "subtopic_aliases": ["<verbatim subtopic>", ...],
      "question_tag_aliases": ["<verbatim tag>", ...]
    }}
  ]
}}
Alias arrays may be empty. Every subtopic and every tag must appear in exactly one
concept's alias arrays."""


def fetch_inputs(subject: str):
    chapters = (
        supabase.table("chapters")
        .select("id, name, class_level")
        .ilike("subject", subject)
        .execute()
        .data
    )

    subs_by_chapter = defaultdict(list)
    for off in range(0, 5000, 1000):
        batch = (
            supabase.table("subtopic_index")
            .select("chapter_id, subtopic")
            .range(off, off + 999)
            .execute()
            .data
        )
        if not batch:
            break
        for s in batch:
            subs_by_chapter[s["chapter_id"]].append(s["subtopic"])

    # question tags key by chapter_name in the questions table, not chapter_id
    tags_by_chapter_norm = defaultdict(Counter)
    exam_counts = defaultdict(Counter)
    for off in range(0, 10000, 1000):
        batch = (
            supabase.table("questions")
            .select("chapter_name, concept, subject, target_exams")
            .ilike("subject", subject)
            .range(off, off + 999)
            .execute()
            .data
        )
        if not batch:
            break
        for q in batch:
            if q.get("concept") and q.get("chapter_name"):
                key = norm(q["chapter_name"])
                tags_by_chapter_norm[key][q["concept"]] += 1
                for ex in q.get("target_exams") or []:
                    exam_counts[key][str(ex).lower()] += 1

    return chapters, subs_by_chapter, tags_by_chapter_norm, exam_counts


def curate_chapter(client, model, subject, chapter, subtopics, tags, exam_hint):
    tags_sorted = dict(sorted(tags.items(), key=lambda kv: -kv[1]))
    prompt = USER_PROMPT.format(
        chapter=chapter["name"],
        class_level=chapter["class_level"],
        subject=subject.capitalize(),
        exam_hint=exam_hint,
        subtopics_json=json.dumps(subtopics, ensure_ascii=False, indent=1),
        tags_json=json.dumps(tags_sorted, ensure_ascii=False, indent=1),
    )
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        response_format={"type": "json_object"},
        temperature=0.2,
        timeout=120,
    )
    data = json.loads(resp.choices[0].message.content)
    concepts = data.get("concepts") or []

    # --- validation ---------------------------------------------------------
    problems = []
    if not (MIN_CONCEPTS <= len(concepts) <= MAX_CONCEPTS):
        problems.append(f"{len(concepts)} concepts (outside {MIN_CONCEPTS}-{MAX_CONCEPTS})")

    valid_subs, valid_tags = set(subtopics), set(tags)
    seen_subs, seen_tags = Counter(), Counter()
    for c in concepts:
        c["exams"] = [e for e in (c.get("exams") or ["jee", "neet"]) if e in ("jee", "neet")] or ["jee", "neet"]
        c["subtopic_aliases"] = [a for a in c.get("subtopic_aliases", []) if a in valid_subs]
        c["question_tag_aliases"] = [a for a in c.get("question_tag_aliases", []) if a in valid_tags]
        seen_subs.update(c["subtopic_aliases"])
        seen_tags.update(c["question_tag_aliases"])

    unmapped_subs = sorted(valid_subs - set(seen_subs))
    unmapped_tags = sorted(valid_tags - set(seen_tags))
    dupes = [a for a, n in (seen_subs + seen_tags).items() if n > 1]
    if dupes:  # alias claimed by two concepts: keep first claimant only
        for a in dupes:
            kept = False
            for c in concepts:
                for field in ("subtopic_aliases", "question_tag_aliases"):
                    if a in c[field]:
                        if kept:
                            c[field] = [x for x in c[field] if x != a]
                        kept = True

    return concepts, unmapped_subs, unmapped_tags, problems


def write_chapter(chapter, concepts, sub_variants):
    rows = []
    used_keys = set()
    for c in sorted(concepts, key=lambda c: c.get("display_order", 99)):
        key = slugify(c["name"])
        while key in used_keys:
            key += "-2"
        used_keys.add(key)
        rows.append({
            "chapter_id": chapter["id"],
            "name": c["name"].strip(),
            "key": key,
            "exams": c["exams"],
            "display_order": c.get("display_order", 99),
        })
    res = supabase.table("concepts").upsert(rows, on_conflict="chapter_id,key").execute()
    id_by_key = {r["key"]: r["id"] for r in res.data}

    alias_rows, collisions = [], []
    for c, row in zip(sorted(concepts, key=lambda c: c.get("display_order", 99)), rows):
        cid = id_by_key[row["key"]]
        for a in c["subtopic_aliases"]:
            # expand cleaned base name back to every raw subtopic_index variant
            for raw in sub_variants.get(a, [a]):
                alias_rows.append({"concept_id": cid, "alias": raw, "source": "subtopic"})
        for a in c["question_tag_aliases"]:
            alias_rows.append({"concept_id": cid, "alias": a, "source": "question_tag"})
    if alias_rows:
        # unique (alias, source) is GLOBAL: a tag name reused by another chapter
        # collides. ignore_duplicates keeps the first claimant; collisions are
        # reported so they can be reviewed rather than silently dropped.
        before = supabase.table("concept_aliases").select("id", count="exact").limit(0).execute().count
        supabase.table("concept_aliases").upsert(
            alias_rows, on_conflict="alias,source", ignore_duplicates=True
        ).execute()
        after = supabase.table("concept_aliases").select("id", count="exact").limit(0).execute().count
        if after - before < len(alias_rows):
            collisions.append(f"{len(alias_rows) - (after - before)} alias(es) already claimed elsewhere")
    return len(rows), len(alias_rows), collisions


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("subject")
    ap.add_argument("--replace", action="store_true", help="redo chapters that already have concepts")
    ap.add_argument("--chapter", help="only this chapter (by name)")
    args = ap.parse_args()

    client = get_drona_client()
    model = get_model_name("scoping")  # deepseek-v4-flash
    chapters, subs, tags_norm, exam_counts = fetch_inputs(args.subject)
    if args.chapter:
        chapters = [c for c in chapters if norm(c["name"]) == norm(args.chapter)]
    print(f"{len(chapters)} {args.subject} chapters | model: {model}")

    existing = supabase.table("concepts").select("chapter_id").execute().data
    done_ids = {r["chapter_id"] for r in existing}

    report_lines = [f"# Concept curation draft — {args.subject}\n"]
    t0 = time.time()

    def job(ch):
        if ch["id"] in done_ids and not args.replace:
            return ch, None, "skipped (already curated)"
        ekey = norm(ch["name"])
        ecounts = exam_counts.get(ekey, Counter())
        hint = f"Question bank for this chapter: {dict(ecounts)}." if ecounts else \
               "No exam data for this chapter yet; use syllabus knowledge."
        try:
            base_subs, sub_variants = clean_subtopics(subs.get(ch["id"], []))
            concepts, u_subs, u_tags, problems = curate_chapter(
                client, model, args.subject, ch,
                base_subs, dict(tags_norm.get(ekey, {})), hint,
            )
            if args.replace and ch["id"] in done_ids:
                supabase.table("concepts").delete().eq("chapter_id", ch["id"]).execute()
            n_c, n_a, collisions = write_chapter(ch, concepts, sub_variants)
            notes = []
            if problems:   notes.append("; ".join(problems))
            if u_subs:     notes.append(f"unmapped subtopics: {u_subs}")
            if u_tags:     notes.append(f"unmapped tags: {u_tags}")
            if collisions: notes.append("; ".join(collisions))
            return ch, concepts, f"{n_c} concepts, {n_a} aliases" + (f" | ⚠ {' | '.join(notes)}" if notes else "")
        except Exception as e:
            return ch, None, f"FAILED: {e}"

    with ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
        futures = {pool.submit(job, ch): ch for ch in chapters}
        for fut in as_completed(futures):
            ch, concepts, status = fut.result()
            print(f"  [{ch['class_level']}] {ch['name']}: {status}")
            report_lines.append(f"\n## {ch['name']} (Class {ch['class_level']}) — {status}\n")
            for c in sorted(concepts or [], key=lambda c: c.get("display_order", 99)):
                exams = "+".join(c["exams"])
                n_al = len(c["subtopic_aliases"]) + len(c["question_tag_aliases"])
                report_lines.append(f"{c.get('display_order','?'):>3}. {c['name']}  [{exams}] ({n_al} aliases)")

    out = f"scratch/concepts_draft_{args.subject}.md"
    with open(out, "w") as f:
        f.write("\n".join(report_lines))
    print(f"\nDone in {time.time()-t0:.0f}s → {out}")


if __name__ == "__main__":
    main()

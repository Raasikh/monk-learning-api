"""
curation_io.py — export curation inputs / load curated concepts.

Splits the taxonomy job into two halves so the *reasoning* can be done by
whichever model is doing the work (a Claude session, a subagent, or an API
call) while the database writes stay in one validated place.

  export  — writes scratch/curation_input_<subject>.json: every chapter with
            its cleaned Drona subtopics and question-bank tags (with counts).
  load    — reads a drafted scratch/curation_output_<subject>.json and writes
            concepts + concept_aliases, validating every row first.

The validation is the point: aliases must be verbatim strings from that
chapter's own input, so a hallucinated or paraphrased alias fails loudly
instead of silently mapping nothing.

Usage:
  python3 scripts/curation_io.py export chemistry
  python3 scripts/curation_io.py load   chemistry            # dry run
  python3 scripts/curation_io.py load   chemistry --apply
"""

import argparse
import json
import sys
from collections import Counter, defaultdict

sys.path.insert(0, ".")

from app.db import supabase                                   # noqa: E402
from scripts.curate_concepts import norm, clean_subtopics, slugify  # noqa: E402

MIN_CONCEPTS, MAX_CONCEPTS = 8, 16


def export(subject: str):
    chapters = (
        supabase.table("chapters").select("id, name, class_level")
        .ilike("subject", subject).execute().data
    )

    subs_by_chapter = defaultdict(list)
    for off in range(0, 5000, 1000):
        batch = (supabase.table("subtopic_index").select("chapter_id, subtopic")
                 .range(off, off + 999).execute().data)
        if not batch:
            break
        for s in batch:
            subs_by_chapter[s["chapter_id"]].append(s["subtopic"])

    tags_by_norm = defaultdict(Counter)
    for off in range(0, 10000, 1000):
        batch = (supabase.table("questions").select("chapter_name, concept, subject")
                 .ilike("subject", subject).range(off, off + 999).execute().data)
        if not batch:
            break
        for q in batch:
            if q.get("concept") and q.get("chapter_name"):
                tags_by_norm[norm(q["chapter_name"])][q["concept"]] += 1

    out = []
    for ch in sorted(chapters, key=lambda c: (c["class_level"], c["name"])):
        base_subs, variants = clean_subtopics(subs_by_chapter.get(ch["id"], []))
        tags = dict(sorted(tags_by_norm.get(norm(ch["name"]), {}).items(), key=lambda kv: -kv[1]))
        out.append({
            "chapter_id": ch["id"],
            "chapter": ch["name"],
            "class_level": ch["class_level"],
            "subtopics": base_subs,          # cleaned base names
            "subtopic_variants": variants,   # base -> raw rows it expands to
            "question_tags": tags,           # tag -> question count
        })

    path = f"scratch/curation_input_{subject}.json"
    with open(path, "w") as f:
        json.dump(out, f, indent=1, ensure_ascii=False)
    n_subs = sum(len(c["subtopics"]) for c in out)
    n_tags = sum(len(c["question_tags"]) for c in out)
    print(f"{len(out)} chapters | {n_subs} subtopics | {n_tags} question tags -> {path}")


def load(subject: str, apply: bool):
    with open(f"scratch/curation_input_{subject}.json") as f:
        inputs = {c["chapter_id"]: c for c in json.load(f)}
    with open(f"scratch/curation_output_{subject}.json") as f:
        drafted = json.load(f)

    existing = {r["chapter_id"] for r in supabase.table("concepts").select("chapter_id").execute().data}

    problems, to_write = [], []
    for entry in drafted:
        cid = entry.get("chapter_id")
        src = inputs.get(cid)
        if not src:
            problems.append(f"unknown chapter_id {cid}")
            continue
        concepts = entry.get("concepts") or []
        label = f"{src['chapter']} (Class {src['class_level']})"

        if not (MIN_CONCEPTS <= len(concepts) <= MAX_CONCEPTS):
            problems.append(f"{label}: {len(concepts)} concepts (outside {MIN_CONCEPTS}-{MAX_CONCEPTS})")

        valid_subs, valid_tags = set(src["subtopics"]), set(src["question_tags"])
        seen_subs, seen_tags = Counter(), Counter()
        for c in concepts:
            for a in c.get("subtopic_aliases", []):
                if a not in valid_subs:
                    problems.append(f"{label}: subtopic alias not in source: {a!r}")
                seen_subs[a] += 1
            for a in c.get("question_tag_aliases", []):
                if a not in valid_tags:
                    problems.append(f"{label}: question tag alias not in source: {a!r}")
                seen_tags[a] += 1

        # Duplicates are checked PER SOURCE, not across them. A string can
        # legitimately exist both as a Drona subtopic and as a question tag,
        # and those two may belong to different concepts — the subtopic
        # teaches one skill while the tagged questions test another. They
        # become separate rows (the unique key is concept_id+alias+source),
        # so only a repeat within the same source is a real collision.
        for seen, src_name in ((seen_subs, "subtopic"), (seen_tags, "question tag")):
            for a, n in seen.items():
                if n > 1:
                    problems.append(f"{label}: {src_name} alias claimed by {n} concepts: {a!r}")
        for a in sorted(valid_subs - set(seen_subs)):
            problems.append(f"{label}: UNMAPPED subtopic: {a!r}")
        for a in sorted(valid_tags - set(seen_tags)):
            problems.append(f"{label}: UNMAPPED question tag: {a!r}")

        to_write.append((src, concepts))

    if problems:
        print(f"⚠ {len(problems)} validation problem(s):")
        for p in problems[:60]:
            print("   ", p)
        if len(problems) > 60:
            print(f"    … and {len(problems) - 60} more")

    print(f"\n{len(to_write)} chapters ready ({sum(len(c) for _, c in to_write)} concepts).")
    if not apply:
        print("dry run — pass --apply to write.")
        return
    if problems:
        print("refusing to write while validation problems remain.")
        return

    for src, concepts in to_write:
        if src["chapter_id"] in existing:
            print(f"  skip (already curated): {src['chapter']}")
            continue
        rows, used = [], set()
        ordered = sorted(concepts, key=lambda c: c.get("display_order", 99))
        for c in ordered:
            key = slugify(c["name"])
            while key in used:
                key += "-2"
            used.add(key)
            rows.append({
                "chapter_id": src["chapter_id"],
                "name": c["name"].strip(),
                "key": key,
                "exams": c.get("exams") or ["jee", "neet"],
                "display_order": c.get("display_order", 99),
            })
        res = supabase.table("concepts").upsert(rows, on_conflict="chapter_id,key").execute()
        id_by_key = {r["key"]: r["id"] for r in res.data}

        alias_rows = []
        for c, row in zip(ordered, rows):
            concept_id = id_by_key[row["key"]]
            for a in c.get("subtopic_aliases", []):
                for raw in src["subtopic_variants"].get(a, [a]):
                    alias_rows.append({"concept_id": concept_id, "alias": raw, "source": "subtopic"})
            for a in c.get("question_tag_aliases", []):
                alias_rows.append({"concept_id": concept_id, "alias": a, "source": "question_tag"})
        if alias_rows:
            supabase.table("concept_aliases").upsert(
                alias_rows, on_conflict="concept_id,alias,source", ignore_duplicates=True
            ).execute()
        print(f"  ✓ {src['chapter']}: {len(rows)} concepts, {len(alias_rows)} aliases")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["export", "load"])
    ap.add_argument("subject")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    if args.mode == "export":
        export(args.subject)
    else:
        load(args.subject, args.apply)

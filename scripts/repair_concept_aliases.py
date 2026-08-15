"""
repair_concept_aliases.py — map orphaned subtopics/question-tags onto the
already-curated concepts of their chapter.

Exists because 0017 originally made concept_aliases unique on (alias, source)
GLOBALLY, so a tag name shared by two chapters could only map in one of them.
The constraint is now per-concept; this pass fills in what was dropped.

No new concepts are created. Each chapter's unmapped items go to DeepSeek with
that chapter's finished concept list; the model only picks a home for each item.

Usage: python scripts/repair_concept_aliases.py <subject>
"""

import json
import sys
from collections import defaultdict

sys.path.insert(0, ".")

from app.db import supabase                                    # noqa: E402
from app.drona.models import get_drona_client, get_model_name  # noqa: E402
from scripts.curate_concepts import norm, clean_subtopics      # noqa: E402

PROMPT = """Chapter: "{chapter}" ({subject}). Its canonical concept list:
{concepts_json}

Assign each item below to exactly ONE concept from the list (the concept it
teaches/tests most). Copy strings verbatim. Return ONLY JSON:
{{"assignments": [{{"item": "<verbatim item>", "concept": "<verbatim concept name>"}}]}}

Items to assign:
{items_json}"""


def main():
    subject = sys.argv[1] if len(sys.argv) > 1 else "physics"
    client = get_drona_client()
    model = get_model_name("scoping")

    chapters = supabase.table("chapters").select("id, name").ilike("subject", subject).execute().data
    ch_ids = {c["id"] for c in chapters}
    ch_by_norm = {norm(c["name"]): c for c in chapters}

    concepts = supabase.table("concepts").select("id, name, chapter_id").limit(5000).execute().data
    concepts_by_ch = defaultdict(list)
    for c in concepts:
        concepts_by_ch[c["chapter_id"]].append(c)

    aliased = set()
    for off in range(0, 10000, 1000):
        b = supabase.table("concept_aliases").select("alias, source, concept_id").range(off, off + 999).execute().data
        if not b:
            break
        # alias coverage is per chapter now: (chapter_id, alias, source)
        ch_of = {c["id"]: c["chapter_id"] for c in concepts}
        aliased.update((ch_of.get(r["concept_id"]), r["alias"], r["source"]) for r in b)

    # orphaned subtopics (raw names; cleaning maps variants to one base item)
    orphans = defaultdict(lambda: {"subtopic": [], "question_tag": []})
    subs = []
    for off in range(0, 5000, 1000):
        b = supabase.table("subtopic_index").select("chapter_id, subtopic").range(off, off + 999).execute().data
        if not b:
            break
        subs.extend(b)
    for s in subs:
        if s["chapter_id"] in ch_ids and (s["chapter_id"], s["subtopic"], "subtopic") not in aliased:
            orphans[s["chapter_id"]]["subtopic"].append(s["subtopic"])

    # orphaned question tags (chapter matched by normalized name)
    for off in range(0, 10000, 1000):
        b = (
            supabase.table("questions")
            .select("chapter_name, concept, subject")
            .ilike("subject", subject)
            .range(off, off + 999)
            .execute()
            .data
        )
        if not b:
            break
        for q in b:
            ch = ch_by_norm.get(norm(q.get("chapter_name") or ""))
            if ch and q.get("concept") and (ch["id"], q["concept"], "question_tag") not in aliased:
                if q["concept"] not in orphans[ch["id"]]["question_tag"]:
                    orphans[ch["id"]]["question_tag"].append(q["concept"])

    total_fixed = 0
    for ch in chapters:
        o = orphans.get(ch["id"])
        if not o or not (o["subtopic"] or o["question_tag"]):
            continue
        clist = concepts_by_ch[ch["id"]]
        if not clist:
            print(f"  {ch['name']}: no concepts curated yet, skipping")
            continue

        base_subs, variants = clean_subtopics(o["subtopic"])
        items = base_subs + o["question_tag"]
        if not items:
            continue
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": PROMPT.format(
                chapter=ch["name"], subject=subject.capitalize(),
                concepts_json=json.dumps([c["name"] for c in clist], ensure_ascii=False),
                items_json=json.dumps(items, ensure_ascii=False),
            )}],
            response_format={"type": "json_object"},
            temperature=0.1,
            timeout=90,
        )
        data = json.loads(resp.choices[0].message.content)
        cid_by_name = {c["name"]: c["id"] for c in clist}
        rows = []
        for a in data.get("assignments", []):
            cid = cid_by_name.get(a.get("concept"))
            item = a.get("item")
            if not cid or item not in items:
                continue
            if item in variants:  # a cleaned subtopic base → expand to raw rows
                for raw in variants[item]:
                    rows.append({"concept_id": cid, "alias": raw, "source": "subtopic"})
            else:
                rows.append({"concept_id": cid, "alias": item, "source": "question_tag"})
        if rows:
            supabase.table("concept_aliases").upsert(
                rows, on_conflict="concept_id,alias,source", ignore_duplicates=True
            ).execute()
        unassigned = len(items) - len(data.get("assignments", []))
        total_fixed += len(rows)
        print(f"  {ch['name']}: {len(rows)} aliases repaired" + (f" | ⚠ {unassigned} unassigned" if unassigned > 0 else ""))

    print(f"\nTotal aliases repaired: {total_fixed}")


if __name__ == "__main__":
    main()

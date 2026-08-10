"""Generates 20-25 conventional syllabus subtopic headings per chapter.

NAMES ONLY. No lesson plans, no segments, no board content, nothing
pre-computed — just the headings, grounded in each chapter's own content so a
heading only appears if the material actually covers it.

Grounding per chapter: pdf_chunks (primary) + lesson_sections titles + the
subtopics already in subtopic_index.

Uses gpt-4o-mini deliberately, NOT DeepSeek: this is an offline naming utility,
and keeping it off DeepSeek means it cannot contend with a live session or skew
latency measurements. Nothing here writes to the database.

Output:
  /tmp/drona_subtopic_headings.json   machine-readable, for later import
  /tmp/drona_subtopic_headings.md     reviewable by subject and chapter
"""
import json
import os
import re
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from app.db import supabase  # noqa: E402

client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
MODEL = "gpt-4o-mini"
TARGET_MIN, TARGET_MAX = 20, 25
WORKERS = int(os.getenv("SUBTOPIC_WORKERS", "6"))

SYSTEM = """You produce the subtopic list for one chapter of an Indian Class 11-12 syllabus
(JEE / NEET / CBSE boards).

Return ONLY valid JSON: {"subtopics": ["...", "..."]}

Rules:
1. Between 20 and 25 subtopics. No fewer, no more.
2. CONVENTIONAL SYLLABUS HEADINGS — short noun phrases exactly as a textbook
   contents page or syllabus document would print them.
   GOOD: "Resolution of a Vector into Components", "Scalar (Dot) Product",
         "Banking of Roads", "Time of Flight and Range"
   BAD:  "Why vectors can't be added like numbers"  (a question, not a heading)
   BAD:  "The five pitfalls that cost marks"        (narrative, not a heading)
   BAD:  "Vectors"                                  (too broad to teach in 30 min)
3. Never phrase a subtopic as a question. No question marks. No "Why", "How",
   "What" openers. No exam-tip or pitfall framing.
4. Each must be a teachable unit of roughly 25-35 minutes — narrower than the
   chapter, wider than a single formula.
5. Ground every heading in the SOURCE MATERIAL provided. Do not invent topics the
   chapter does not cover, and do not pull in topics belonging to other chapters.
6. Order them the way the chapter teaches them, simplest first.
7. Keep each heading under 70 characters. Title Case. No numbering, no trailing
   punctuation."""


def fetch_paged(table, cols, chapter_id, limit=None):
    out, start = [], 0
    while True:
        q = supabase.table(table).select(cols).eq("chapter_id", chapter_id).range(start, start + 999)
        rows = q.execute().data or []
        out += rows
        if len(rows) < 1000 or (limit and len(out) >= limit):
            break
        start += 1000
    return out[:limit] if limit else out


def build_context(chapter):
    cid = chapter["id"]
    chunks = fetch_paged("pdf_chunks", "content", cid, limit=30)
    sections = fetch_paged("lesson_sections", "title, position, subtopic", cid)
    existing = supabase.table("subtopic_index").select("subtopic").eq("chapter_id", cid).execute().data or []

    parts = [f"CHAPTER: {chapter['name']}  ({(chapter.get('subject') or '').title()}, Class {chapter.get('class_level')})"]
    if existing:
        parts.append("\nSUBTOPICS ALREADY DEFINED (keep these, expand around them):\n" +
                     "\n".join(f"- {e['subtopic']}" for e in existing))
    if sections:
        seen, names = set(), []
        for s in sections:
            sub = (s.get("subtopic") or "").strip()
            if sub and sub not in seen:
                seen.add(sub); names.append(sub)
        if names:
            parts.append("\nSECTION GROUPINGS IN THIS CHAPTER:\n" + "\n".join(f"- {n}" for n in names))
    if chunks:
        body = "\n\n".join((c.get("content") or "")[:700] for c in chunks[:22])
        parts.append("\nSOURCE MATERIAL (textbook chunks):\n" + body[:22000])
    return "\n".join(parts)


CLEAN = re.compile(r"^\s*(?:\d+[\.\)]\s*)?(.*?)[\s.;:]*$")


def normalise(items):
    out, seen = [], set()
    for raw in items:
        if not isinstance(raw, str):
            continue
        name = CLEAN.match(raw).group(1).strip()
        if not name or "?" in name or len(name) > 70:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(name)
    return out


def do_chapter(chapter):
    t0 = time.time()
    try:
        ctx = build_context(chapter)
        res = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "system", "content": SYSTEM},
                      {"role": "user", "content": ctx + f"\n\nProduce {TARGET_MIN}-{TARGET_MAX} subtopic headings."}],
            response_format={"type": "json_object"},
            temperature=0.2,
        )
        names = normalise(json.loads(res.choices[0].message.content).get("subtopics", []))
        status = "ok" if TARGET_MIN <= len(names) <= TARGET_MAX else f"count={len(names)}"
        print(f"  {chapter['name'][:40]:<40} {len(names):>3} headings  {status}  ({time.time()-t0:.0f}s)", flush=True)
        return {"chapter_id": chapter["id"], "chapter": chapter["name"],
                "subject": chapter.get("subject"), "class_level": chapter.get("class_level"),
                "subtopics": names, "status": status}
    except Exception as e:
        print(f"  {chapter['name'][:40]:<40} FAILED  {str(e)[:70]}", flush=True)
        return {"chapter_id": chapter["id"], "chapter": chapter["name"],
                "subject": chapter.get("subject"), "class_level": chapter.get("class_level"),
                "subtopics": [], "status": f"failed: {str(e)[:120]}"}


def main():
    chapters = supabase.table("chapters").select("id,name,subject,class_level").execute().data or []
    chapters.sort(key=lambda c: ((c.get("subject") or ""), c.get("class_level") or 0, c["name"]))
    print(f"generating headings for {len(chapters)} chapters using {MODEL} ({WORKERS} workers)\n", flush=True)

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        results = list(ex.map(do_chapter, chapters))

    with open("/tmp/drona_subtopic_headings.json", "w") as fh:
        json.dump(results, fh, indent=2)

    by_subject = defaultdict(list)
    for r in results:
        by_subject[(r.get("subject") or "other").title()].append(r)

    total = sum(len(r["subtopics"]) for r in results)
    with open("/tmp/drona_subtopic_headings.md", "w") as fh:
        fh.write(f"# Drona subtopic headings\n\n{len(chapters)} chapters · {total} subtopics · "
                 f"names only, nothing pre-computed\n")
        for subject in sorted(by_subject):
            fh.write(f"\n## {subject}\n")
            for r in sorted(by_subject[subject], key=lambda x: (x.get("class_level") or 0, x["chapter"])):
                fh.write(f"\n### {r['chapter']} (Class {r.get('class_level')}) — {len(r['subtopics'])}\n\n")
                for i, s in enumerate(r["subtopics"], 1):
                    fh.write(f"{i}. {s}\n")

    bad = [r for r in results if r["status"] != "ok"]
    print(f"\n{'='*70}")
    print(f"  {len(chapters)} chapters · {total} subtopics · avg {total/max(1,len(chapters)):.1f} per chapter")
    print(f"  outside the 20-25 target or failed: {len(bad)}")
    for r in bad[:12]:
        print(f"    - {r['chapter']}: {r['status']}")
    print(f"\n  /tmp/drona_subtopic_headings.json")
    print(f"  /tmp/drona_subtopic_headings.md")


if __name__ == "__main__":
    main()

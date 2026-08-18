"""
tag_io.py — export untagged questions for concept assignment / load the result.

Same split as curation_io.py: the *reasoning* (which concept does this question
test?) is done by whichever model is doing the work, while validation and the
database write stay in one place.

  export  — writes scratch/tagging_batch_<subject>_<n>.json: batches of roughly
            equal size, each carrying the chapters involved, every concept
            available in those chapters, and the untagged questions with their
            stem text.
  load    — reads scratch/tagging_result_*.json and writes question_concepts
            after validating that each assigned concept actually belongs to
            that question's chapter.

Servable questions (needs_manual IS NULL) come first: those are the ones a
student can actually be served, so they are the ones whose Progress score is
wrong while they stay untagged.

Usage:
  python3 scripts/tag_io.py export biology --batch-size 200
  python3 scripts/tag_io.py load                      # dry run, all results
  python3 scripts/tag_io.py load --apply
"""

import argparse
import glob
import json
import sys
from collections import defaultdict

sys.path.insert(0, ".")

from app.db import supabase                          # noqa: E402
from scripts.curate_concepts import norm             # noqa: E402

STEM_CHARS = 600


def _tagged_ids():
    tagged = set()
    for off in range(0, 20000, 1000):
        b = supabase.table("question_concepts").select("question_id").range(off, off + 999).execute().data
        if not b:
            break
        tagged.update(r["question_id"] for r in b)
    return tagged


def export(subject: str, batch_size: int, include_quarantined: bool):
    chapters = supabase.table("chapters").select("id, name, class_level, subject").ilike("subject", subject).execute().data
    ch_by_norm = {norm(c["name"]): c for c in chapters}
    ch_by_id = {c["id"]: c for c in chapters}

    concepts = []
    for off in range(0, 5000, 1000):
        b = supabase.table("concepts").select("id, chapter_id, name, display_order").range(off, off + 999).execute().data
        if not b:
            break
        concepts.extend(b)
    concepts_by_ch = defaultdict(list)
    for c in concepts:
        if c["chapter_id"] in ch_by_id:
            concepts_by_ch[c["chapter_id"]].append(c)

    tagged = _tagged_ids()

    rows = []
    for off in range(0, 10000, 1000):
        b = (supabase.table("questions")
             .select("id, chapter_name, concept, question_text, options, needs_manual, question_type")
             .ilike("subject", subject).range(off, off + 999).execute().data)
        if not b:
            break
        rows.extend(b)

    work = []
    for q in rows:
        if q["id"] in tagged:
            continue
        if q.get("needs_manual") is not None and not include_quarantined:
            continue
        ch = ch_by_norm.get(norm(q.get("chapter_name") or ""))
        if not ch or not concepts_by_ch.get(ch["id"]):
            continue  # unresolved chapter — handled separately, needs a chapter decision first
        # Options must ship with the stem. Roughly half the bank's stems are
        # bare instructions ("Identify the incorrect statement") whose actual
        # content lives entirely in the options — without them the question is
        # unclassifiable, and the first tagging pass correctly refused ~39% of
        # one batch for exactly this reason.
        entry = {
            "question_id": q["id"],
            "chapter_id": ch["id"],
            "chapter": ch["name"],
            "class_level": ch["class_level"],
            "legacy_tag": q.get("concept"),
            "stem": (q.get("question_text") or "")[:STEM_CHARS],
        }
        opts = q.get("options")
        if opts:
            entry["options"] = {k: str(v)[:200] for k, v in opts.items()} if isinstance(opts, dict) else opts
        work.append(entry)

    work.sort(key=lambda w: (w["class_level"], w["chapter"]))

    batches, cur = [], []
    for w in work:
        cur.append(w)
        if len(cur) >= batch_size:
            batches.append(cur)
            cur = []
    if cur:
        batches.append(cur)

    for i, batch in enumerate(batches, 1):
        ch_ids = {w["chapter_id"] for w in batch}
        payload = {
            "subject": subject,
            "batch": i,
            "chapters": [
                {
                    "chapter_id": cid,
                    "chapter": ch_by_id[cid]["name"],
                    "class_level": ch_by_id[cid]["class_level"],
                    "concepts": [
                        {"concept_id": c["id"], "name": c["name"]}
                        for c in sorted(concepts_by_ch[cid], key=lambda c: c["display_order"])
                    ],
                }
                for cid in sorted(ch_ids, key=lambda c: ch_by_id[c]["name"])
            ],
            "questions": batch,
        }
        path = f"scratch/tagging_batch_{subject}_{i}.json"
        with open(path, "w") as f:
            json.dump(payload, f, indent=1, ensure_ascii=False)
        print(f"  {path}: {len(batch)} questions, {len(ch_ids)} chapters")
    print(f"{subject}: {len(work)} untagged questions -> {len(batches)} batch(es)")


def load(apply: bool):
    concepts = {}
    for off in range(0, 5000, 1000):
        b = supabase.table("concepts").select("id, chapter_id, name").range(off, off + 999).execute().data
        if not b:
            break
        for c in b:
            concepts[c["id"]] = c

    results = sorted(glob.glob("scratch/tagging_result_*.json"))
    if not results:
        print("no scratch/tagging_result_*.json files found")
        return

    all_rows, problems, seen = [], [], set()
    for path in results:
        with open(path) as f:
            data = json.load(f)
        assignments = data.get("assignments") if isinstance(data, dict) else data
        # the batch file that produced this result tells us each question's chapter
        batch_path = path.replace("tagging_result_", "tagging_batch_")
        try:
            with open(batch_path) as f:
                chap_of_q = {q["question_id"]: q["chapter_id"] for q in json.load(f)["questions"]}
        except FileNotFoundError:
            problems.append(f"{path}: no matching batch file {batch_path}")
            continue

        for a in assignments:
            qid, cid = a.get("question_id"), a.get("concept_id")
            if qid in seen:
                problems.append(f"{path}: duplicate assignment for {qid}")
                continue
            seen.add(qid)
            if qid not in chap_of_q:
                problems.append(f"{path}: {qid} not in its batch")
                continue
            c = concepts.get(cid)
            if not c:
                problems.append(f"{path}: unknown concept_id {cid} for {qid}")
                continue
            if c["chapter_id"] != chap_of_q[qid]:
                problems.append(f"{path}: {qid} assigned {c['name']!r} which belongs to a DIFFERENT chapter")
                continue
            all_rows.append({"question_id": qid, "concept_id": cid, "role": "primary"})

    if problems:
        print(f"⚠ {len(problems)} problem(s):")
        for p in problems[:40]:
            print("   ", p)
        if len(problems) > 40:
            print(f"    … and {len(problems)-40} more")

    print(f"\n{len(all_rows)} valid assignments from {len(results)} result file(s).")
    if not apply:
        print("dry run — pass --apply to write.")
        return
    if problems:
        print("refusing to write while problems remain.")
        return
    for i in range(0, len(all_rows), 500):
        supabase.table("question_concepts").upsert(
            all_rows[i:i+500], on_conflict="question_id,concept_id", ignore_duplicates=True
        ).execute()
    print(f"wrote {len(all_rows)} question_concepts rows.")


def retry(batch_size: int):
    """Re-export everything a first pass marked `unassignable`, now WITH the
    options text. Most first-pass refusals were bare-instruction stems whose
    content lives entirely in the options — solvable, not hopeless."""
    qids = []
    for path in sorted(glob.glob("scratch/tagging_result_*.json")):
        with open(path) as f:
            data = json.load(f)
        for u in (data.get("unassignable") or []):
            qids.append(u["question_id"])
    qids = list(dict.fromkeys(qids))
    if not qids:
        print("nothing flagged unassignable")
        return
    print(f"{len(qids)} questions flagged unassignable in pass 1")

    chapters = {c["id"]: c for c in supabase.table("chapters").select("id, name, class_level, subject").execute().data}
    concepts = []
    for off in range(0, 5000, 1000):
        b = supabase.table("concepts").select("id, chapter_id, name, display_order").range(off, off + 999).execute().data
        if not b:
            break
        concepts.extend(b)
    concepts_by_ch = defaultdict(list)
    for c in concepts:
        concepts_by_ch[c["chapter_id"]].append(c)

    rows = []
    for i in range(0, len(qids), 200):
        rows.extend(supabase.table("questions")
                    .select("id, chapter_name, subject, concept, question_text, options")
                    .in_("id", qids[i:i+200]).execute().data)

    ch_by_subj_norm = defaultdict(dict)
    for c in chapters.values():
        ch_by_subj_norm[c["subject"].lower()][norm(c["name"])] = c["id"]

    work = []
    for q in rows:
        cid = ch_by_subj_norm[(q.get("subject") or "").lower()].get(norm(q.get("chapter_name") or ""))
        if not cid or not concepts_by_ch.get(cid):
            continue
        opts = q.get("options")
        work.append({
            "question_id": q["id"], "chapter_id": cid,
            "chapter": chapters[cid]["name"], "subject": q.get("subject"),
            "legacy_tag": q.get("concept"),
            "stem": (q.get("question_text") or "")[:STEM_CHARS],
            "options": ({k: str(v)[:250] for k, v in opts.items()} if isinstance(opts, dict) else opts) if opts else None,
        })

    batches = [work[i:i+batch_size] for i in range(0, len(work), batch_size)]
    for i, batch in enumerate(batches, 1):
        ch_ids = {w["chapter_id"] for w in batch}
        payload = {
            "pass": 2, "batch": i,
            "chapters": [{"chapter_id": cid, "chapter": chapters[cid]["name"],
                          "class_level": chapters[cid]["class_level"],
                          "concepts": [{"concept_id": c["id"], "name": c["name"]}
                                       for c in sorted(concepts_by_ch[cid], key=lambda c: c["display_order"])]}
                         for cid in sorted(ch_ids, key=lambda c: chapters[c]["name"])],
            "questions": batch,
        }
        path = f"scratch/tagging_batch_retry_{i}.json"
        with open(path, "w") as f:
            json.dump(payload, f, indent=1, ensure_ascii=False)
        n_opts = sum(1 for w in batch if w["options"])
        print(f"  {path}: {len(batch)} questions ({n_opts} now have options), {len(ch_ids)} chapters")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["export", "load", "retry"])
    ap.add_argument("subject", nargs="?")
    ap.add_argument("--batch-size", type=int, default=200)
    ap.add_argument("--include-quarantined", action="store_true")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    if args.mode == "export":
        export(args.subject, args.batch_size, args.include_quarantined)
    elif args.mode == "retry":
        retry(args.batch_size)
    else:
        load(args.apply)

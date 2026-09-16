"""Symptom scan over every stored doubt — the bug classes that actually shipped.

Every bug this audit hunts was found in production first: SMILES quoted as a
final answer, a phantom "null" key withholding a correct derivation, section
headings read as questions, sub-parts split into fragments, duplicate options,
answers gone empty. Run it after a pipeline change, or on a schedule; a bucket
growing again means a rule leaked.

    python3 scripts/audit_doubts.py
"""
import re
import sys

sys.path.insert(0, ".")
from app.db import supabase  # noqa: E402

SMILES = "<smiles>"
LATEX_UNRENDERED = re.compile(r"\\begin\{|\\pu\{")  # \mathrm/\ce verified handled by the app
ANSKEY_IN_STEM = re.compile(r"(?:^|\n)\W{0,2}(?:ans(?:wer)?s?|soln?)\s*[.:\-–—]", re.I)
HEADING = re.compile(r"^\s*(?:[IVX]+\.|SECTION\b)", re.I)
FRAGMENT = re.compile(r"^\s*\(?(?:i{1,3}|iv|v|[a-d])\)")
PHANTOM_NULL = re.compile(r"[\"“']null[\"”']", re.I)


def fetch_all():
    rows, start = [], 0
    while True:
        page = (supabase.table("doubts")
                .select("id, question_text, stem, answer, status, solved, "
                        "failure_reason, question_type, option_labels, options, "
                        "steps, key_idea, legible, question_image, created_at")
                .order("created_at", desc=True).range(start, start + 199).execute().data)
        rows.extend(page)
        if len(page) < 200:
            return rows
        start += 200


def main() -> int:
    rows = fetch_all()
    buckets = {}

    def hit(name, r, detail=""):
        buckets.setdefault(name, []).append((r["id"][:8], r["created_at"][:10], detail[:70]))

    for r in rows:
        ans = r.get("answer") or ""
        opts = [o for o in (r.get("options") or []) if isinstance(o, dict)]
        step_texts = [(st.get("text") or "") for st in (r.get("steps") or [])
                      if isinstance(st, dict)]
        all_texts = [ans, r.get("key_idea") or ""] + step_texts

        if SMILES in ans:
            hit("smiles_in_answer", r, ans)
        if any(SMILES in t for t in step_texts):
            hit("smiles_in_steps", r)
        if any(LATEX_UNRENDERED.search(t) for t in all_texts):
            hit("unrenderable_latex", r)
        if r.get("solved") and not ans.strip():
            hit("solved_empty_answer", r)
        if r.get("status") == "unsure" and PHANTOM_NULL.search(r.get("failure_reason") or ""):
            hit("phantom_null_unsure", r)
        if ANSKEY_IN_STEM.search(r.get("stem") or r.get("question_text") or ""):
            hit("answer_key_in_stem", r)
        texts = [(o.get("text") or "").strip() for o in opts]
        if len(texts) != len(set(texts)) and any(texts):
            hit("duplicate_options", r)
        if (r.get("question_type") == "single_correct" and r.get("solved")
                and not (r.get("option_labels") or [])):
            hit("solved_mcq_no_label", r, ans)
        qt = r.get("question_text") or ""
        if HEADING.match(qt):
            hit("heading_as_question", r, qt)
        if FRAGMENT.match(qt):
            hit("subpart_fragment", r, qt)
        if not r.get("legible") and r.get("solved"):
            hit("illegible_but_solved", r)
        if r.get("solved") and not (r.get("steps") or []):
            hit("solved_no_steps", r)

    print(f"audited {len(rows)} doubts")
    for name in sorted(buckets):
        print(f"\n{name}: {len(buckets[name])}")
        for item in buckets[name][:5]:
            print("   ", item)
    crops = sum(1 for r in rows if r.get("question_image"))
    print(f"\ncrop coverage: {crops}/{len(rows)}")
    return 1 if buckets else 0


if __name__ == "__main__":
    raise SystemExit(main())

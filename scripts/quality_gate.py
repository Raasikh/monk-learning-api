"""Ingest quality gate for the questions table.

Runs every candidate row through the pipeline that the 2026-08-15 full-bank
audit proved out (see EXTRACTION_QUALITY_SPEC.md):

  lint   — structural reject-at-sight checks, no LLM
  blind  — solver sees stem+options ONLY and answers (never the key)
  defend — second pass is SHOWN the key and asked to defend it
  key ships only when blind and defend name the same answer
  sol    — solution regenerated to derive the verified key, then an
           independent honesty check (VALID / HANDWAVE / CONTRADICTS)

Nothing is written on one model's opinion: on numerical disputes a single
strong model was wrong 62% of the time in the audit.

Usage:
  python3 scripts/quality_gate.py --where "source=eq.batch_2026_08"        # dry run
  python3 scripts/quality_gate.py --ids /path/ids.json                     # explicit ids
  python3 scripts/quality_gate.py --where "..." --apply                    # write results

--apply does, per row:
  PASS  -> needs_manual=NULL, solution replaced with the verified derivation
  FAIL  -> needs_manual=<reason>   (row stays/becomes unservable)

Resumable: verdicts append to gate_results.jsonl next to this script; rows
already judged are skipped on re-run. Delete that file to re-judge.
"""
import argparse
import asyncio
import collections
import json
import os
import re
import sys

import requests
from dotenv import load_dotenv

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
load_dotenv(os.path.join(REPO, '.env'))
load_dotenv('/Users/raasikhnaveed/Desktop/dronav1project/.env')

from app.drona.models import get_drona_async_client  # noqa: E402

U = (os.getenv('SUPABASE_URL') or 'https://tgbknrmnjwiokraddurx.supabase.co').rstrip('/')
K = (os.getenv('SUPABASE_SECRET_KEY') or '').strip('"\'')
H = {'apikey': K, 'Authorization': f'Bearer {K}'}
HW = {**H, 'Content-Type': 'application/json', 'Prefer': 'return=minimal'}

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'gate_results.jsonl')
MODEL = "deepseek-v4-pro"
CONCURRENCY = 12
COLS = ('id,question_text,question_type,options,correct_option,correct_value,'
        'value_tolerance,solution,chapter_name,needs_manual,source')

# ---------------------------------------------------------------- lint ----

META_TEXT = re.compile(r"the trap|students fixate|explanation\s*:|the answer is|correct answer", re.I)
FIGURE_REF = re.compile(r"\b(figure|graph shown|following table|diagram|shown below|given curve)\b", re.I)

def lint(q):
    """Structural reject-at-sight. Returns a reason string or None."""
    text = (q.get('question_text') or '').strip()
    if len(text) < 20:
        return 'stem_too_short'
    if re.search(r"\(\s*\)\s*\d", text) or re.search(r"[,\s]\+\s*\+\s*=", text):
        return 'broken_extraction'
    singles = re.findall(r"(?<![\w])[a-zA-Z](?![\w])", text)
    if len(singles) >= 8 and len(text) < 400:
        return 'broken_extraction'
    if FIGURE_REF.search(text) and not q.get('options'):
        # figure-dependent numerical with no figure extracted
        return 'missing_diagram'
    for frag in (text, json.dumps(q.get('options') or {})):
        if frag.count('$') % 2 == 1:
            return 'unrenderable_latex'
    opts = q.get('options')
    if q.get('question_type') == 'single_correct':
        if not isinstance(opts, dict):
            return 'options_destroyed'
        vals = [str(v).strip() for v in opts.values() if str(v).strip()]
        if len(vals) < 4:
            return 'options_destroyed'
        norm = [re.sub(r'\W+', '', v.lower()) for v in vals]
        if len(set(norm)) < len(norm):
            return 'options_destroyed'
        if any(META_TEXT.search(v) for v in vals):
            return 'options_destroyed'
        if not q.get('correct_option'):
            return 'answer_solution_mismatch'
    if q.get('question_type') == 'numerical' and q.get('correct_value') is None:
        return 'nvq_answer_missing'
    return None

# ---------------------------------------------------------------- LLM ----

BLIND_MCQ = """You are an expert JEE/NEET examiner. Solve the question yourself, from first principles. You are NOT given an answer key.

If the item is too garbled, truncated, or internally inconsistent to answer reliably, do NOT guess — report UNREADABLE.

Answer immediately and concisely.
Return ONLY JSON: {"answer":"A"|"B"|"C"|"D"|"UNREADABLE","why":"<= 20 words"}"""

BLIND_NUM = """You are an expert JEE/NEET examiner. Solve this numerical question yourself. You are NOT given the answer. Honour any rounding or unit convention the stem states.

If you cannot solve it reliably, report UNREADABLE — never guess.
Return ONLY JSON: {"value":<number> or null,"status":"SOLVED"|"UNREADABLE","why":"<= 20 words"}"""

DEFEND = """You are a meticulous JEE/NEET answer-key checker. You are shown a question, its options (if any), and the stored answer key. Decide whether that key is defensible.

Be conservative: VALID if the key is defensible under any standard reading. WRONG only when clearly, demonstrably incorrect. UNREADABLE if the item is too corrupted to judge.
Return ONLY JSON: {"verdict":"VALID"|"WRONG"|"UNREADABLE","why":"<= 20 words"}"""

WRITE_SOL = """You write worked solutions for JEE/NEET questions. You are given a question and its VERIFIED correct answer. Derive it honestly, step by step.

NEVER write filler like "consider the possibility of additional constraints" or "confirming that option X is correct". If your derivation does not reach the stated answer, say so in "problem" instead of fudging it.

3-6 steps, each one sentence starting "Step N: ", plain speakable text, no LaTeX, no $.
Return ONLY JSON: {"steps":["Step 1: ...", ...],"reaches":"<the answer your steps arrive at>","problem":""}"""

CHECK_SOL = """You are checking a worked solution for internal honesty. Decide:
VALID — the steps genuinely derive the stated answer.
HANDWAVE — the steps assert or assume the answer rather than deriving it.
CONTRADICTS — the steps actually derive a DIFFERENT answer.
Return ONLY JSON: {"verdict":"VALID"|"HANDWAVE"|"CONTRADICTS","why":"<= 20 words"}"""


async def ask(client, system, user):
    """One JSON call with the empty-object/truncation retry the audit needed."""
    for no_think in (False, True):
        kw = {'extra_body': {"thinking": {"type": "disabled"}}} if no_think else {}
        try:
            r = await client.chat.completions.create(
                model=MODEL,
                messages=[{"role": "system", "content": system},
                          {"role": "user", "content": user}],
                response_format={"type": "json_object"},
                temperature=0.0, max_tokens=3000, timeout=180.0, **kw)
            try:
                d = json.loads(r.choices[0].message.content or "")
            except Exception:
                d = {}
            if d:
                return d
        except Exception as e:
            last = str(e)[:100]
    return {"error": locals().get('last', 'empty response')}


def stem_block(q):
    opts = q.get('options')
    s = f"Question:\n{q.get('question_text')}"
    if isinstance(opts, dict) and opts:
        s += "\n\nOptions:\n" + "\n".join(f"{k}. {v}" for k, v in sorted(opts.items()))
    return s


def values_match(got, key, tolerance):
    try:
        got, key = float(got), float(key)
    except (TypeError, ValueError):
        return False
    if tolerance is not None and float(tolerance) > 0:
        return abs(got - key) <= float(tolerance)
    tol = max(1e-6, abs(key) * 0.005)
    if 200 <= abs(key) < 1e6 and key.is_integer():
        tol = min(tol, 0.5)
    return abs(got - key) <= tol


async def gate_one(client, sem, q, lock):
    async with sem:
        rec = {"id": q['id'], "type": q.get('question_type')}

        reason = lint(q)
        if reason:
            rec.update({"stage": "lint", "pass": False, "reason": reason})
            return await _emit(rec, lock)

        is_num = q.get('question_type') == 'numerical'
        key = q.get('correct_value') if is_num else (q.get('correct_option') or '').strip().upper()

        # 1. blind solve
        b = await ask(client, BLIND_NUM if is_num else BLIND_MCQ, stem_block(q))
        if is_num:
            blind_ok = b.get('status') == 'SOLVED' and values_match(b.get('value'), key, q.get('value_tolerance'))
            unread = b.get('status') == 'UNREADABLE'
        else:
            blind_ok = (str(b.get('answer') or '').strip().upper() == key)
            unread = b.get('answer') == 'UNREADABLE'
        if unread:
            rec.update({"stage": "blind", "pass": False, "reason": "audit_unreadable_stem", "why": b.get('why')})
            return await _emit(rec, lock)

        # 2. adversarial defence
        d = await ask(client, DEFEND, stem_block(q) + f"\n\nStored answer key: {key}")
        defend_ok = d.get('verdict') == 'VALID'

        if not (blind_ok and defend_ok):
            rec.update({"stage": "key", "pass": False, "reason": "audit_wrong_key",
                        "blind": b.get('answer', b.get('value')), "defend": d.get('verdict'),
                        "why": d.get('why') or b.get('why')})
            return await _emit(rec, lock)

        # 3. honest solution
        w = await ask(client, WRITE_SOL, stem_block(q) + f"\n\nVerified correct answer: {key}")
        steps = w.get('steps') or []
        # The writer often answers "B. Zygotene" rather than the bare letter —
        # compare on the leading option letter, not the literal string.
        reaches = str(w.get('reaches') or '').strip().upper()
        m = re.match(r'^([A-D])\b', reaches)
        reaches_letter = m.group(1) if m else reaches
        if not steps or w.get('problem') or (not is_num and reaches_letter != key):
            rec.update({"stage": "solution", "pass": False, "reason": "audit_bad_solution",
                        "why": w.get('problem') or f"writer reached {reaches or '?'}"})
            return await _emit(rec, lock)
        c = await ask(client, CHECK_SOL,
                      stem_block(q) + f"\n\nStated answer: {key}\n\nProposed solution:\n" + "\n".join(steps))
        if c.get('verdict') != 'VALID':
            rec.update({"stage": "solution", "pass": False, "reason": "audit_bad_solution",
                        "why": f"check={c.get('verdict')}: {c.get('why')}"})
            return await _emit(rec, lock)

        rec.update({"stage": "done", "pass": True, "steps": steps})
        return await _emit(rec, lock)


async def _emit(rec, lock):
    async with lock:
        with open(OUT, 'a') as f:
            f.write(json.dumps(rec, default=str) + "\n")
    return rec


# ---------------------------------------------------------------- io ----

def fetch(where=None, ids=None):
    rows = []
    if ids:
        for i in range(0, len(ids), 100):
            r = requests.get(U + '/rest/v1/questions', headers=H,
                             params={'select': COLS, 'id': 'in.(' + ','.join(ids[i:i+100]) + ')'})
            rows.extend(r.json())
        return rows
    step, off = 1000, 0
    fkey, _, fval = (where or '').partition('=')
    while True:
        params = {'select': COLS}
        if fkey:
            params[fkey] = fval
        r = requests.get(U + '/rest/v1/questions', headers={**H, 'Range': f'{off}-{off+step-1}'}, params=params)
        b = r.json()
        rows.extend(b)
        if len(b) < step:
            break
        off += step
    return rows


def already_done():
    if not os.path.exists(OUT):
        return {}
    done = {}
    for line in open(OUT):
        try:
            r = json.loads(line)
            done[r['id']] = r
        except Exception:
            pass
    return done


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--where', help='PostgREST filter, e.g. source=eq.batch_2026_08')
    ap.add_argument('--ids', help='JSON file containing a list of question ids')
    ap.add_argument('--apply', action='store_true')
    args = ap.parse_args()
    if not args.where and not args.ids:
        ap.error('need --where or --ids')

    ids = json.load(open(args.ids)) if args.ids else None
    rows = fetch(args.where, ids)
    done = already_done()
    todo = [q for q in rows if q['id'] not in done]
    print(f"candidates={len(rows)} judged_previously={len(done)} to_judge={len(todo)}", flush=True)

    client = get_drona_async_client()
    sem, lock = asyncio.Semaphore(CONCURRENCY), asyncio.Lock()
    n = 0
    for fut in asyncio.as_completed([gate_one(client, sem, q, lock) for q in todo]):
        r = await fut
        done[r['id']] = r
        n += 1
        if n % 100 == 0:
            print(f"  ... {n}/{len(todo)}", flush=True)

    verdicts = [done[q['id']] for q in rows if q['id'] in done]
    passed = [r for r in verdicts if r.get('pass')]
    failed = [r for r in verdicts if not r.get('pass')]
    print(f"\nPASS {len(passed)}  FAIL {len(failed)}")
    print("fail reasons:", dict(collections.Counter(r.get('reason') for r in failed).most_common()))

    if not args.apply:
        print("\nDRY RUN — nothing written. Re-run with --apply.")
        return

    n_ok = n_bad = 0
    for r in passed:
        resp = requests.patch(U + '/rest/v1/questions', headers=HW, params={'id': f"eq.{r['id']}"},
                              data=json.dumps({"solution": {"steps": r['steps']}, "needs_manual": None}))
        n_ok += resp.status_code in (200, 204)
    by_reason = collections.defaultdict(list)
    for r in failed:
        by_reason[r.get('reason') or 'audit_remove_verdict'].append(r['id'])
    for reason, idlist in by_reason.items():
        for i in range(0, len(idlist), 100):
            resp = requests.patch(U + '/rest/v1/questions', headers=HW,
                                  params={'id': 'in.(' + ','.join(idlist[i:i+100]) + ')'},
                                  data=json.dumps({"needs_manual": reason}))
            n_bad += (resp.status_code in (200, 204)) * len(idlist[i:i+100])
    print(f"APPLIED: {n_ok} rows passed and serving with verified solutions; {n_bad} rows tagged needs_manual")


if __name__ == '__main__':
    asyncio.run(main())

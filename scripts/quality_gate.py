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
import sqlite3
import sys
import time

import requests
from dotenv import load_dotenv

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
load_dotenv(os.path.join(REPO, '.env'))
load_dotenv('/Users/raasikhnaveed/Desktop/dronav1project/.env')

from app.drona.models import get_drona_async_client  # noqa: E402
from app.drona.usage import record_call  # noqa: E402
from openai import AsyncOpenAI  # noqa: E402

U = (os.getenv('SUPABASE_URL') or 'https://tgbknrmnjwiokraddurx.supabase.co').rstrip('/')
K = (os.getenv('SUPABASE_SECRET_KEY') or '').strip('"\'')
H = {'apikey': K, 'Authorization': f'Bearer {K}'}
HW = {**H, 'Content-Type': 'application/json', 'Prefer': 'return=minimal'}

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'gate_results.jsonl')
# Overridable so the gate can run on a cheap tier. Note the tradeoff the spec
# itself measured: on NUMERICAL disputes a strong model was wrong 62% of the
# time, which is why two passes exist at all. MCQ items are far more forgiving
# because the options constrain the answer space; numerical items have nothing
# to collide with, which is why their key error rate was 2.7x higher.
# QUALITY_GATE_MODEL sets the default tier; QUALITY_GATE_MODEL_DISPUTE is used
# only to re-judge items the two passes disagreed on, so the expensive tier is
# billed on the small disputed subset rather than the whole batch.
MODEL = os.getenv("QUALITY_GATE_MODEL", "deepseek-v4-flash")
MODEL_DISPUTE = os.getenv("QUALITY_GATE_MODEL_DISPUTE", MODEL)
# QUALITY_GATE_PROVIDER=openrouter switches BOTH ask() and the dispute
# escalation onto OpenRouter (any model slug in QUALITY_GATE_MODEL /
# QUALITY_GATE_MODEL_DISPUTE, e.g. "stealth/ox-alpha") instead of DeepSeek.
# Kept as a separate switch rather than overloading get_drona_async_client()
# so the tutor's own model plumbing is untouched.
PROVIDER = os.getenv("QUALITY_GATE_PROVIDER", "deepseek")
OPENROUTER_KEY = (os.getenv("OPENROUTER_API_KEY") or "").strip('"\'')


def get_client():
    if PROVIDER == "openrouter":
        if not OPENROUTER_KEY:
            raise RuntimeError("QUALITY_GATE_PROVIDER=openrouter but OPENROUTER_API_KEY is not set")
        return AsyncOpenAI(api_key=OPENROUTER_KEY, base_url="https://openrouter.ai/api/v1",
                            timeout=180.0, max_retries=0)
    return get_drona_async_client()
# llm_calls accounting needs the Supabase key. A --staging run on a machine
# without it must not print one ERROR per model call trying to record; say so
# once and skip recording instead.
RECORD_CALLS = bool(K)
if not RECORD_CALLS:
    print("NOTE: llm_calls recording disabled - SUPABASE_SECRET_KEY is not set",
          file=sys.stderr)
CONCURRENCY = int(os.getenv("QUALITY_GATE_CONCURRENCY", "12"))
COLS = ('id,question_text,question_type,options,correct_option,correct_value,'
        'value_tolerance,solution,chapter_name,needs_manual,source')

# ---------------------------------------------------------------- lint ----

META_TEXT = re.compile(r"the trap|students fixate|explanation\s*:|the answer is|correct answer", re.I)
FOLLOWING_REF = re.compile(r"(?:of|among|from)\s+the\s+following", re.I)
FIGURE_REF = re.compile(r"\b(figure|graph shown|following table|diagram|shown below|given curve)\b", re.I)

def lint(q):
    """Structural reject-at-sight. Returns a reason string or None."""
    text = (q.get('question_text') or '').strip()
    if q.get('question_type') == 'multi_correct':
        # The blind/defend prompts answer with a single letter, so judging a
        # multi-label key ("A,B,D") through them can only produce false
        # disagreement. Routed out before any model call until the gate grows
        # multi-answer prompts; the extraction-side gates have already checked
        # every named label exists among the printed options.
        return 'multi_correct_unjudged'
    if len(text) < 20:
        # Completion stems are legitimately tiny - "Sponges exhibit",
        # "Notochord is" - and answerable when four real options follow.
        # Verified: 3 of 4 stem_too_short failures were exactly this. Short
        # only rejects when the options cannot carry the question either.
        opts = q.get('options') or {}
        real = [v for v in opts.values() if str(v or '').strip()]
        if len(real) < 4:
            return 'stem_too_short'
    if re.search(r"\(\s*\)\s*\d", text) or re.search(r"[,\s]\+\s*\+\s*=", text):
        return 'broken_extraction'
    # Scramble singles - counted on MATH-STRIPPED text only. Adversarially
    # verified triage of the 2026-08-15 sample: this check produced 55 false
    # positives and 0 true ones, because the "isolated single letters" were
    # $..$ math variables, \mathbf letter-spacing (A g I), electron configs,
    # unit vectors, list labels and the article "a" - two rows crossed the
    # threshold on articles alone. Real scramble shows marooned letters in
    # PROSE, so math spans are removed first, the article/list letters a/A/I
    # are ignored, and at least 5 DISTINCT letters are required (scramble is
    # diverse; repeated unit letters are not).
    nomath = re.sub(r"\$\$.*?\$\$|\$[^$]*\$", " ", text, flags=re.S)
    singles = [s for s in re.findall(r"(?<![\w\\])[a-zA-Z](?![\w])", nomath)
               if s not in ('a', 'A', 'I')]
    if len(singles) >= 8 and len(set(s.lower() for s in singles)) >= 5 and len(nomath) < 400:
        return 'broken_extraction'
    if FIGURE_REF.search(text) and not q.get('options'):
        # figure-dependent numerical with no figure extracted
        return 'missing_diagram'
    # A row whose stem needs a figure, or whose options are image-only blanks,
    # cannot be judged by a text-only gate at all - blind solve fails it as
    # unreadable and burns two model calls first (17 rows in the verified
    # sample, the single largest REAL defect class). Routed out here instead.
    if q.get('has_figure'):
        opts = q.get('options') or {}
        blank = [k for k, v in opts.items() if not str(v or '').strip()]
        if FIGURE_REF.search(text) or blank:
            return 'figure_dependent'
        # A figure in the STEM region carrying an "of the following" reference:
        # the list/set the question asks about lives in the image. 3,748 batch2
        # rows failed audit_wrong_key on exactly this shape - the defender kept
        # saying "compound list is corrupted/missing" about chemistry stems
        # whose compounds are drawn, not written. No deixis word appears, so the
        # FIGURE_REF route above never fired.
        if q.get('has_stem_figure') and FOLLOWING_REF.search(text):
            return 'figure_dependent'
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
        # \W+ stripped every operator, so log(m+n) and log(m-n) normalised to
        # the same string and 8 verified-distinct option sets were failed as
        # duplicates. Sign, comparison, arrows and grouping survive; only
        # whitespace and decorative punctuation are dropped.
        norm = [re.sub(r'[^\w+\-<>=/()^→√]', '', v.lower()) for v in vals]
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

A pure recall question (a textbook classification, constant, or named fact) has
nothing to derive: for those, correctly STATING the standard fact and matching
it to the answer IS a valid solution — do not demand a derivation that cannot
exist, and do not substitute your own recollection of the fact for the
solution's unless the solution is unambiguously wrong.
Return ONLY JSON: {"verdict":"VALID"|"HANDWAVE"|"CONTRADICTS","why":"<= 20 words"}"""


async def ask(client, system, user, model=None, service="gate", ref=None):
    """One JSON call with the empty-object/truncation retry the audit needed.

    Every attempt is recorded to `llm_calls` — including the ones whose result
    was discarded (exceptions, empty JSON), which billed and were invisible
    before. `ref` (the question id) lands in subtopic_key so spend is
    attributable per row. Recording runs off the event loop and never raises.
    """
    mdl = model or MODEL
    # OpenRouter's shared free pool 429s under load (observed directly against
    # stealth/ox-alpha), which the DeepSeek path never needed to handle — that
    # provider is billed capacity, not a shared queue. `thinking: disabled` is
    # a DeepSeek-specific field; sending it to another provider risks an
    # unknown-param rejection, so it's only ever attached on that provider.
    is_openrouter = PROVIDER == "openrouter"
    attempts = [(False, 0)] if not is_openrouter else [(False, 0), (False, 3), (False, 8), (False, 15), (False, 25)]
    if not is_openrouter:
        attempts = [(False, 0), (True, 0)]
    for attempt, (no_think, backoff) in enumerate(attempts, start=1):
        if backoff:
            await asyncio.sleep(backoff)
        kw = {'extra_body': {"thinking": {"type": "disabled"}}} if no_think else {}
        t0 = time.monotonic()
        try:
            r = await client.chat.completions.create(
                model=mdl,
                messages=[{"role": "system", "content": system},
                          {"role": "user", "content": user}],
                response_format={"type": "json_object"},
                temperature=0.0, max_tokens=3000, timeout=180.0, **kw)
        except Exception as e:
            last = str(e)[:100]
            if RECORD_CALLS:
                await asyncio.to_thread(
                    record_call, mdl, service, ok=False, attempt=attempt,
                    latency_ms=int((time.monotonic() - t0) * 1000),
                    subtopic_key=ref, error=str(e))
            # A non-429 failure on OpenRouter (bad request, auth, etc.) will
            # not be fixed by waiting and retrying the same call five times.
            if is_openrouter and '429' not in str(e) and 'rate' not in str(e).lower():
                break
            continue
        try:
            d = json.loads(r.choices[0].message.content or "")
        except Exception:
            d = {}
        # ok=False here means "billed but the result was discarded" — the
        # empty-object/truncation case this function's retry exists for.
        if RECORD_CALLS:
            await asyncio.to_thread(
                record_call, mdl, service, ok=bool(d), attempt=attempt, res=r,
                latency_ms=int((time.monotonic() - t0) * 1000),
                subtopic_key=ref, error=None if d else "empty or unparseable JSON")
        if d:
            return d
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


async def _finish_solution(client, q, rec, lock, key, is_num):
    """Stage 3 only: write an honest solution and check it.

    Shared by the normal path and the print-adjudicated path, so a key verified
    against the page still gets exactly the same solution scrutiny.
    """
    # 3. honest solution
    w = await ask(client, WRITE_SOL, stem_block(q) + f"\n\nVerified correct answer: {key}",
                  service="gate_write_sol", ref=q['id'])
    steps = w.get('steps') or []
    # The writer names its destination however it likes: "B. Zygotene",
    # "0.044", "120 V", "3100 Å, option D". The old leading-letter regex
    # matched none of the value forms, compared the raw string against a
    # one-letter key, and failed 31 rows whose keys had ALREADY passed
    # blind AND defend - the largest single false-positive source after
    # the scramble lint. Resolution order: leading letter, then
    # "option X" anywhere, then the value matched against the keyed
    # option's own text (numeric-aware).
    reaches = str(w.get('reaches') or '').strip().upper()
    m = re.match(r'^([A-D])\b', reaches) or re.search(r'\bOPTION\s+([A-D])\b', reaches)
    reaches_letter = m.group(1) if m else None
    if reaches_letter is None and not is_num and isinstance(q.get('options'), dict):
        keyed_text = str(q['options'].get(key) or '').strip().upper()
        if keyed_text:
            norm = lambda s: re.sub(r'[\s$\\{}]', '', s)
            if norm(reaches) and (norm(reaches) == norm(keyed_text)
                                  or norm(reaches) in norm(keyed_text)
                                  or norm(keyed_text) in norm(reaches)):
                reaches_letter = key
            else:
                try:  # "0.044" vs "$0.044$" / "0.0444"
                    if values_match(float(re.sub(r'[^\d.eE+-]', '', reaches) or 'x'),
                                    float(re.sub(r'[^\d.eE+-]', '', keyed_text) or 'x'), None):
                        reaches_letter = key
                except (TypeError, ValueError):
                    pass
    if reaches_letter is None:
        reaches_letter = reaches
    if not steps or w.get('problem') or (not is_num and reaches_letter != key):
        rec.update({"stage": "solution", "pass": False, "reason": "audit_bad_solution",
                    "why": w.get('problem') or f"writer reached {reaches or '?'}"})
        return await _emit(rec, lock)
    c = await ask(client, CHECK_SOL,
                  stem_block(q) + f"\n\nStated answer: {key}\n\nProposed solution:\n" + "\n".join(steps),
                  service="gate_check_sol", ref=q['id'])
    if c.get('verdict') != 'VALID':
        rec.update({"stage": "solution", "pass": False, "reason": "audit_bad_solution",
                    "why": f"check={c.get('verdict')}: {c.get('why')}"})
        return await _emit(rec, lock)

    rec.update({"stage": "done", "pass": True, "steps": steps})
    return await _emit(rec, lock)


async def gate_one(client, sem, q, lock):
    async with sem:
        rec = {"id": q['id'], "type": q.get('question_type')}

        reason = lint(q)
        if reason:
            rec.update({"stage": "lint", "pass": False, "reason": reason})
            return await _emit(rec, lock)

        is_num = q.get('question_type') == 'numerical'
        key = q.get('correct_value') if is_num else (q.get('correct_option') or '').strip().upper()

        # A key verified against the printed page outranks a blind solve, so the
        # key stages are skipped rather than re-run. Measured on the 2026-08-17
        # adjudication: of 534 rows this gate had failed as wrong_key/disputed,
        # 468 (87.6%) matched their printed key exactly - the model was failing
        # hard JEE Advanced problems, not catching bad keys. Two independent
        # readers over the same slices agreed 89/89 on servable-vs-held, so the
        # print reading is reproducible in a way the blind solve was not.
        # Re-asking the model that already got these wrong would just re-fail
        # them and bill for it; the solution stage below still runs in full.
        if q.get('adjudication_verdict') == 'PRINT_CONFIRMS':
            b = {"answer": key, "value": key, "why": "print-adjudicated"}
            blind_ok = defend_ok = True
            d = {"verdict": "VALID", "why": "key verified against printed page"}
            rec["key_stage"] = "skipped_print_adjudicated"
            return await _finish_solution(client, q, rec, lock, key, is_num)

        # 1. blind solve
        b = await ask(client, BLIND_NUM if is_num else BLIND_MCQ, stem_block(q),
                      service="gate_blind", ref=q['id'])
        if is_num:
            blind_ok = b.get('status') == 'SOLVED' and values_match(b.get('value'), key, q.get('value_tolerance'))
            unread = b.get('status') == 'UNREADABLE'
        else:
            blind_ok = (str(b.get('answer') or '').strip().upper() == key)
            unread = b.get('answer') == 'UNREADABLE'
        if unread and MODEL_DISPUTE != MODEL:
            # One refusal on the cheap tier is not evidence the stem is broken:
            # a verified case called a well-posed flux question "ambiguous"
            # while the printed key was confirmable by geometry. One retry on
            # the dispute tier before quarantining.
            b = await ask(client, BLIND_NUM if is_num else BLIND_MCQ, stem_block(q),
                          model=MODEL_DISPUTE, service="gate_blind_dispute", ref=q['id'])
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
        d = await ask(client, DEFEND, stem_block(q) + f"\n\nStored answer key: {key}",
                      service="gate_defend", ref=q['id'])
        defend_ok = d.get('verdict') == 'VALID'

        if defend_ok and not blind_ok:
            # The two passes disagree: the defender (who saw the key) endorses
            # it, the blind solver names something else. In the verified sample
            # every such row had a correct key and a WRONG blind answer - the
            # solver mis-solved, or the item needs a figure the text never
            # carried. Disagreement is settled by a fresh blind attempt on the
            # dispute tier, not by letting the weaker pass veto: agree -> the
            # key stands; still apart -> quarantine as DISPUTED, distinct from
            # audit_wrong_key, because "two passes disagree" is a triage state,
            # not a finding that the key is wrong.
            b2 = await ask(client, BLIND_NUM if is_num else BLIND_MCQ, stem_block(q),
                           model=MODEL_DISPUTE, service="gate_blind_dispute", ref=q['id'])
            if is_num:
                blind_ok = b2.get('status') == 'SOLVED' and values_match(b2.get('value'), key, q.get('value_tolerance'))
            else:
                blind_ok = (str(b2.get('answer') or '').strip().upper() == key)
            if not blind_ok:
                rec.update({"stage": "key", "pass": False, "reason": "audit_key_disputed",
                            "blind": b.get('answer', b.get('value')),
                            "blind_retry": b2.get('answer', b2.get('value')),
                            "defend": d.get('verdict'), "why": b2.get('why') or b.get('why')})
                return await _emit(rec, lock)

        if not (blind_ok and defend_ok):
            rec.update({"stage": "key", "pass": False, "reason": "audit_wrong_key",
                        "blind": b.get('answer', b.get('value')), "defend": d.get('verdict'),
                        "why": d.get('why') or b.get('why')})
            return await _emit(rec, lock)

        return await _finish_solution(client, q, rec, lock, key, is_num)


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


LETTERS = "ABCDEFGH"


def _relabel(options, correct_option):
    """Staging keeps the labels the PAPER printed; this gate assumes A-D.

    Papers are split between "1..4" and "A..D", so feeding staging rows in raw
    would have the blind solver answer "B" against a stored key of "3" and score
    every such row as a disagreement. Relabelled by POSITION, exactly as
    extraction/to_production_shape.py does for the served rows, so the gate
    judges what a student would actually see.
    """
    if not options:
        return None, correct_option
    keys = list(options)
    if all(k.isdigit() for k in keys):
        ordered = sorted(keys, key=int)
    else:
        return options, correct_option
    mapping = {old: LETTERS[i] for i, old in enumerate(ordered)}
    return ({mapping[k]: options[k] for k in ordered},
            mapping.get(correct_option, correct_option))


def fetch_staging(db_path):
    """Read candidate rows from the extraction staging store.

    The extraction directive halts before promotion - nothing may be written to
    `questions` - so the gate reads the SQLite staging DB directly instead of
    PostgREST. Same row shape either way, so every downstream stage is unchanged.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    # figure-bearing rows cannot be judged by a text-only gate; lint routes
    # them out as figure_dependent instead of letting blind-solve fail them
    # as unreadable after two paid model calls
    figq = {r[0] for r in conn.execute("select distinct question_id from staging_figures")}
    # in_stem is newer than some staging DBs on disk (regress-pageorder-2026-08-16
    # predates it). Without the column the stem-figure route simply cannot fire;
    # degrading to an empty set keeps the gate runnable on older stores instead
    # of dying on `no such column`.
    _figcols = {r[1] for r in conn.execute("pragma table_info(staging_figures)")}
    stemfig = ({r[0] for r in conn.execute(
        "select distinct question_id from staging_figures where in_stem=1")}
        if "in_stem" in _figcols else set())
    rows = []
    for r in conn.execute("select * from staging_questions where gate_status='staged'"):
        options = json.loads(r["options"]) if r["options"] else None
        options, correct_option = _relabel(options, r["correct_option"])
        rows.append({
            "id": r["id"],
            "question_text": r["question_text"],
            "question_type": r["question_type"],
            "options": options,
            "correct_option": correct_option,
            "correct_value": r["correct_value"],
            # staging has no tolerance column yet; None makes values_match fall
            # back to its default band rather than silently comparing exactly
            "value_tolerance": None,
            "solution": None,
            "chapter_name": r["chapter"],
            "needs_manual": r["needs_manual"],
            # A key already checked against the PRINTED page. Stronger evidence
            # than any blind solve, so gate_one skips its key stages rather than
            # re-litigating them - see the guard there.
            "adjudication_verdict": (r["adjudication_verdict"]
                                     if "adjudication_verdict" in r.keys() else None),
            # Batch tag, not the individual filename: the spec's rule 3 wants a
            # single value per batch so the gate can target it and a bad batch
            # can be rolled back as a unit. run_id is exactly that
            # ("full-2026-08-10", "batch2-2026-08-15"); the per-paper filename
            # stays available separately.
            "source": r["run_id"],
            "source_pdf": r["source_pdf"],
            "has_figure": r["id"] in figq,
            "has_stem_figure": r["id"] in stemfig,
        })
    conn.close()
    return rows


def apply_staging(db_path, passed, failed, dupes=None):
    """Write verdicts back to staging. Never touches `questions`.

    `dupes` maps staging id -> (questions_twin_id, twin_servable, jaccard) from
    the twin check. A servable twin means the promote step must NOT insert this
    row (gate_verdict='pass_duplicate'); a quarantined twin means insert as
    normal but retire the old questions row (duplicate_of carries its id).
    """
    dupes = dupes or {}
    conn = sqlite3.connect(db_path)
    cols = {r[1] for r in conn.execute("pragma table_info(staging_questions)")}
    if "solution_text" not in cols:
        conn.execute("alter table staging_questions add column solution_text text")
    if "gate_verdict" not in cols:
        conn.execute("alter table staging_questions add column gate_verdict text")
    if "duplicate_of" not in cols:
        conn.execute("alter table staging_questions add column duplicate_of text")
    n_ok = n_bad = 0
    for r in passed:
        hit = dupes.get(r["id"])
        if hit and hit[1]:
            conn.execute(
                "update staging_questions set solution_text=?, "
                "needs_manual='duplicate_of_servable', gate_verdict='pass_duplicate', "
                "duplicate_of=? where id=?",
                (json.dumps({"steps": r["steps"]}, ensure_ascii=False), hit[0], r["id"]))
            n_ok += 1
            continue
        conn.execute(
            "update staging_questions set solution_text=?, needs_manual=NULL, "
            "gate_verdict='pass', duplicate_of=? where id=?",
            (json.dumps({"steps": r["steps"]}, ensure_ascii=False),
             hit[0] if hit else None, r["id"]))
        n_ok += 1
    for r in failed:
        conn.execute(
            "update staging_questions set needs_manual=?, gate_verdict='fail' where id=?",
            (r.get("reason") or "audit_remove_verdict", r["id"]))
        n_bad += 1
    conn.commit()
    conn.close()
    return n_ok, n_bad


# ---------------------------------------------------------------- dedupe ----
# Re-extraction recovers quarantined questions as NEW rows, so without a twin
# check at promotion time the bank accumulates duplicates: a re-extracted copy
# of an already-servable question would double-serve, and the stale quarantined
# original would sit in triage piles forever after its clean twin ships.
#
# Matching is token-set Jaccard over normalised stems with an inverted-index
# block (rare tokens only) so a full-bank pass stays O(rows x candidates), not
# O(rows^2). Numbers are load-bearing: "x+y+z=8" and "x+y+z=20" share almost
# every word, so a high word overlap with DIFFERENT number sets is treated as a
# different question unless the overlap is near-total (OCR noise can perturb a
# digit, hence the escape hatch at 0.92 rather than a hard veto).

STOPWORDS = frozenset(
    "the a an of in on for is are be to and or with which following from by at "
    "as its this that then will can what when correct incorrect option options "
    "given find value statement statements respectively".split())

TWIN_STRONG = 0.85   # Jaccard at/above which same-number stems are twins
TWIN_WEAK = 0.70     # floor when the number sets also match exactly
TWIN_NUM_MISMATCH = 0.92  # overlap needed to call twins DESPITE differing numbers


def stem_tokens(text):
    toks = re.findall(r"[a-z]+|\d+(?:\.\d+)?", (text or '').lower())
    return frozenset(t for t in toks if t not in STOPWORDS and (len(t) > 1 or t.isdigit()))


class TwinIndex:
    """Token-blocked twin lookup over the live questions table."""

    def __init__(self, rows):
        self.meta = {}     # id -> (tokens, numbers, servable)
        df = collections.Counter()
        for q in rows:
            toks = stem_tokens(q.get('question_text'))
            nums = frozenset(t for t in toks if t[0].isdigit())
            self.meta[q['id']] = (toks, nums, q.get('needs_manual') is None)
            for t in toks:
                df[t] += 1
        # Block on discriminative tokens only; ubiquitous ones pull in everything.
        self.inverted = collections.defaultdict(set)
        for qid, (toks, _, _) in self.meta.items():
            for t in toks:
                if df[t] <= 50:
                    self.inverted[t].add(qid)

    def find_twin(self, text, exclude_id=None):
        """Best (twin_id, servable, jaccard) above threshold, else None."""
        toks = stem_tokens(text)
        if len(toks) < 6:
            return None            # too little signal to call anything a twin
        nums = frozenset(t for t in toks if t[0].isdigit())
        shared = collections.Counter()
        for t in toks:
            for qid in self.inverted.get(t, ()):
                shared[qid] += 1
        best = None
        for qid, n_shared in shared.most_common(30):
            if qid == exclude_id or n_shared < 2:
                continue
            o_toks, o_nums, servable = self.meta[qid]
            union = len(toks | o_toks)
            j = len(toks & o_toks) / union if union else 0.0
            if nums == o_nums:
                threshold = TWIN_WEAK if len(toks) >= 10 else TWIN_STRONG
            else:
                threshold = TWIN_NUM_MISMATCH
            if j >= threshold and (best is None or j > best[2]):
                best = (qid, servable, round(j, 3))
        return best


def build_twin_index():
    return TwinIndex(fetch(None, None))


def dedupe_report():
    """Read-only scan of the whole bank for twin pairs."""
    rows = fetch(None, None)
    idx = TwinIndex(rows)
    by_id = {r['id']: r for r in rows}
    pairs, seen = [], set()
    for q in rows:
        hit = idx.find_twin(q.get('question_text'), exclude_id=q['id'])
        if not hit:
            continue
        a, b = sorted((q['id'], hit[0]))
        if (a, b) in seen:
            continue
        seen.add((a, b))
        me_servable = q.get('needs_manual') is None
        # A pair is RESOLVED when its quarantined side is parked precisely
        # because of the twin relation — one copy serves, the other is retired.
        RESOLVED_TAGS = ('duplicate_of_servable', 'superseded_by_reextraction')
        other_tag = by_id[hit[0]].get('needs_manual')
        my_tag = q.get('needs_manual')
        if me_servable and hit[1]:
            kind = 'UNRESOLVED servable+servable (double-serving!)'
        elif me_servable or hit[1]:
            tag = other_tag if me_servable else my_tag
            kind = ('resolved (twin parked)' if tag in RESOLVED_TAGS
                    else 'servable+quarantined (twin awaiting triage)')
        else:
            kind = 'quarantined+quarantined (informational)'
        pairs.append((kind, hit[2], a, b))
    counts = collections.Counter(k for k, *_ in pairs)
    print(f"twin pairs found: {len(pairs)}")
    for k, v in counts.most_common():
        print(f"  {v:4d}  {k}")
    unresolved = [p for p in pairs if p[0].startswith('UNRESOLVED')]
    for kind, j, a, b in sorted(unresolved, key=lambda p: -p[1])[:15]:
        print(f"    !! J={j}  {a[:8]} ~ {b[:8]}")
    print("CLEAN: no question double-serves." if not unresolved
          else f"ATTENTION: {len(unresolved)} double-serving pairs need cleanup.")
    return pairs


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
    ap.add_argument('--staging', help='path to an extraction staging.db; reads and '
                                      'writes there instead of the questions table')
    ap.add_argument('--limit', type=int, help='judge at most N rows (sampling)')
    ap.add_argument('--journal', help='verdict journal path (default: gate_results.jsonl '
                                      'next to this script). Concurrent runs sharing the '
                                      'default journal interleave rows and contaminate any '
                                      'aggregate computed over the raw file — give each run '
                                      'its own journal.')
    ap.add_argument('--no-dedupe', action='store_true',
                    help='skip the twin check at promotion (not recommended)')
    ap.add_argument('--dedupe-report', action='store_true',
                    help='read-only: scan the whole questions table for twin pairs and exit')
    args = ap.parse_args()
    if args.dedupe_report:
        dedupe_report()
        return
    if not args.where and not args.ids and not args.staging:
        ap.error('need --where, --ids, or --staging')

    global OUT
    if args.journal:
        OUT = args.journal

    ids = json.load(open(args.ids)) if args.ids else None
    rows = fetch_staging(args.staging) if args.staging else fetch(args.where, ids)
    if args.staging and ids:
        # --ids used to be silently ignored under --staging: an intended 60-row
        # sample became a full-bank run (found by the biology-set session).
        # Honour it as a filter over the staging rows instead.
        idset = set(ids)
        rows = [q for q in rows if q['id'] in idset]
    if args.limit and args.limit < len(rows):
        # Spread the sample across the corpus. Rows come out in insertion order,
        # so a plain rows[:N] slice draws from whichever papers happened to be
        # processed first - measured: the first 300 of 6,683 span only 6 of 78
        # papers, which measures those papers rather than the bank. Fixed seed so
        # the sample is reproducible and the journal stays resumable.
        import random
        rows = random.Random(0).sample(rows, args.limit)
    done = already_done()
    todo = [q for q in rows if q['id'] not in done]
    print(f"candidates={len(rows)} judged_previously={len(done)} to_judge={len(todo)}", flush=True)

    client = get_client()
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

    # Twin check at promotion time. Skipped only with --no-dedupe: a promotion
    # that double-serves an existing question is a defect even when the row
    # itself is flawless.
    twin_idx = None if args.no_dedupe else build_twin_index()
    row_text = {q['id']: q.get('question_text') for q in rows}

    if args.staging:
        dupes = {}
        if twin_idx:
            for r in passed:
                hit = twin_idx.find_twin(row_text.get(r['id']))
                if hit:
                    dupes[r['id']] = hit
        n_ok, n_bad = apply_staging(args.staging, passed, failed, dupes)
        n_dup = sum(1 for h in dupes.values() if h[1])
        print(f"APPLIED to staging: {n_ok} passed (solution stored, needs_manual cleared); "
              f"{n_bad} tagged needs_manual; {n_dup} held as duplicate_of_servable; "
              f"{len(dupes) - n_dup} marked supersedes_quarantined. `questions` untouched.")
        return

    n_ok = n_bad = n_dup = n_super = 0
    for r in passed:
        if twin_idx:
            hit = twin_idx.find_twin(row_text.get(r['id']), exclude_id=r['id'])
            if hit and hit[1]:
                # A servable twin already covers this question — promoting would
                # double-serve it. Park this copy instead.
                resp = requests.patch(U + '/rest/v1/questions', headers=HW,
                                      params={'id': f"eq.{r['id']}"},
                                      data=json.dumps({"needs_manual": "duplicate_of_servable"}))
                n_dup += resp.status_code in (200, 204)
                continue
            if hit and not hit[1]:
                # This row supersedes a stale quarantined copy of the same
                # question — retire the old one so it leaves the triage piles.
                resp = requests.patch(U + '/rest/v1/questions', headers=HW,
                                      params={'id': f"eq.{hit[0]}"},
                                      data=json.dumps({"needs_manual": "superseded_by_reextraction"}))
                n_super += resp.status_code in (200, 204)
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
    print(f"APPLIED: {n_ok} rows passed and serving with verified solutions; {n_bad} rows tagged needs_manual; "
          f"{n_dup} held as duplicate_of_servable; {n_super} stale twins retired as superseded_by_reextraction")


if __name__ == '__main__':
    asyncio.run(main())

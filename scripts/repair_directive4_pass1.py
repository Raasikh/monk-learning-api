#!/usr/bin/env python3
"""Directive-4 pass 1: deterministic residue repairs + quarantine classes.

Terminal pass over the four raw staging files (run last; row-level edits only):
  1. Strip answer/solution leak residue from option values (truncation only,
     never reconstruction). The earlier repair_options.py pass missed rows
     where the leak sits in option D without an "Official Ans" banner.
  2. Strip ExamSIDE website furniture ("Correct", "Your answer", "Check
     Answer", "Explanation ...") from option values.
  3. Quarantine classes (set needs_manual on rows currently 'pending_gate';
     already-quarantined rows keep their reason and only get a defects note):
       options_unrepairable          empty option after strip, no image fallback
       options_merged_answer_choices '(1)...(2)...' choices embedded in an option
       option_figures_incomplete     options are images; no complete A-D set exists
       options_duplicate_values      two options byte-identical (len>20)
       options_ocr_degraded          lost minus signs / fraction bars (named rows)
       text_layer_pua_unrepairable   private-use-area chars survive
       stem_reference_absent         stem references a figure, no asset attached
       stem_furniture_residue        page header/footer inside stem
       stem_merged_next_question     following question's text inside stem
       stem_figures_incomplete       stem needs multiple figures, only one attached
       source_figure_axis_swapped    source printed the figure wrong (named row)

Every touched row appends to a string-list field `defects` for audit.
Prints per-class before/after counts. Raw layer only; nothing here is servable.
"""
import json, re, sys, collections

BASE = 'data/nta_raw'
DQ = f'{BASE}/diagram_questions.jsonl'
EXAMSIDE = [f'{BASE}/examside_diagram_questions.jsonl',
            f'{BASE}/examside_diagram_questions_jee_advanced.jsonl',
            f'{BASE}/neet_mathongo_questions.jsonl']

LEAK_MARKERS = ['Official Ans', 'Ans. (', 'Ans.(', '\nSol.', ' Sol.', 'Sol: (',
                'Solution:', 'Answer (', 'JEE Exam Solution', 'www.esaral.com']
NEXTQ_RE = re.compile(r'\s\d{1,2}\.\s*\(\d\)\s')          # " 23. (3) " next-q + key
MERGED_CHOICES_RE = re.compile(r'\(1\).{0,80}\(2\)', re.S)
FURN_STEM_RE = re.compile(r'JEE[\s-]*Main[\s-]*\d{2}-\d{2}-\d{4}|Evening Shift|Morning Shift', re.I)
NEXTQ_STEM_RE = re.compile(r'\n\s*\d{1,2}\s*\n[A-Z][a-z]')
FIGREF_RE = re.compile(r'\b(figure|fig\.|diagram|graph shown|shown in|as shown|see figure|given figure|the figure)\b', re.I)
PUA_RE = re.compile(r'[\ue000-\uf8ff]')

PUNCT_ONLY_RE = re.compile(r'^[\W_]+$')
ANDOR_RE = re.compile(r'^(and|or)$')
VOLT_PAIR_RE = re.compile(r'^[+−-]?\d+\s*V\s+[+−-]?\d+\s*V$')
NUM_UNIT_RE = re.compile(r'^[+−-]?[\d.,/]+\s*[a-zA-ZµΩ°/%]*$')
GATE_NAMES = {'or', 'and', 'nor', 'nand', 'not', 'xor', 'xnor'}
FIGWORD_RE = re.compile(r'graph|plot|figure|circuit|structure|diagram|shown|curve|sketch|waveform|spectrum|variation', re.I)

OCR_DEGRADED_NAMED = {'1ca8ba8bcb5f9f4b', '162f72c9c3a8573c'}
AXIS_SWAPPED_NAMED = {'7b493d842c687bd9'}
STEM_FIGURES_INCOMPLETE_NAMED = {'95381c0c61187508'}
DUPLICATE_OF = {'100383e3ca6fb082': '68afe0ae57644d5b'}
OPTIONS_OTHER_QUESTION_NAMED = {'e76314c461c43677'}


def load(path):
    return [json.loads(l) for l in open(path)]

def save(path, rows):
    with open(path, 'w') as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')

def norm(s):
    return re.sub(r'\s+', '', s or '').lower()

def note(r, msg):
    r.setdefault('defects', [])
    if msg not in r['defects']:
        r['defects'].append(msg)

def quarantine(r, reason, counts):
    """Set needs_manual only if the row is currently a servable candidate."""
    if r.get('needs_manual') in (None, 'pending_gate'):
        r['needs_manual'] = reason
        counts[reason] += 1
    note(r, reason)


def strip_leak(value):
    """Truncate an option value at the earliest leak marker. Returns (new, stripped)."""
    if not isinstance(value, str):
        return value, False
    cut = len(value)
    for m in LEAK_MARKERS:
        i = value.find(m)
        if i != -1:
            cut = min(cut, i)
    m = NEXTQ_RE.search(value)
    if m:
        cut = min(cut, m.start())
    if cut < len(value):
        return value[:cut].rstrip(), True
    return value, False


def spaced_fragment(v):
    """Option text that is OCR-of-image label fragments, e.g. 'SPh F NO2', 'D4 R 5V'."""
    s = (v or '').strip()
    if not s or '$' in s or len(s) > 25:
        return False
    if s.lower() in GATE_NAMES or NUM_UNIT_RE.match(s):
        return False
    if re.match(r'^[A-E](\s+and\s+[A-E])+\s+only$', s):
        return False
    if re.search(r'[=\\/()\[\]π{}]', s):
        return False
    toks = re.split(r'[\s,]+', s)
    return len(toks) >= 2 and all(len(t) <= 4 for t in toks) and any(re.search(r'[A-Za-z]', t) for t in toks)


def option_figures_signature(r, sib_count):
    opts = [(r.get('options') or {}).get(k) for k in 'ABCD']
    nvals = [norm(v) for v in opts]
    nonempty = [v for v in nvals if v]
    if nonempty and len(set(nvals)) == 1 and len(nvals) == 4:
        return 'all4_identical'
    punct = sum(1 for v in opts if isinstance(v, str) and (PUNCT_ONLY_RE.match(v.strip()) or ANDOR_RE.match(v.strip())))
    if punct >= 2:
        return 'punct_options'
    if any(isinstance(v, str) and VOLT_PAIR_RE.match(v.strip()) for v in opts):
        return 'node_voltages'
    frag = sum(1 for v in opts if spaced_fragment(v))
    if frag >= 2 and sib_count >= 2 and FIGWORD_RE.search(r.get('question_text') or ''):
        return 'spaced_label_fragments'
    return None


def main():
    counts = collections.Counter()
    stripped_opt_d_leak = 0
    stripped_furniture = 0

    # sibling crops per (paper_id, qno) from the candidate pool
    sib = collections.Counter()
    for l in open(f'{BASE}/diagram_candidates.jsonl'):
        c = json.loads(l)
        q = (c.get('context') or {}).get('qno')
        if q is not None:
            sib[(c['paper_id'], q)] += 1

    # ---------- diagram_questions.jsonl ----------
    rows = load(DQ)
    for r in rows:
        qid = r['diagram_question_id']
        # 1. leak strip on all options
        for k in 'ABCD':
            opts = r.get('options') or {}
            v = opts.get(k)
            new, did = strip_leak(v)
            if did:
                opts[k] = new
                stripped_opt_d_leak += 1
                note(r, f'option_{k}_leak_truncated')
        # named rows
        if qid in AXIS_SWAPPED_NAMED:
            quarantine(r, 'source_figure_axis_swapped', counts)
        if qid in STEM_FIGURES_INCOMPLETE_NAMED:
            quarantine(r, 'stem_figures_incomplete', counts)
        if qid in OCR_DEGRADED_NAMED:
            quarantine(r, 'options_ocr_degraded', counts)
        if qid in DUPLICATE_OF:
            r['duplicate_of'] = DUPLICATE_OF[qid]
            note(r, f'duplicate_of:{DUPLICATE_OF[qid]}')
        if qid in OPTIONS_OTHER_QUESTION_NAMED:
            note(r, 'options_belong_to_other_question')
        # structural classes
        opts = r.get('options') or {}
        vals = [opts.get(k) for k in 'ABCD']
        if r.get('question_type') == 'single_correct' and any(
                not isinstance(v, str) or not v.strip() for v in vals):
            quarantine(r, 'options_unrepairable', counts)
        if any(isinstance(v, str) and MERGED_CHOICES_RE.search(v) for v in vals):
            quarantine(r, 'options_merged_answer_choices', counts)
        sig = option_figures_signature(r, sib.get((r['paper_id'], r['qno']), 0))
        if sig:
            note(r, f'option_figures_signature:{sig}')
            r['option_figures'] = {'status': 'incomplete', 'source': 'option_text_signature',
                                   'signature': sig}
            quarantine(r, 'option_figures_incomplete', counts)
        nv = [norm(v) for v in vals if isinstance(v, str) and v.strip()]
        if len(nv) != len(set(nv)):
            long_dup = any(nv.count(x) > 1 and len(x) >= 15 for x in set(nv))
            if long_dup:
                quarantine(r, 'options_duplicate_values', counts)
        text_all = (r.get('question_text') or '') + ' ' + ' '.join(
            v for v in vals if isinstance(v, str))
        if PUA_RE.search(text_all):
            quarantine(r, 'text_layer_pua_unrepairable', counts)
        stem = r.get('question_text') or ''
        if not r.get('diagram_asset') and FIGREF_RE.search(stem):
            quarantine(r, 'stem_reference_absent', counts)
        if FURN_STEM_RE.search(stem):
            quarantine(r, 'stem_furniture_residue', counts)
        elif NEXTQ_STEM_RE.search(stem):
            quarantine(r, 'stem_merged_next_question', counts)
    save(DQ, rows)

    # ---------- examside / mathongo ----------
    FURN_TAIL = re.compile(r'\s*(Your answer.*|Check Answer.*|Explanation.*)$', re.I | re.S)
    CORRECT_TAIL = re.compile(r'\s*Correct\s*$')
    for path in EXAMSIDE:
        rows = load(path)
        for r in rows:
            opts = r.get('options') or {}
            oimgs = r.get('option_images') or {}
            for k in 'ABCD':
                v = opts.get(k)
                if not isinstance(v, str):
                    continue
                new = CORRECT_TAIL.sub('', FURN_TAIL.sub('', v)).strip()
                if new != v.strip():
                    opts[k] = new
                    stripped_furniture += 1
                    note(r, f'option_{k}_examside_furniture_stripped')
            # option_figures concept: a key is covered by non-empty text OR an
            # image. Mixed rows (some text, some images) are complete if every
            # key is covered. Incomplete = at least one key has neither.
            have_img = [k for k in 'ABCD' if oimgs.get(k)]
            covered = [k for k in 'ABCD'
                       if oimgs.get(k) or (isinstance((r.get('options') or {}).get(k), str)
                                           and (r.get('options') or {}).get(k).strip())]
            if have_img:
                if len(covered) == 4:
                    r['option_figures'] = {'status': 'complete', 'source': 'examside_option_images',
                                           'mode': 'images' if len(have_img) == 4 else 'mixed'}
                else:
                    r['option_figures'] = {'status': 'incomplete', 'source': 'examside_option_images',
                                           'present': have_img,
                                           'uncovered': [k for k in 'ABCD' if k not in covered]}
                    quarantine(r, 'option_figures_incomplete', counts)
            # empty option text without an image to carry it
            if r.get('question_type') == 'single_correct':
                for k in 'ABCD':
                    v = (r.get('options') or {}).get(k)
                    if (not isinstance(v, str) or not v.strip()) and not oimgs.get(k):
                        quarantine(r, 'options_unrepairable', counts)
                        break
        save(path, rows)

    print(json.dumps({
        'option_values_leak_truncated': stripped_opt_d_leak,
        'option_values_examside_furniture_stripped': stripped_furniture,
        'newly_quarantined_by_reason': dict(counts),
    }, indent=2))

if __name__ == '__main__':
    sys.exit(main())

#!/usr/bin/env python3
"""Directive non-figure pool §3.2: deterministic repairs + eligibility.

Runs the same solved repair classes as the diagram corpus over
data/nta_raw/nonfigure_questions.jsonl, reusing the helpers from
repair_directive4_pass1.py (truncation only, never reconstruction):

  option/stem leak strip        Official Ans / Ans. (n) / Sol. residue
  option_too_long               >300 chars after strip -> quarantine
  options_duplicate_values      two options textually identical
  options_ocr_degraded          lost minus signs / fraction bars signature
  text_layer_pua_unrepairable   PUA in options (stems were filtered at materialise)
  stem_furniture_residue        page header/footer inside stem
  stem_merged_next_question     following question's text inside stem
  eligibility                   pending_gate only if is_quality_question-passable

Every touched row appends to `defects`. Prints per-class before/after counts.
"""
import json, re, sys, collections
sys.path.insert(0, 'scripts')
from repair_directive4_pass1 import (strip_leak, LEAK_MARKERS, NEXTQ_RE,
                                     FURN_STEM_RE, NEXTQ_STEM_RE, VOLT_PAIR_RE)

PATH = 'data/nta_raw/nonfigure_questions.jsonl'
PUA_RE = re.compile(r'[\uf000-\uf0ff]')
STAMP_RE = re.compile(r'\bQ\d{1,3}\.\s*\([A-D1-4]\)')
MERGED_CHOICES_RE = re.compile(r'\(1\).{0,80}\(2\)', re.S)
ANS_VAR_RE = re.compile(r'\bAns\.\s*[\$\\]')


def note(r, msg):
    r.setdefault('defects', [])
    if msg not in r['defects']:
        r['defects'].append(msg)


def quarantine(r, reason, counts):
    if r.get('needs_manual') in (None, 'pending_gate'):
        r['needs_manual'] = reason
        counts[reason] += 1
    note(r, reason)


def main():
    rows = [json.loads(l) for l in open(PATH)]
    counts = collections.Counter()
    stripped = collections.Counter()

    def strip_text(v):
        if not isinstance(v, str):
            return v, False
        cut = len(v)
        m = ANS_VAR_RE.search(v)
        if m:
            cut = min(cut, m.start())
        new = v[:cut]
        new2, did = strip_leak(new)
        if m or did:
            return new2.rstrip(), True
        return v, False

    for r in rows:
        opts = r.get('options') or {}
        for k in 'ABCD':
            new, did = strip_text(opts.get(k))
            if did:
                opts[k] = new
                stripped[f'option_{k}_leak_truncated'] += 1
                note(r, f'option_{k}_leak_truncated')
        stem = r.get('question_text') or ''
        new, did = strip_text(stem)
        if did and len(new.strip()) >= 20:
            r['question_text'] = new.strip()
            stripped['stem_leak_truncated'] += 1
            note(r, 'stem_leak_truncated')
        elif did:
            quarantine(r, 'stem_unrepairable', counts)

        vals = [(r.get('options') or {}).get(k) for k in 'ABCD']
        # eligibility: 4 non-empty options after strip
        if any(not isinstance(v, str) or not v.strip() for v in vals):
            quarantine(r, 'options_unrepairable', counts)
        if any(isinstance(v, str) and len(v) > 300 for v in vals):
            quarantine(r, 'option_too_long', counts)
        norm = [re.sub(r'\s+', '', (v or '').lower()) for v in vals]
        if all(norm) and len(set(norm)) < 4:
            quarantine(r, 'options_duplicate_values', counts)
        if any(isinstance(v, str) and VOLT_PAIR_RE.match(v.strip()) for v in vals):
            quarantine(r, 'options_ocr_degraded', counts)
        if any(isinstance(v, str) and v.count('$') % 2 == 1 for v in vals):
            quarantine(r, 'options_unrepairable', counts)
            note(r, 'unbalanced_math_delimiters')
        if any(isinstance(v, str) and MERGED_CHOICES_RE.search(v) for v in vals):
            quarantine(r, 'options_merged_answer_choices', counts)
        if any(isinstance(v, str) and PUA_RE.search(v) for v in vals):
            quarantine(r, 'text_layer_pua_unrepairable', counts)
        stem = r.get('question_text') or ''
        if FURN_STEM_RE.search(stem):
            quarantine(r, 'stem_furniture_residue', counts)
        elif NEXTQ_STEM_RE.search(stem):
            quarantine(r, 'stem_merged_next_question', counts)
        if STAMP_RE.search(stem):
            quarantine(r, 'answer_stamp_in_stem', counts)
        # no figure, ever
        r['diagram'] = None

    with open(PATH, 'w') as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')
    nm = collections.Counter(r.get('needs_manual') for r in rows)
    print(json.dumps({'stripped': dict(stripped),
                      'newly_quarantined': dict(counts),
                      'needs_manual_after': dict(nm)}, indent=2))


if __name__ == '__main__':
    sys.exit(main())

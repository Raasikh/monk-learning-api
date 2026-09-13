#!/usr/bin/env python3
"""Directive-4 pass 2: enforce pending_gate eligibility.

A row may hold needs_manual='pending_gate' only if it could in principle pass
is_quality_question (app/routers/practice.py:157): stem >=20 chars, and either
4 covered options (text or option image), or numerical with a numeric key,
or a complete option-figure set. Everything else gets a specific reason:

  type_underivable          question_type missing
  stem_below_min_length     stem <20 chars (several are image-carried stems)
  options_unrepairable      single_correct, <4 covered options, no images
  option_figures_incomplete image-option row with at least one uncovered key
  type_options_conflict     numerical type carrying options (client renders
                            numerical rows with no options — production defect
                            class repaired 52 times in the live bank)
  key_missing               numerical with no parseable numeric key

Image-option rows whose four keys are all covered (text and/or option_images)
stay pending_gate and get option_figures.status='complete'.
"""
import json, re, sys, collections

BASE = 'data/nta_raw'
FILES = [f'{BASE}/diagram_questions.jsonl',
         f'{BASE}/examside_diagram_questions.jsonl',
         f'{BASE}/examside_diagram_questions_jee_advanced.jsonl',
         f'{BASE}/neet_mathongo_questions.jsonl']

NUM_RE = re.compile(r'[+-]?\d+(\.\d+)?$')


def numeric_key(r):
    for e in (r.get('answer_sheet') or {}).get('entries') or []:
        raw = ((e.get('answer') or {}).get('raw'))
        if raw is not None and NUM_RE.fullmatch(str(raw).strip()):
            return str(raw).strip()
    return None


def note(r, msg):
    r.setdefault('defects', [])
    if msg not in r['defects']:
        r['defects'].append(msg)


def main():
    counts = collections.Counter()
    kept_complete = 0
    for path in FILES:
        rows = [json.loads(l) for l in open(path)]
        for r in rows:
            if r.get('needs_manual') != 'pending_gate':
                continue
            qid = r['diagram_question_id']
            stem = (r.get('question_text') or '').strip()
            qt = r.get('question_type')
            opts = r.get('options') or {}
            oimgs = r.get('option_images') or {}
            nonempty = [k for k in 'ABCD' if isinstance(opts.get(k), str) and opts.get(k).strip()]
            covered = [k for k in 'ABCD' if k in nonempty or oimgs.get(k)]

            def fail(reason):
                r['needs_manual'] = reason
                counts[reason] += 1
                note(r, reason)

            if not qt:
                fail('type_underivable')
                continue
            if len(stem) < 20:
                if r.get('diagram_image_urls'):
                    note(r, 'stem_is_image_carried')
                fail('stem_below_min_length')
                continue
            if qt in ('single_correct', 'match_the_following'):
                if len(nonempty) >= 4:
                    continue
                if oimgs:
                    if len(covered) == 4:
                        r['option_figures'] = {'status': 'complete',
                                               'source': 'examside_option_images',
                                               'mode': 'images' if not nonempty else 'mixed'}
                        kept_complete += 1
                    else:
                        r['option_figures'] = {'status': 'incomplete',
                                               'source': 'examside_option_images',
                                               'uncovered': [k for k in 'ABCD' if k not in covered]}
                        fail('option_figures_incomplete')
                else:
                    fail('options_unrepairable')
                continue
            if qt == 'numerical':
                if nonempty:
                    fail('type_options_conflict')
                elif not numeric_key(r):
                    fail('key_missing')
                continue
            # unknown future type: keep, but never silently
            note(r, f'eligibility_unreviewed_type:{qt}')
        with open(path, 'w') as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + '\n')
    print(json.dumps({'newly_quarantined': dict(counts),
                      'kept_pending_gate_as_complete_option_figures': kept_complete}, indent=2))


if __name__ == '__main__':
    sys.exit(main())

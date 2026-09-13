#!/usr/bin/env python3
"""Directive non-figure pool §3.3: dedupe internally and against the live bank.

Fingerprint = stem text, lowercased, LaTeX commands and all non-alphanumerics
stripped. Internal duplicates keep the first row (provenance preserved via
duplicate_of + merged_from on the keeper). Rows matching the live questions
table get needs_manual='duplicate_of_servable:<live_id>'; the live row is
never touched.
"""
import json, re, sys, collections

PATH = 'data/nta_raw/nonfigure_questions.jsonl'
LIVE = 'scratch/directive4/live_questions_fingerprint_source.json'
LATEX_CMD = re.compile(r'\\[a-zA-Z]+')
NONALNUM = re.compile(r'[^a-z0-9]+')


def fingerprint(text):
    t = (text or '').lower()
    t = LATEX_CMD.sub(' ', t)
    t = NONALNUM.sub('', t)
    return t


def main():
    rows = [json.loads(l) for l in open(PATH)]
    counts = collections.Counter()

    # internal dedupe over all rows, first occurrence wins
    seen = {}
    for r in rows:
        fp = fingerprint(r.get('question_text'))
        if not fp:
            continue
        if fp in seen:
            keeper = seen[fp]
            if r.get('needs_manual') == 'pending_gate':
                r['needs_manual'] = 'duplicate_internal'
                counts['duplicate_internal'] += 1
            r['duplicate_of'] = keeper['nonfigure_question_id']
            r.setdefault('defects', []).append(f"duplicate_internal:{keeper['nonfigure_question_id']}")
            keeper.setdefault('merged_from', []).append({
                'nonfigure_question_id': r['nonfigure_question_id'],
                'paper_id': r['paper_id'], 'qno': r.get('qno'), 'page': r.get('page'),
                'pdf_url': r.get('pdf_url'), 'source_tier': r.get('source_tier'),
            })
        else:
            seen[fp] = r

    # live-bank dedupe
    live_fp = {}
    for q in json.load(open(LIVE)):
        fp = fingerprint(q.get('question_text'))
        if fp and fp not in live_fp:
            live_fp[fp] = q['id']
    for r in rows:
        if r.get('needs_manual') != 'pending_gate':
            continue
        live_id = live_fp.get(fingerprint(r.get('question_text')))
        if live_id is not None:
            r['needs_manual'] = f'duplicate_of_servable:{live_id}'
            r['duplicate_of_live'] = live_id
            counts['duplicate_of_servable'] += 1

    with open(PATH, 'w') as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')
    nm = collections.Counter(
        'duplicate_of_servable' if (r.get('needs_manual') or '').startswith('duplicate_of_servable') else r.get('needs_manual')
        for r in rows)
    print(json.dumps({'new': dict(counts), 'needs_manual_after': dict(nm)}, indent=2))


if __name__ == '__main__':
    sys.exit(main())

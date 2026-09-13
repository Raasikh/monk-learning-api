#!/usr/bin/env python3
"""Materialise the non-figure question pool (directive: non-figure pool §3.1).

Reads every paper artifact in data/nta_raw/papers/*.json and emits the CLEAN
subset — 4 non-empty A-D options + usable embedded A-D key + stem >= 20 chars +
no Symbol-font PUA (U+F000-F0FF) in the stem — to
data/nta_raw/nonfigure_questions.jsonl.

These rows have no figure and must never be given one: diagram=None, always.
Every row carries needs_manual='pending_gate' and full provenance.
Does not touch the existing diagram JSONL files.
"""
import json, re, glob, hashlib, collections, sys

BASE = 'data/nta_raw'
OUT = f'{BASE}/nonfigure_questions.jsonl'
PUA_RE = re.compile(r'[\uf000-\uf0ff]')


def qid_for(paper_id, q, manifest_subject=None):
    key = (paper_id, q.get('qno'), q.get('question_id'),
           q.get('subject') or manifest_subject, q.get('section'), 'nonfigure')
    return hashlib.sha256(json.dumps(key, default=str).encode()).hexdigest()[:16]


def main():
    stats = collections.Counter()
    key_dist = collections.Counter()
    rows_out = []
    seen_ids = set()
    for path in sorted(glob.glob(f'{BASE}/papers/*.json')):
        d = json.load(open(path))
        man = d.get('manifest') or {}
        sheet_status = (d.get('answer_sheet') or {}).get('status')
        for q in d.get('questions') or []:
            stats['total'] += 1
            opts = q.get('options') or {}
            if not all(isinstance(opts.get(k), str) and opts.get(k).strip() for k in 'ABCD'):
                stats['drop:fewer_than_4_options'] += 1
                continue
            ea = q.get('embedded_answer') or {}
            letter = ea.get('option')
            if not (isinstance(letter, str) and letter.strip() in 'ABCD'):
                stats['drop:no_usable_key'] += 1
                continue
            letter = letter.strip()
            stem = (q.get('text') or '').strip()
            if len(stem) < 20:
                stats['drop:stem_under_20_chars'] += 1
                continue
            if PUA_RE.search(stem):
                stats['drop:pua_mojibake'] += 1
                continue
            stats['clean'] += 1
            key_dist[letter] += 1
            qid = qid_for(d['paper_id'], q, man.get('subject'))
            if qid in seen_ids:
                stats['drop:id_collision'] += 1
                continue
            seen_ids.add(qid)
            rows_out.append({
                'nonfigure_question_id': qid,
                'paper_id': d['paper_id'],
                'exam': man.get('exam') or d.get('exam_tag'),
                'exam_tag': d.get('exam_tag'),
                'tags': d.get('tags'),
                'year': man.get('year'),
                'session': man.get('session'),
                'exam_date': man.get('exam_date'),
                'shift': man.get('shift'),
                'subject': q.get('subject') or man.get('subject'),
                'section': q.get('section'),
                'qno': q.get('qno'),
                'question_id': q.get('question_id'),
                'question_type': 'single_correct',  # 4 options + letter key is never numerical
                'question_text': stem,
                'options': {k: opts[k].strip() for k in 'ABCD'},
                'correct_option': letter,
                'solution': None,
                'explanations': None,
                'answer_sheet': {
                    'status': sheet_status if sheet_status == 'official_verified' else 'embedded_unverified',
                    'source': 'mirror_pdf_embedded',
                    'official_key_url': man.get('official_key_url'),
                    'validation': 'not_verified',
                    'entries': [{'qno': q.get('qno'), 'question_id': q.get('question_id'),
                                 'subject': q.get('subject'), 'section': q.get('section'),
                                 'answer': {'raw': ea.get('raw'), 'option': letter,
                                            'option_index': ea.get('option_index')}}],
                },
                'source_tier': man.get('source_tier'),
                'source_site': man.get('source_site'),
                'source_page_url': man.get('source_page_url'),
                'pdf_url': man.get('pdf_url'),
                'official_key_url': man.get('official_key_url'),
                'page': q.get('page_start'),
                'diagram': None,
                'needs_manual': 'pending_gate',
                'parse_flags': q.get('parse_flags'),
            })
    with open(OUT, 'w') as f:
        for r in rows_out:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')
    n = stats['clean']
    print(json.dumps({
        'out': OUT, 'rows_written': len(rows_out), 'stats': dict(stats),
        'key_distribution_pct': {k: round(100.0 * v / n, 1) for k, v in sorted(key_dist.items())},
        'papers_represented': len({r['paper_id'] for r in rows_out}),
        'subject_unset': sum(1 for r in rows_out if not r['subject']),
    }, indent=2))


if __name__ == '__main__':
    sys.exit(main())

# Corpus proof report (directive §4)

rows analyzed: 4232

## 1. Answer-key distribution

### 1a. Row-level (rows production would serve: row.qno/question_id joined
to its own entry; single-entry sheets joined to that entry)
- {"rows_with_any_key": 718, "letter_keyed": 612, "value_keyed": 101, "dropped_no_key": 5, "no_key": 3514, "letter_distribution_n": 612, "letter_distribution": {"A": "23.4%", "B": "29.1%", "C": "25.3%", "D": "22.2%"}}

### 1b. Entry-level per extraction path (single_correct questions only)
- embedded_unverified:letter_raw (n=7421): {'A': '26.5%', 'B': '27.2%', 'C': '24.7%', 'D': '21.7%'} -> IN BAND
- official_verified:option_field (n=793): {'A': '22.1%', 'B': '30.4%', 'C': '27.4%', 'D': '20.2%'} -> IN BAND

Note: official NTA keys are themselves non-uniform (2022 session key:
A 24.0 / B 31.2 / C 26.3 / D 18.6, z_D=-4.1), so the 15-35% band is a
sanity signal, not ground truth; per-question key agreement is the
authoritative check and happens at the verification gate.

## 2. Self-consistency
- duplicate-text groups: 138
- groups with disagreeing keys: 14 (target 0)

## 3. Multi-region merges
- merged keeper rows (carrying merged_from): 325
- rows whose diagram_regions array has >1 element: 233

## 4. Cumulative funnel (directive §1 gates, in order)
- raw: 4232
- text>=20: 4217
- +question_type: 3438
- +options>=4_or_numerical: 3158
- +asset_resolves: 2797
- +metadata_complete: 1894
- +solution_steps: 1332
- +any_key: 41
- +verified_key: 14
- servable_now: 0
- drop reasons: {"drop:asset_missing": 361, "drop:no_question_type": 779, "drop:options<4": 280, "drop:no_solution": 562, "drop:metadata": 903, "drop:no_key": 1291, "drop:text<20": 15}

Solutions arithmetic (labeled): 2,530 = ExamSIDE rows whose printed
explanation was restructured into solution.steps + explanations.en;
3,122 = mined eSaral ARTIFACT questions with captured Sol. blocks
(artifact-level; only those matching diagram rows propagate);
the +solution_steps funnel count is corpus ROWS carrying steps after
materialize — the sources do not overlap, so no row was overwritten.

## 5. Asset integrity
- asset paths: 625; resolving: 625
- crops under 60x40: 8
- OCR confidence: min=0.0000 p05=0.8087 median=0.9840 below0.90=134

## 6. Text fidelity defects by FIELD (target 0 each)
Fields checked: question_text, options, solution_steps, explanations.
Predicates (published 2026-09-11, widened 2026-09-12):
- pua_mojibake: field contains >=1 codepoint in U+F000..U+F0FF
- char_fragmented: >=4 non-empty lines AND >=40% of non-empty lines
  have stripped length <= 2 (options: only when field >= 300 chars,
  since four short math values trip it legitimately)
- publisher_header: first 300 chars match /chapter-wise question bank|
  mathongo|esaral|selfstudys|download\s+\S+\s*app/i
- answer_stamp_in_stem: field matches /\bQ\d{1,3}\.\s*\([A-D1-4]\)/
- control_chars: any codepoint in U+0000-08, U+000B, U+000C, U+000E-1F
- leak_marker (options only): /Official\s+Ans|(^|\n)\s*Ans\s*[.:\)]|
  (^|\n)\s*Sol\s*[.:]/i
- pua_mojibake: 6  (question_text:1, options:5, solution_steps:0, explanations:0)
- char_fragmented: 15  (question_text:12, options:1, solution_steps:2, explanations:0)
- publisher_header: 5  (question_text:0, options:1, solution_steps:4, explanations:0)
- answer_stamp_in_stem: 0  (question_text:0, options:0, solution_steps:0, explanations:0)
- control_chars: 2  (question_text:0, options:2, solution_steps:0, explanations:0)
- leak_marker: 2  (question_text:0, options:2, solution_steps:0, explanations:0)

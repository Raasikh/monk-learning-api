# NTA raw extraction summary

Deterministic pipeline (`scripts/extract_nta_papers.py`) — no LLM, no DB writes.
Raw layer only: no answers fabricated, nothing marked servable; defects are flagged.

## Manifest

- entries: 189
- mirror: 180
- official: 9
- probed OK: 189

## Per-paper extraction results

| paper_id | exam_tag | format | status | questions | answer_sheet | flagged | defects |
|---|---|---|---|---|---|---|---|
| jee-main-2022-s2-2022-06-24-shift-1 | jee-main | generic_mirror | extracted | 59 | embedded_unverified | 59 | 64 question markers skipped as out-of-order (text-layer reading order scrambled; likely lost questions): [2, 8, 1, 1, 2, |
| jee-main-2022-s2-2022-06-25-shift-1-2 | jee-main | - | needs_ocr | 0 | official_key_pending | 0 | no usable text layer; OCR deferred per task scope |
| jee-main-2022-s2-2022-06-25-shift-1-3 | jee-main | generic_mirror | parse_failed | 0 | official_key_pending | 0 | text layer present but no question blocks matched any known layout; paper may be solutions-only, image-based, or an unre |
| jee-main-2022-s2-2022-06-25-shift-1 | jee-main | - | needs_ocr | 0 | official_key_pending | 0 | no usable text layer; OCR deferred per task scope |
| jee-main-2022-s2-2022-06-25-shift-2-2 | jee-main | generic_mirror | parse_failed | 0 | official_key_pending | 0 | text layer present but no question blocks matched any known layout; paper may be solutions-only, image-based, or an unre |
| jee-main-2022-s2-2022-06-25-shift-2-3 | jee-main | generic_mirror | parse_failed | 0 | official_key_pending | 0 | text layer present but no question blocks matched any known layout; paper may be solutions-only, image-based, or an unre |
| jee-main-2022-s2-2022-06-25-shift-2 | jee-main | - | needs_ocr | 0 | official_key_pending | 0 | no usable text layer; OCR deferred per task scope |
| jee-main-2022-s2-2022-06-26-shift-1-2 | jee-main | generic_mirror | parse_failed | 0 | official_key_pending | 0 | text layer present but no question blocks matched any known layout; paper may be solutions-only, image-based, or an unre |
| jee-main-2022-s2-2022-06-26-shift-1-3 | jee-main | - | needs_ocr | 0 | official_key_pending | 0 | no usable text layer; OCR deferred per task scope |
| jee-main-2022-s2-2022-06-26-shift-1 | jee-main | - | needs_ocr | 0 | official_key_pending | 0 | no usable text layer; OCR deferred per task scope |
| jee-main-2022-s2-2022-06-26-shift-2-2 | jee-main | - | needs_ocr | 0 | official_key_pending | 0 | no usable text layer; OCR deferred per task scope |
| jee-main-2022-s2-2022-06-26-shift-2-3 | jee-main | - | needs_ocr | 0 | official_key_pending | 0 | no usable text layer; OCR deferred per task scope |
| jee-main-2022-s2-2022-06-26-shift-2 | jee-main | - | needs_ocr | 0 | official_key_pending | 0 | no usable text layer; OCR deferred per task scope |
| jee-main-2022-s2-2022-06-27-shift-1-2 | jee-main | - | needs_ocr | 0 | official_key_pending | 0 | no usable text layer; OCR deferred per task scope |
| jee-main-2022-s2-2022-06-27-shift-1-3 | jee-main | generic_mirror | parse_failed | 0 | official_key_pending | 0 | text layer present but no question blocks matched any known layout; paper may be solutions-only, image-based, or an unre |
| jee-main-2022-s2-2022-06-27-shift-1 | jee-main | - | needs_ocr | 0 | official_key_pending | 0 | no usable text layer; OCR deferred per task scope |
| jee-main-2022-s2-2022-06-27-shift-2-2 | jee-main | - | needs_ocr | 0 | official_key_pending | 0 | no usable text layer; OCR deferred per task scope |
| jee-main-2022-s2-2022-06-27-shift-2-3 | jee-main | - | needs_ocr | 0 | official_key_pending | 0 | no usable text layer; OCR deferred per task scope |
| jee-main-2022-s2-2022-06-27-shift-2 | jee-main | - | needs_ocr | 0 | official_key_pending | 0 | no usable text layer; OCR deferred per task scope |
| jee-main-2022-s2-2022-06-28-shift-1-2 | jee-main | generic_mirror | parse_failed | 0 | official_key_pending | 0 | text layer present but no question blocks matched any known layout; paper may be solutions-only, image-based, or an unre |
| jee-main-2022-s2-2022-06-28-shift-1-3 | jee-main | - | needs_ocr | 0 | official_key_pending | 0 | no usable text layer; OCR deferred per task scope |
| jee-main-2022-s2-2022-06-28-shift-1 | jee-main | - | needs_ocr | 0 | official_key_pending | 0 | no usable text layer; OCR deferred per task scope |
| jee-main-2022-s2-2022-06-28-shift-2-2 | jee-main | - | needs_ocr | 0 | official_key_pending | 0 | no usable text layer; OCR deferred per task scope |
| jee-main-2022-s2-2022-06-28-shift-2-3 | jee-main | generic_mirror | parse_failed | 0 | official_key_pending | 0 | text layer present but no question blocks matched any known layout; paper may be solutions-only, image-based, or an unre |
| jee-main-2022-s2-2022-06-28-shift-2 | jee-main | - | needs_ocr | 0 | official_key_pending | 0 | no usable text layer; OCR deferred per task scope |
| jee-main-2022-s2-2022-06-29-shift-1-2 | jee-main | - | needs_ocr | 0 | official_key_pending | 0 | no usable text layer; OCR deferred per task scope |
| jee-main-2022-s2-2022-06-29-shift-1-3 | jee-main | - | needs_ocr | 0 | official_key_pending | 0 | no usable text layer; OCR deferred per task scope |
| jee-main-2022-s2-2022-06-29-shift-1 | jee-main | - | needs_ocr | 0 | official_key_pending | 0 | no usable text layer; OCR deferred per task scope |
| jee-main-2022-s2-2022-06-29-shift-2-2 | jee-main | - | needs_ocr | 0 | official_key_pending | 0 | no usable text layer; OCR deferred per task scope |
| jee-main-2022-s2-2022-06-29-shift-2-3 | jee-main | generic_mirror | parse_failed | 0 | official_key_pending | 0 | text layer present but no question blocks matched any known layout; paper may be solutions-only, image-based, or an unre |
| jee-main-2022-s2-2022-06-29-shift-2 | jee-main | generic_mirror | parse_failed | 0 | official_key_pending | 0 | text layer present but no question blocks matched any known layout; paper may be solutions-only, image-based, or an unre |
| jee-main-2022-s2-2022-07-25-shift-1-2 | jee-main | generic_mirror | parse_failed | 0 | official_key_pending | 0 | text layer present but no question blocks matched any known layout; paper may be solutions-only, image-based, or an unre |
| jee-main-2022-s2-2022-07-25-shift-1-3 | jee-main | generic_mirror | parse_failed | 0 | official_key_pending | 0 | text layer present but no question blocks matched any known layout; paper may be solutions-only, image-based, or an unre |
| jee-main-2022-s2-2022-07-25-shift-1 | jee-main | generic_mirror | extracted | 20 | embedded_unverified | 20 | 13 question markers skipped as out-of-order (text-layer reading order scrambled; likely lost questions): [1, 2, 0, 1, 0, |
| jee-main-2022-s2-2022-07-25-shift-2-2 | jee-main | - | needs_ocr | 0 | official_key_pending | 0 | no usable text layer; OCR deferred per task scope |
| jee-main-2022-s2-2022-07-25-shift-2-3 | jee-main | generic_mirror | parse_failed | 0 | official_key_pending | 0 | text layer present but no question blocks matched any known layout; paper may be solutions-only, image-based, or an unre |
| jee-main-2022-s2-2022-07-25-shift-2 | jee-main | generic_mirror | extracted | 15 | embedded_unverified | 15 | 13 question markers skipped as out-of-order (text-layer reading order scrambled; likely lost questions): [3, 1, 2, 3, 4, |
| jee-main-2022-s2-2022-07-26-shift-1-2 | jee-main | generic_mirror | parse_failed | 0 | official_key_pending | 0 | text layer present but no question blocks matched any known layout; paper may be solutions-only, image-based, or an unre |
| jee-main-2022-s2-2022-07-26-shift-1-3 | jee-main | - | needs_ocr | 0 | official_key_pending | 0 | no usable text layer; OCR deferred per task scope |
| jee-main-2022-s2-2022-07-26-shift-1 | jee-main | generic_mirror | extracted | 20 | embedded_unverified | 20 | 14 question markers skipped as out-of-order (text-layer reading order scrambled; likely lost questions): [4, 4, 2, 2, 1, |
| jee-main-2022-s2-2022-07-26-shift-2-2 | jee-main | generic_mirror | parse_failed | 0 | official_key_pending | 0 | text layer present but no question blocks matched any known layout; paper may be solutions-only, image-based, or an unre |
| jee-main-2022-s2-2022-07-26-shift-2-3 | jee-main | generic_mirror | parse_failed | 0 | official_key_pending | 0 | text layer present but no question blocks matched any known layout; paper may be solutions-only, image-based, or an unre |
| jee-main-2022-s2-2022-07-26-shift-2 | jee-main | generic_mirror | extracted | 18 | embedded_unverified | 18 | 11 question markers skipped as out-of-order (text-layer reading order scrambled; likely lost questions): [15, 1, 2, 3, 4 |
| jee-main-2022-s2-2022-07-27-shift-1-2 | jee-main | generic_mirror | parse_failed | 0 | official_key_pending | 0 | text layer present but no question blocks matched any known layout; paper may be solutions-only, image-based, or an unre |
| jee-main-2022-s2-2022-07-27-shift-1-3 | jee-main | generic_mirror | parse_failed | 0 | official_key_pending | 0 | text layer present but no question blocks matched any known layout; paper may be solutions-only, image-based, or an unre |
| jee-main-2022-s2-2022-07-27-shift-1 | jee-main | generic_mirror | extracted | 19 | embedded_unverified | 19 | 14 question markers skipped as out-of-order (text-layer reading order scrambled; likely lost questions): [10, 2, 2, 1, 2 |
| jee-main-2022-s2-2022-07-27-shift-2-2 | jee-main | generic_mirror | parse_failed | 0 | official_key_pending | 0 | text layer present but no question blocks matched any known layout; paper may be solutions-only, image-based, or an unre |
| jee-main-2022-s2-2022-07-27-shift-2-3 | jee-main | generic_mirror | parse_failed | 0 | official_key_pending | 0 | text layer present but no question blocks matched any known layout; paper may be solutions-only, image-based, or an unre |
| jee-main-2022-s2-2022-07-27-shift-2 | jee-main | generic_mirror | parse_failed | 0 | official_key_pending | 0 | text layer present but no question blocks matched any known layout; paper may be solutions-only, image-based, or an unre |
| jee-main-2022-s2-2022-07-28-shift-1-2 | jee-main | generic_mirror | parse_failed | 0 | official_key_pending | 0 | text layer present but no question blocks matched any known layout; paper may be solutions-only, image-based, or an unre |
| jee-main-2022-s2-2022-07-28-shift-1-3 | jee-main | generic_mirror | parse_failed | 0 | official_key_pending | 0 | text layer present but no question blocks matched any known layout; paper may be solutions-only, image-based, or an unre |
| jee-main-2022-s2-2022-07-28-shift-1 | jee-main | generic_mirror | extracted | 18 | embedded_unverified | 18 | 12 question markers skipped as out-of-order (text-layer reading order scrambled; likely lost questions): [7, 12, 1, 2, 4 |
| jee-main-2022-s2-2022-07-28-shift-2-2 | jee-main | generic_mirror | parse_failed | 0 | official_key_pending | 0 | text layer present but no question blocks matched any known layout; paper may be solutions-only, image-based, or an unre |
| jee-main-2022-s2-2022-07-28-shift-2-3 | jee-main | generic_mirror | extracted | 2 | official_key_pending | 2 | 2/2 questions carry parse_flags |
| jee-main-2022-s2-2022-07-28-shift-2 | jee-main | generic_mirror | extracted | 19 | embedded_unverified | 19 | 24 question markers skipped as out-of-order (text-layer reading order scrambled; likely lost questions): [1, 1, 1, 5, 5, |
| jee-main-2022-s2-2022-07-29-shift-1-2 | jee-main | generic_mirror | parse_failed | 0 | official_key_pending | 0 | text layer present but no question blocks matched any known layout; paper may be solutions-only, image-based, or an unre |
| jee-main-2022-s2-2022-07-29-shift-1-3 | jee-main | generic_mirror | parse_failed | 0 | official_key_pending | 0 | text layer present but no question blocks matched any known layout; paper may be solutions-only, image-based, or an unre |
| jee-main-2022-s2-2022-07-29-shift-1 | jee-main | generic_mirror | extracted | 19 | embedded_unverified | 19 | 14 question markers skipped as out-of-order (text-layer reading order scrambled; likely lost questions): [17, 2, 1, 2, 2 |
| jee-main-2022-s2-2022-07-29-shift-2-2 | jee-main | generic_mirror | parse_failed | 0 | official_key_pending | 0 | text layer present but no question blocks matched any known layout; paper may be solutions-only, image-based, or an unre |
| jee-main-2022-s2-2022-07-29-shift-2-3 | jee-main | generic_mirror | parse_failed | 0 | official_key_pending | 0 | text layer present but no question blocks matched any known layout; paper may be solutions-only, image-based, or an unre |
| jee-main-2022-s2-2022-07-29-shift-2 | jee-main | generic_mirror | extracted | 19 | embedded_unverified | 19 | 11 question markers skipped as out-of-order (text-layer reading order scrambled; likely lost questions): [4, 1, 2, 3, 4, |
| jee-main-2023-s1-2023-01-24-shift-1-2 | jee-main | generic_mirror | extracted | 30 | embedded_unverified | 30 | 1 question markers skipped as out-of-order (text-layer reading order scrambled; likely lost questions): [2]; 30/30 quest |
| jee-main-2023-s1-2023-01-24-shift-1-3 | jee-main | generic_mirror | extracted | 30 | embedded_unverified | 30 | 4 question markers skipped as out-of-order (text-layer reading order scrambled; likely lost questions): [2, 2, 2, 2]; 30 |
| jee-main-2023-s1-2023-01-24-shift-1 | jee-main | generic_mirror | extracted | 30 | embedded_unverified | 30 | 37 question markers skipped as out-of-order (text-layer reading order scrambled; likely lost questions): [1, 3, 3, 7, 2, |
| jee-main-2023-s1-2023-01-24-shift-2-2 | jee-main | generic_mirror | extracted | 30 | embedded_unverified | 30 | 3 question markers skipped as out-of-order (text-layer reading order scrambled; likely lost questions): [3, 7, 0]; 30/30 |
| jee-main-2023-s1-2023-01-24-shift-2-3 | jee-main | generic_mirror | extracted | 29 | embedded_unverified | 29 | 1 question markers skipped as out-of-order (text-layer reading order scrambled; likely lost questions): [7]; 29/29 quest |
| jee-main-2023-s1-2023-01-24-shift-2 | jee-main | generic_mirror | extracted | 30 | embedded_unverified | 30 | 4 question markers skipped as out-of-order (text-layer reading order scrambled; likely lost questions): [2, 2, 2, 1]; 30 |
| jee-main-2023-s1-2023-01-25-shift-1-2 | jee-main | generic_mirror | extracted | 30 | embedded_unverified | 30 | 1 question markers skipped as out-of-order (text-layer reading order scrambled; likely lost questions): [2]; 30/30 quest |
| jee-main-2023-s1-2023-01-25-shift-1-3 | jee-main | generic_mirror | extracted | 30 | embedded_unverified | 30 | 1 question markers skipped as out-of-order (text-layer reading order scrambled; likely lost questions): [0]; 30/30 quest |
| jee-main-2023-s1-2023-01-25-shift-1 | jee-main | generic_mirror | extracted | 30 | embedded_unverified | 30 | 26 question markers skipped as out-of-order (text-layer reading order scrambled; likely lost questions): [2, 1, 1, 1, 1, |
| jee-main-2023-s1-2023-01-25-shift-2-2 | jee-main | generic_mirror | extracted | 30 | embedded_unverified | 30 | 7 question markers skipped as out-of-order (text-layer reading order scrambled; likely lost questions): [0, 0, 2, 2, 2,  |
| jee-main-2023-s1-2023-01-25-shift-2-3 | jee-main | generic_mirror | extracted | 30 | embedded_unverified | 30 | 30/30 questions carry parse_flags |
| jee-main-2023-s1-2023-01-25-shift-2 | jee-main | generic_mirror | extracted | 30 | embedded_unverified | 30 | 4 question markers skipped as out-of-order (text-layer reading order scrambled; likely lost questions): [1, 1, 0, 48]; 3 |
| jee-main-2023-s1-2023-01-29-shift-1-2 | jee-main | generic_mirror | extracted | 30 | embedded_unverified | 30 | 1 question markers skipped as out-of-order (text-layer reading order scrambled; likely lost questions): [4]; 30/30 quest |
| jee-main-2023-s1-2023-01-29-shift-1-3 | jee-main | generic_mirror | extracted | 29 | embedded_unverified | 29 | 1 question markers skipped as out-of-order (text-layer reading order scrambled; likely lost questions): [47]; 29/29 ques |
| jee-main-2023-s1-2023-01-29-shift-1 | jee-main | generic_mirror | extracted | 30 | embedded_unverified | 30 | 12 question markers skipped as out-of-order (text-layer reading order scrambled; likely lost questions): [16, 1, 1, 1, 1 |
| jee-main-2023-s1-2023-01-29-shift-2-2 | jee-main | generic_mirror | extracted | 30 | embedded_unverified | 30 | 1 question markers skipped as out-of-order (text-layer reading order scrambled; likely lost questions): [0]; 30/30 quest |
| jee-main-2023-s1-2023-01-29-shift-2-3 | jee-main | generic_mirror | extracted | 30 | embedded_unverified | 30 | 30/30 questions carry parse_flags |
| jee-main-2023-s1-2023-01-29-shift-2 | jee-main | generic_mirror | extracted | 29 | embedded_unverified | 29 | 17 question markers skipped as out-of-order (text-layer reading order scrambled; likely lost questions): [1, 4, 5, 3, 4, |
| jee-main-2023-s1-2023-01-30-shift-1-2 | jee-main | generic_mirror | extracted | 30 | embedded_unverified | 30 | 3 question markers skipped as out-of-order (text-layer reading order scrambled; likely lost questions): [0, 5, 15]; 30/3 |
| jee-main-2023-s1-2023-01-30-shift-1-3 | jee-main | generic_mirror | extracted | 30 | embedded_unverified | 30 | 3 question markers skipped as out-of-order (text-layer reading order scrambled; likely lost questions): [2, 3, 4]; 30/30 |
| jee-main-2023-s1-2023-01-30-shift-1 | jee-main | generic_mirror | extracted | 26 | embedded_unverified | 26 | 16 question markers skipped as out-of-order (text-layer reading order scrambled; likely lost questions): [3, 1, 1, 1, 3, |
| jee-main-2023-s1-2023-01-30-shift-2-2 | jee-main | generic_mirror | extracted | 10 | embedded_unverified | 10 | 21 question markers skipped as out-of-order (text-layer reading order scrambled; likely lost questions): [11, 12, 13, 14 |
| jee-main-2023-s1-2023-01-30-shift-2-3 | jee-main | generic_mirror | extracted | 30 | embedded_unverified | 30 | 30/30 questions carry parse_flags |
| jee-main-2023-s1-2023-01-30-shift-2 | jee-main | generic_mirror | extracted | 30 | embedded_unverified | 30 | 3 question markers skipped as out-of-order (text-layer reading order scrambled; likely lost questions): [9, 2, 1]; 30/30 |
| jee-main-2023-s1-2023-01-31-shift-1-2 | jee-main | generic_mirror | extracted | 21 | embedded_unverified | 21 | 12 question markers skipped as out-of-order (text-layer reading order scrambled; likely lost questions): [22, 23, 24, 1, |
| jee-main-2023-s1-2023-01-31-shift-1-3 | jee-main | generic_mirror | extracted | 26 | embedded_unverified | 26 | 6 question markers skipped as out-of-order (text-layer reading order scrambled; likely lost questions): [43, 51, 1, 2, 3 |
| jee-main-2023-s1-2023-01-31-shift-1 | jee-main | generic_mirror | extracted | 27 | embedded_unverified | 27 | 9 question markers skipped as out-of-order (text-layer reading order scrambled; likely lost questions): [4, 1, 0, 3, 0,  |
| jee-main-2023-s1-2023-01-31-shift-2-2 | jee-main | generic_mirror | extracted | 30 | embedded_unverified | 30 | 30/30 questions carry parse_flags |
| jee-main-2023-s1-2023-01-31-shift-2-3 | jee-main | generic_mirror | extracted | 28 | embedded_unverified | 28 | 5 question markers skipped as out-of-order (text-layer reading order scrambled; likely lost questions): [2, 3, 4, 5, 50] |
| jee-main-2023-s1-2023-01-31-shift-2 | jee-main | generic_mirror | extracted | 30 | embedded_unverified | 30 | 17 question markers skipped as out-of-order (text-layer reading order scrambled; likely lost questions): [1, 1, 2, 1, 2, |
| jee-main-2023-s1-2023-02-01-shift-1-2 | jee-main | generic_mirror | extracted | 29 | embedded_unverified | 29 | 29/29 questions carry parse_flags |
| jee-main-2023-s1-2023-02-01-shift-1-3 | jee-main | generic_mirror | extracted | 30 | embedded_unverified | 30 | 2 question markers skipped as out-of-order (text-layer reading order scrambled; likely lost questions): [1, 2]; 30/30 qu |
| jee-main-2023-s1-2023-02-01-shift-1 | jee-main | generic_mirror | extracted | 24 | embedded_unverified | 24 | 14 question markers skipped as out-of-order (text-layer reading order scrambled; likely lost questions): [3, 1, 1, 1, 10 |
| jee-main-2023-s1-2023-02-01-shift-2-2 | jee-main | generic_mirror | extracted | 25 | embedded_unverified | 25 | 7 question markers skipped as out-of-order (text-layer reading order scrambled; likely lost questions): [1, 3, 2, 3, 4,  |
| jee-main-2023-s1-2023-02-01-shift-2-3 | jee-main | generic_mirror | extracted | 30 | embedded_unverified | 30 | 30/30 questions carry parse_flags |
| jee-main-2023-s1-2023-02-01-shift-2 | jee-main | generic_mirror | extracted | 30 | embedded_unverified | 30 | 7 question markers skipped as out-of-order (text-layer reading order scrambled; likely lost questions): [2, 2, 2, 12, 3, |
| jee-main-2023-s2-2023-04-06-shift-1-2 | jee-main | generic_mirror | extracted | 30 | embedded_unverified | 30 | 30/30 questions carry parse_flags |
| jee-main-2023-s2-2023-04-06-shift-1 | jee-main | generic_mirror | extracted | 7 | embedded_unverified | 7 | 24 question markers skipped as out-of-order (text-layer reading order scrambled; likely lost questions): [38, 39, 40, 41 |
| jee-main-2023-s2-2023-04-06-shift-2-2 | jee-main | generic_mirror | extracted | 30 | embedded_unverified | 30 | 30/30 questions carry parse_flags |
| jee-main-2023-s2-2023-04-06-shift-2 | jee-main | generic_mirror | extracted | 30 | embedded_unverified | 30 | 4 question markers skipped as out-of-order (text-layer reading order scrambled; likely lost questions): [40, 10, 4, 22]; |
| jee-main-2023-s2-2023-04-08-shift-1-2 | jee-main | generic_mirror | extracted | 30 | embedded_unverified | 30 | 4 question markers skipped as out-of-order (text-layer reading order scrambled; likely lost questions): [2, 8, 1, 1]; 30 |
| jee-main-2023-s2-2023-04-08-shift-1-3 | jee-main | generic_mirror | extracted | 29 | embedded_unverified | 29 | 29/29 questions carry parse_flags |
| jee-main-2023-s2-2023-04-08-shift-1 | jee-main | generic_mirror | extracted | 30 | embedded_unverified | 30 | 6 question markers skipped as out-of-order (text-layer reading order scrambled; likely lost questions): [1, 1, 1, 1, 1,  |
| jee-main-2023-s2-2023-04-08-shift-2-2 | jee-main | generic_mirror | extracted | 12 | embedded_unverified | 12 | 21 question markers skipped as out-of-order (text-layer reading order scrambled; likely lost questions): [43, 44, 45, 46 |
| jee-main-2023-s2-2023-04-08-shift-2-3 | jee-main | generic_mirror | extracted | 30 | embedded_unverified | 30 | 30/30 questions carry parse_flags |
| jee-main-2023-s2-2023-04-08-shift-2 | jee-main | generic_mirror | extracted | 30 | embedded_unverified | 30 | 30/30 questions carry parse_flags |
| jee-main-2023-s2-2023-04-10-shift-1-2 | jee-main | generic_mirror | parse_failed | 0 | official_key_pending | 0 | text layer present but no question blocks matched any known layout; paper may be solutions-only, image-based, or an unre |
| jee-main-2023-s2-2023-04-10-shift-1 | jee-main | generic_mirror | extracted | 30 | embedded_unverified | 30 | 4 question markers skipped as out-of-order (text-layer reading order scrambled; likely lost questions): [2, 3, 4, 1]; 30 |
| jee-main-2023-s2-2023-04-10-shift-2-2 | jee-main | generic_mirror | extracted | 30 | embedded_unverified | 30 | 1 question markers skipped as out-of-order (text-layer reading order scrambled; likely lost questions): [2]; 30/30 quest |
| jee-main-2023-s2-2023-04-10-shift-2-3 | jee-main | generic_mirror | extracted | 30 | embedded_unverified | 30 | 3 question markers skipped as out-of-order (text-layer reading order scrambled; likely lost questions): [1, 2, 3]; 30/30 |
| jee-main-2023-s2-2023-04-10-shift-2 | jee-main | generic_mirror | extracted | 2 | embedded_unverified | 2 | 88 question markers skipped as out-of-order (text-layer reading order scrambled; likely lost questions): [1, 2, 3, 2, 0, |
| jee-main-2023-s2-2023-04-11-shift-1-2 | jee-main | generic_mirror | extracted | 30 | embedded_unverified | 30 | 2 question markers skipped as out-of-order (text-layer reading order scrambled; likely lost questions): [2, 2]; 30/30 qu |
| jee-main-2023-s2-2023-04-11-shift-1 | jee-main | generic_mirror | extracted | 30 | embedded_unverified | 30 | 2 question markers skipped as out-of-order (text-layer reading order scrambled; likely lost questions): [1, 4]; 30/30 qu |
| jee-main-2023-s2-2023-04-11-shift-2-2 | jee-main | generic_mirror | extracted | 30 | embedded_unverified | 30 | 4 question markers skipped as out-of-order (text-layer reading order scrambled; likely lost questions): [2, 2, 2, 2]; 30 |
| jee-main-2023-s2-2023-04-11-shift-2 | jee-main | generic_mirror | extracted | 30 | embedded_unverified | 30 | 30/30 questions carry parse_flags |
| jee-main-2023-s2-2023-04-12-shift-1 | jee-main | generic_mirror | parse_failed | 0 | official_key_pending | 0 | text layer present but no question blocks matched any known layout; paper may be solutions-only, image-based, or an unre |
| jee-main-2023-s2-2023-04-13-shift-1-2 | jee-main | generic_mirror | extracted | 30 | embedded_unverified | 30 | 30/30 questions carry parse_flags |
| jee-main-2023-s2-2023-04-13-shift-1 | jee-main | generic_mirror | extracted | 30 | embedded_unverified | 30 | 3 question markers skipped as out-of-order (text-layer reading order scrambled; likely lost questions): [7, 10, 5]; 30/3 |
| jee-main-2023-s2-2023-04-13-shift-2-2 | jee-main | generic_mirror | extracted | 30 | embedded_unverified | 30 | 4 question markers skipped as out-of-order (text-layer reading order scrambled; likely lost questions): [1, 2, 3, 4]; 30 |
| jee-main-2023-s2-2023-04-13-shift-2 | jee-main | generic_mirror | extracted | 30 | embedded_unverified | 30 | 30/30 questions carry parse_flags |
| jee-main-2023-s2-2023-04-15-shift-1-2 | jee-main | generic_mirror | extracted | 30 | embedded_unverified | 30 | 30/30 questions carry parse_flags |
| jee-main-2023-s2-2023-04-15-shift-1 | jee-main | generic_mirror | extracted | 30 | embedded_unverified | 30 | 3 question markers skipped as out-of-order (text-layer reading order scrambled; likely lost questions): [2, 2, 4]; 30/30 |
| jee-main-2023-shift-1-16114-maths-6-4-2023-20shift-201 | jee-main | generic_mirror | extracted | 30 | embedded_unverified | 30 | 5 question markers skipped as out-of-order (text-layer reading order scrambled; likely lost questions): [2, 2, 3, 3, 1]; |
| jee-main-2023-shift-1-161445-maths-10-4-2023-20shift-201 | jee-main | generic_mirror | extracted | 30 | embedded_unverified | 30 | 7 question markers skipped as out-of-order (text-layer reading order scrambled; likely lost questions): [2, 1, 1, 1, 1,  |
| jee-main-2023-shift-1-161552-maths-11-4-2023-20shift-201 | jee-main | generic_mirror | extracted | 30 | embedded_unverified | 30 | 4 question markers skipped as out-of-order (text-layer reading order scrambled; likely lost questions): [4, 1, 1, 1]; 30 |
| jee-main-2023-shift-1-161645-1204-mathematics-paper-with-sol-morning | jee-main | - | needs_ocr | 0 | unavailable | 0 | no usable text layer; OCR deferred per task scope |
| jee-main-2023-shift-1-161752-maths-20-13-4-2023-20shift-201 | jee-main | generic_mirror | extracted | 19 | embedded_unverified | 19 | 33 question markers skipped as out-of-order (text-layer reading order scrambled; likely lost questions): [1, 9, 10, 11,  |
| jee-main-2023-shift-1-161823-maths-20-15-4-2023-20shift-201 | jee-main | generic_mirror | extracted | 30 | embedded_unverified | 30 | 3 question markers skipped as out-of-order (text-layer reading order scrambled; likely lost questions): [2, 2, 3]; 30/30 |
| jee-main-2023-shift-1-164150-1204-chemistry-paper-with-sol-morning | jee-main | - | needs_ocr | 0 | unavailable | 0 | no usable text layer; OCR deferred per task scope |
| jee-main-2023-shift-2-16130-maths-6-4-2023-20shift-202 | jee-main | generic_mirror | extracted | 29 | embedded_unverified | 29 | 2 question markers skipped as out-of-order (text-layer reading order scrambled; likely lost questions): [2, 2]; 29/29 qu |
| jee-main-2023-shift-2-161612-maths-11-4-2023-shift-202 | jee-main | generic_mirror | extracted | 30 | embedded_unverified | 30 | 3 question markers skipped as out-of-order (text-layer reading order scrambled; likely lost questions): [2, 5, 4]; 30/30 |
| jee-main-2023-shift-2-16187-maths-20-13-4-2023-20shift-202 | jee-main | generic_mirror | extracted | 9 | embedded_unverified | 9 | 33 question markers skipped as out-of-order (text-layer reading order scrambled; likely lost questions): [2, 1, 3, 35, 1 |
| jee-main-2024-111843-jee-main-chemistry-2024-question-papers-with-answer-k | jee-main | generic_mirror | extracted | 30 | embedded_unverified | 30 | 30/30 questions carry parse_flags |
| jee-main-2024-112028-jee-main-2024-physics-question-papers-with-answer-key | jee-main | generic_mirror | extracted | 30 | embedded_unverified | 30 | 2 question markers skipped as out-of-order (text-layer reading order scrambled; likely lost questions): [1, 5]; 30/30 qu |
| jee-main-2024-112154-jee-main-2024-maths-question-papers-with-answer-key-p | jee-main | generic_mirror | extracted | 10 | embedded_unverified | 10 | 34 question markers skipped as out-of-order (text-layer reading order scrambled; likely lost questions): [2, 3, 4, 4, 3, |
| jee-main-2024-131142-physics-jee-main-2024-question-papers-with-answer-key | jee-main | generic_mirror | extracted | 30 | embedded_unverified | 30 | 13 question markers skipped as out-of-order (text-layer reading order scrambled; likely lost questions): [1, 2, 1, 1, 1, |
| jee-main-2024-13135-chemistry-jee-main-2024-question-papers-with-answer-ke | jee-main | generic_mirror | extracted | 30 | embedded_unverified | 30 | 30/30 questions carry parse_flags |
| jee-main-2024-131418-maths-jee-main-2024-question-papers-with-answer-20key | jee-main | generic_mirror | extracted | 29 | embedded_unverified | 29 | 10 question markers skipped as out-of-order (text-layer reading order scrambled; likely lost questions): [1, 1, 1, 1, 1, |
| jee-main-2024-171134-physics-jee-mains-2024-question-papers-with-answer-ke | jee-main | generic_mirror | extracted | 24 | embedded_unverified | 24 | 2 question markers skipped as out-of-order (text-layer reading order scrambled; likely lost questions): [7, 22]; 24/24 q |
| jee-main-2024-171231-chemistry-jee-mains-2024-question-papers-with-answer | jee-main | generic_mirror | extracted | 28 | embedded_unverified | 28 | 1 question markers skipped as out-of-order (text-layer reading order scrambled; likely lost questions): [20]; 28/28 ques |
| jee-main-2024-17950-maths-jee-mains-2024-question-papers-with-answer-key-p | jee-main | generic_mirror | extracted | 20 | embedded_unverified | 20 | 14 question markers skipped as out-of-order (text-layer reading order scrambled; likely lost questions): [1, 3, 1, 14, 1 |
| jee-main-2024-182028-physics-jee-mains-2024-question-papers-with-answer-ke | jee-main | - | needs_ocr | 0 | unavailable | 0 | no usable text layer; OCR deferred per task scope |
| jee-main-2024-182148-chemistry-jee-mains-2024-question-papers-with-answer | jee-main | generic_mirror | parse_failed | 0 | unavailable | 0 | text layer present but no question blocks matched any known layout; paper may be solutions-only, image-based, or an unre |
| jee-main-2024-18231-maths-jee-mains-2024-question-papers-with-answer-key-p | jee-main | generic_mirror | extracted | 29 | embedded_unverified | 29 | 4 question markers skipped as out-of-order (text-layer reading order scrambled; likely lost questions): [3, 1, 1, 5]; 29 |
| jee-main-2024-s1-2024-01-27-shift-2-2 | jee-main | generic_mirror | extracted | 10 | embedded_unverified | 10 | 10/10 questions carry parse_flags |
| jee-main-2024-s1-2024-01-27-shift-2-3 | jee-main | generic_mirror | extracted | 6 | embedded_unverified | 6 | 6/6 questions carry parse_flags |
| jee-main-2024-s1-2024-01-27-shift-2 | jee-main | generic_mirror | extracted | 20 | embedded_unverified | 20 | 20/20 questions carry parse_flags |
| jee-main-2024-s1-2024-01-29-shift-2-2 | jee-main | generic_mirror | extracted | 6 | embedded_unverified | 6 | 6/6 questions carry parse_flags |
| jee-main-2024-s1-2024-01-29-shift-2-3 | jee-main | generic_mirror | extracted | 6 | official_key_pending | 6 | 6/6 questions carry parse_flags |
| jee-main-2024-s1-2024-01-29-shift-2 | jee-main | generic_mirror | extracted | 20 | embedded_unverified | 20 | 20/20 questions carry parse_flags |
| jee-main-2024-s1-2024-01-30-shift-2-2 | jee-main | generic_mirror | extracted | 4 | embedded_unverified | 4 | 4/4 questions carry parse_flags |
| jee-main-2024-s1-2024-01-30-shift-2-3 | jee-main | generic_mirror | extracted | 7 | embedded_unverified | 7 | 1 question markers skipped as out-of-order (text-layer reading order scrambled; likely lost questions): [2]; 7/7 questio |
| jee-main-2024-s1-2024-01-30-shift-2 | jee-main | generic_mirror | extracted | 16 | embedded_unverified | 16 | 16/16 questions carry parse_flags |
| jee-main-2024-s1-2024-01-31-shift-1-2 | jee-main | generic_mirror | extracted | 14 | embedded_unverified | 14 | 14/14 questions carry parse_flags |
| jee-main-2024-s1-2024-01-31-shift-1-3 | jee-main | generic_mirror | extracted | 5 | embedded_unverified | 5 | 5/5 questions carry parse_flags |
| jee-main-2024-s1-2024-01-31-shift-1 | jee-main | generic_mirror | extracted | 26 | embedded_unverified | 26 | 1 question markers skipped as out-of-order (text-layer reading order scrambled; likely lost questions): [2]; 26/26 quest |
| jee-main-2024-s1-2024-02-01-2 | jee-main | generic_mirror | parse_failed | 0 | official_key_pending | 0 | text layer present but no question blocks matched any known layout; paper may be solutions-only, image-based, or an unre |
| jee-main-2024-s1-2024-02-01-3 | jee-main | generic_mirror | parse_failed | 0 | official_key_pending | 0 | text layer present but no question blocks matched any known layout; paper may be solutions-only, image-based, or an unre |
| jee-main-2024-s1-2024-02-01 | jee-main | generic_mirror | parse_failed | 0 | official_key_pending | 0 | text layer present but no question blocks matched any known layout; paper may be solutions-only, image-based, or an unre |
| jee-main-2024-s2-2024-04-05-shift-1 | jee-main | generic_mirror | extracted | 36 | embedded_unverified | 36 | 18 question markers skipped as out-of-order (text-layer reading order scrambled; likely lost questions): [4, 6, 11, 12,  |
| jee-main-2024-s2-2024-04-05-shift-2 | jee-main | generic_mirror | extracted | 25 | embedded_unverified | 25 | 25/25 questions carry parse_flags |
| jee-main-2024-s2-2024-04-06-shift-1 | jee-main | generic_mirror | extracted | 61 | embedded_unverified | 61 | 17 question markers skipped as out-of-order (text-layer reading order scrambled; likely lost questions): [1, 2, 3, 4, 5, |
| jee-main-2024-s2-2024-04-06-shift-2 | jee-main | generic_mirror | extracted | 21 | embedded_unverified | 21 | 21/21 questions carry parse_flags |
| jee-main-2024-s2-2024-04-08-shift-1-2 | jee-main | generic_mirror | extracted | 26 | official_key_pending | 26 | 1 question markers skipped as out-of-order (text-layer reading order scrambled; likely lost questions): [100]; 26/26 que |
| jee-main-2024-s2-2024-04-08-shift-1 | jee-main | generic_mirror | extracted | 45 | official_key_pending | 45 | 45/45 questions carry parse_flags |
| jee-main-2024-s2-2024-04-09-shift-1 | jee-main | generic_mirror | extracted | 69 | official_key_pending | 69 | 69/69 questions carry parse_flags |
| jee-main-2024-s2-2024-04-09-shift-2 | jee-main | generic_mirror | extracted | 22 | official_key_pending | 22 | 22/22 questions carry parse_flags |
| jee-main-2024-s2-shift-1-152832-4th-april-2024-morning-shift-1-faculty-copy | jee-main | generic_mirror | extracted | 26 | embedded_unverified | 26 | 4 question markers skipped as out-of-order (text-layer reading order scrambled; likely lost questions): [2, 3, 3, 3]; 26 |
| jee-main-2024-s2-shift-2-152848-4th-april-2024-evening-shift-2-faculty-copy | jee-main | generic_mirror | extracted | 24 | embedded_unverified | 24 | 1 question markers skipped as out-of-order (text-layer reading order scrambled; likely lost questions): [2]; 24/24 quest |
| jee-main-2025-s1-2025-01-22-shift-1 | jee-main | generic_mirror | extracted | 65 | embedded_unverified | 65 | 25 question markers skipped as out-of-order (text-layer reading order scrambled; likely lost questions): [1, 1, 2, 1, 1, |
| jee-main-2025-s1-2025-01-22-shift-2 | jee-main | generic_mirror | extracted | 63 | embedded_unverified | 63 | 42 question markers skipped as out-of-order (text-layer reading order scrambled; likely lost questions): [7, 7, 3, 7, 7, |
| jee-main-2025-s1-2025-01-23-shift-1 | jee-main | generic_mirror | extracted | 53 | embedded_unverified | 53 | 24 question markers skipped as out-of-order (text-layer reading order scrambled; likely lost questions): [1, 1, 2, 13, 3 |
| jee-main-2025-s1-2025-01-23-shift-2 | jee-main | generic_mirror | extracted | 52 | embedded_unverified | 52 | 33 question markers skipped as out-of-order (text-layer reading order scrambled; likely lost questions): [13, 4, 7, 5, 2 |
| jee-main-2025-s1-2025-01-24-shift-1 | jee-main | generic_mirror | extracted | 72 | embedded_unverified | 72 | 11 question markers skipped as out-of-order (text-layer reading order scrambled; likely lost questions): [1, 13, 1, 1, 9 |
| jee-main-2025-s1-2025-01-24-shift-2 | jee-main | generic_mirror | extracted | 75 | embedded_unverified | 75 | 6 question markers skipped as out-of-order (text-layer reading order scrambled; likely lost questions): [5, 1, 1, 2, 2,  |
| jee-main-2025-s1-2025-01-28-shift-1-2 | jee-main | - | needs_ocr | 0 | official_key_pending | 0 | no usable text layer; OCR deferred per task scope |
| jee-main-2025-s1-2025-01-28-shift-1 | jee-main | generic_mirror | extracted | 70 | embedded_unverified | 70 | 11 question markers skipped as out-of-order (text-layer reading order scrambled; likely lost questions): [11, 14, 9, 0,  |
| jee-main-2025-s1-2025-01-28-shift-2 | jee-main | generic_mirror | extracted | 70 | embedded_unverified | 70 | 31 question markers skipped as out-of-order (text-layer reading order scrambled; likely lost questions): [2, 2, 2, 2, 2, |
| jee-main-2025-s1-2025-01-29-shift-1 | jee-main | generic_mirror | extracted | 57 | embedded_unverified | 57 | 30 question markers skipped as out-of-order (text-layer reading order scrambled; likely lost questions): [10, 11, 12, 13 |
| jee-main-2026-s2-202604091916616339 | jee-main | nta_2026 | extracted | 75 | official_key_pending | 73 | 73/75 questions carry parse_flags |
| jee-main-2026-s2-202604092007095665 | jee-main | nta_2026 | extracted | 75 | official_key_pending | 73 | 73/75 questions carry parse_flags |
| jee-main-2026-s2-202604092096865379 | jee-main | nta_2026 | extracted | 75 | official_key_pending | 73 | 73/75 questions carry parse_flags; 73/75 stems are image-only in the text layer; IDs/structure extracted but content nee |
| jee-main-2026-s2-20260409432593766 | jee-main | nta_2026 | extracted | 75 | official_key_pending | 73 | 73/75 questions carry parse_flags |
| jee-main-2026-s2-20260409481957146 | jee-main | nta_2026 | extracted | 75 | official_key_pending | 73 | 73/75 questions carry parse_flags; 73/75 stems are image-only in the text layer; IDs/structure extracted but content nee |
| jee-main-2026-s2-20260409725707538 | jee-main | nta_2026 | extracted | 75 | official_key_pending | 73 | 73/75 questions carry parse_flags; 60/75 stems are image-only in the text layer; IDs/structure extracted but content nee |
| jee-main-2026-s2-20260409828731207 | jee-main | nta_2026 | extracted | 75 | official_key_pending | 73 | 73/75 questions carry parse_flags |
| jee-main-2026-s2-20260409829414602 | jee-main | nta_2026 | extracted | 75 | official_key_pending | 73 | 73/75 questions carry parse_flags; 73/75 stems are image-only in the text layer; IDs/structure extracted but content nee |
| jee-main-2026-s2-20260409932754345 | jee-main | nta_2026 | extracted | 75 | official_key_pending | 73 | 73/75 questions carry parse_flags; 73/75 stems are image-only in the text layer; IDs/structure extracted but content nee |

## Status totals

- extracted: 129
- needs_ocr: 27
- parse_failed: 33

## Answer-sheet totals

- embedded_unverified: 114
- official_key_pending: 71
- unavailable: 4

## Goal audit

- extracted paper artifacts: 129
- needs_ocr artifacts: 27
- parse_failed artifacts: 33
- counting rule: each sourced PDF is counted as one paper artifact;
  subject-wise PDFs are not merged into full shifts in this count.
- official-key status is stored per artifact as answer_sheet.status;
  embedded mirror answers remain validation=not_verified.

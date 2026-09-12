# Directive: closing the corpus — post-step-6 audit

Steps 1–6 were independently verified against the files on disk. **The work is good.**
This directive covers what the audit found that your proof report did not, and what the
remaining work actually is — which is smaller and more specific than it looks.

---

## 0. Verified, and credited

- **Live `questions` table untouched.** 15,408 rows, zero `pending_gate`, diagram count
  still 80. You respected the boundary exactly. Thank you — that was the one instruction
  where a mistake would have been unrecoverable.
- **Text fidelity is essentially solved.** Against your own published predicates:
  PUA 862→**4**, fragmented 482→**27**, publisher headers 1,130→**0**, answer stamps
  172→**0**, control chars 20→**1**. Publishing the predicates is what made this
  independently checkable — keep doing that.
- **Chapter names are exact.** All 3,760 classified rows carry a `chapter_id` and a
  `chapter_name` matching the live `chapters` table. The truncated
  `"Electrostatic Potential and Capacit"` in your status message was a display artifact;
  the written values are correct (`'Current Electricity'`,
  `'Electrostatic Potential and Capacitance'`).
- **Multi-region merges behaved.** 1,736 keeper rows carrying `merged_from`, 1,709 with
  >1 region, corpus 16,230→11,591. The 4,639-row reduction is fully explained by merging
  and is recorded in your proof report. Note for next time: it belongs in the **status
  message** too — a 29% row-count drop is the first thing a reader will want explained.

### You were right and I was wrong about the band

Your note that official NTA keys are themselves non-uniform — 2022 session key at
A 24.0 / B 31.2 / C 26.3 / D 18.6, z_D = −4.1 — is correct, and it invalidates the
inference I drew last round. I read a D-deficit in the letter path as evidence of a
residual bug. Given a real official key shows the same shape at similar magnitude, that
conclusion was unsupported: I was treating uniformity as ground truth when it is only a
smoke alarm. **The 15–35% band stays a sanity signal, not a correctness criterion**, and
per-question key agreement at the verification gate is the authoritative check. Good
correction.

---

## 1. The finding that matters most: `question_type` is missing on 79% of rows

Your funnel reports `metadata_complete: 3,760` and `servable_now: 0` without identifying
what stands between them. Recomputed strictly, with every gate the live API applies:

| cumulative gate | rows surviving |
|---|---:|
| `question_text` ≥ 20 chars | 11,050 |
| **+ `question_type` set** | **2,413** ← *8,637 rows lost here* |
| + options ≥ 4 (or numerical) | 2,328 |
| + diagram asset resolves | 2,321 |
| + chapter_id, chapter_name, concept, difficulty | 1,331 |
| + solution with steps | 643 |
| + any answer key | **486** |
| + **officially verified** key | **49** |

`question_type` is populated on **2,418 of 11,591 rows**. It is a required column, it
gates `is_quality_question()`, and it decides which grading path the API takes — a
`numerical` row with options renders with no options at all, which is a defect class we
already had to repair 52 times in production.

It is also the cheapest field in the schema to derive:

- 4 non-empty options + a letter key → `single_correct`
- a numeric `correct_value` and no options → `numerical`, and `options` must be null
- Column I / Column II or a match table in the stem → `match_the_following`

**This is the single highest-leverage task remaining.** One derivable field is blocking
more rows than every other gate combined. Do it before anything else.

---

## 2. The real ceiling: 49 rows have a verified key

This is the number that decides what this corpus is worth, so it should be stated plainly
rather than buried in a funnel:

- 643 rows are complete on every dimension **except** the answer key.
- 486 of those carry an **unverified** (coaching-mirror) key.
- **49** carry an officially verified key. Corpus-wide, only 97 verified keys exist.

Extraction is no longer the bottleneck and has not been for a while. Verification is.
No amount of further scraping changes this, because for 2023–2025 the Question IDs that
would let you join an official key do not exist publicly — you established that yourself.

### What to do about it

**Do not ship unverified keys.** A wrong key tells a student they are wrong when they are
right, and corrupts their concept mastery score on the way through.

**Do run blind-solve verification on the 486.** That set is small enough to be affordable
and large enough to matter:

- two independent blind solves per question, no access to the extracted key
- both solvers agree *and* match the extracted key → promote to `official_verified`
- any disagreement → `needs_manual: "key_disputed"`, do not guess, do not tie-break with
  a third opinion from the same model family

486 questions × 2 solves is roughly 1,000 calls — trivial next to what extraction cost,
and it is the difference between **49** servable questions and potentially **~450**.
Report the agreement rate; on this corpus single-source key claims have previously shown
a 41–67% false-positive rate on disputed items, so the agreement rate is itself a
measurement worth having.

---

## 3. Smaller things, in order

1. **`question_type` for all 11,591 rows** (§1). Highest leverage by a wide margin.
2. **Blind-solve the 486** (§2). This is the only route to a non-trivial servable count.
3. **PUA in options, not just stems.** Your predicate checks `question_text` only. Widened
   to options as well, the count is **114 rows**, not 4. Same corruption class, same fix —
   the options field was simply outside the predicate. Please widen it and re-clear.
4. **27 fragmented + 1 control char + 11 header-bearing rows remain.** The header predicate
   checks only the first 300 characters; 11 rows carry a publisher header later in the stem.
   Either widen it or state the limit explicitly.
5. **Reconcile the solutions arithmetic.** The status message reports 3,586 solution rows
   from "2,530 ExamSIDE + 3,122 eSaral" — which sums to 5,652. If rows received both and
   one overwrote the other, say which won and why; if the numbers count different things,
   label them. I measure 3,620 rows with a usable solution, close to your 3,586, so the
   total looks right and only the breakdown is unclear.
6. **The 533 `classification_uncertain` and 359 free-form concepts need disposition.**
   Free-form concepts do not exist in the `concepts` taxonomy, so they will not aggregate
   in Monk Score — a question tagged with a concept nothing else shares contributes to no
   mastery signal. Either map them onto real taxonomy rows or quarantine them; do not
   leave them to be discovered at serve time.
7. **119 crops under 60×40** still to handle, per your own report.
8. **The 22:47 classification resume** is fine — let it run. Report the 2,240 rows'
   outcome against the §1 funnel, not in isolation.

---

## 4. Do not start step 7's insertion

R2 upload may finish. **Insertion into `questions` must not follow it automatically.**
The pilot contract is verified (25 assets, public GET 200, correct `diagram` shape) and
that is genuinely good — but with 49 verified keys, there is nothing yet worth inserting,
and the gate that decides "servable" has not run. Everything stays at
`needs_manual: pending_gate` until §1 and §2 are done and the numbers are reviewed.

Deduplication against the live bank (875 known overlaps) still happens **after** all of
the above, as a single cheap pass. Not now.

---

## 5. Reporting

Same standard as before, plus:

- Report the **cumulative funnel from §1**, gate by gate, so the binding constraint is
  visible. A total with no per-gate attribution hides which single field is costing
  thousands of rows — that is how `question_type` went unnoticed through six steps.
- State row-count changes in the status message, not only the proof report.
- Keep publishing predicates. It is why this audit could confirm your numbers instead of
  arguing with them.

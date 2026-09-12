# Directive: the options field is contaminated, and no predicate is watching it

Two things happened. The blind-solve run is being handled on our side (Anthropic family
as solver A, cross-checked against the printed mirror key; DeepSeek via OpenRouter as
tie-break on disagreements only — so the 23:23 cron can be cancelled, see §4). While
building that set, we found a defect that blocks shipping and that your fidelity checks
structurally cannot see.

---

## 1. The answer and the worked solution are printed inside the options

Found while extracting blind-solve candidates — the very first question sampled had:

```json
"options": {
  "A": "205", "B": "615", "C": "510",
  "D": "430\n\nOfficial Ans. by NTA (D)\nAns. (D)\nSol. $t_1+t_2+t_3+t_4=30$\nCoefficient of..."
}
```

Another:

```json
"D": "$\\frac{\\pi}{2}$\n\nOfficial Ans. by NTA (C)\nAns. (C)\nSol. $\\int_0^\\pi \\frac{e^{\\cos x}\\sin x}{...}$\nUse King's pro"
```

Measured across the corpus:

| defect | rows |
|---|---:|
| an option value contains `Official Ans` / `Ans.` / `Sol.` | **383** |
| an option value contains a full worked solution | 354 |
| **an option value reveals the explicit correct letter** | **235** |
| an option value longer than 300 characters | 891 |
| **of the 1,500 complete/eligible rows, contaminated** | **170 (11%)** |

All 383 are in `diagram_questions.jsonl`.

**This is shipping-blocking.** A student opening one of these sees option D read
`"π/2 … Official Ans. by NTA (C) … Sol. ∫…"`. It gives away the answer, it renders as a
wall of LaTeX inside a multiple-choice button, and on 235 rows it states a letter that
may contradict the row's own stored key.

### Why every check missed it

Your `answer_stamp_in_stem` predicate is:

```
question_text matches /\bQ\d{1,3}\.\s*\([A-D1-4]\)/
```

It reads `question_text`. The contamination is in `options`. Same structural blind spot
that made the PUA count read 4 when the real figure was 110 — that one you fixed when it
was pointed out, but the fix was to widen *one* predicate rather than all of them.

**Widen every text-fidelity predicate to cover `options` values, `solution.steps`, and
`explanations` — not just `question_text`.** Re-run the whole §1.6 battery over all four
fields and report per-field counts. A predicate that inspects one of four text fields is
reporting on a quarter of the surface and calling it zero.

### The fix

Deterministic, and the real option text survives in every case we inspected — it is the
prefix before the leak marker:

1. For each option value, truncate at the first match of
   `/Official\s+Ans|(?:^|\n)\s*Ans\s*[.:\)]|(?:^|\n)\s*Sol\s*[.:]/i` and strip.
2. If truncation leaves fewer than 4 non-empty options, the row's option parse is
   unreliable — quarantine `options_leak_unrecoverable`, do not ship a 3-option row.
3. **Harvest before you truncate.** The leaked text contains an explicit answer letter on
   235 rows and a worked solution on 354. Capture both:
   - the letter as an *additional independent key claim* — then **compare it against the
     row's existing stored key and report every disagreement.** This is free
     cross-validation on 235 rows and it directly tests the §1.1 regex fix on real data.
     A disagreement means one of the two extraction paths is still wrong.
   - the `Sol.` body as a solution candidate for rows currently missing one (2,724 rows
     have options but no solution).
4. Treat any option over ~300 characters as suspect and inspect it. 891 rows qualify.
   Genuine JEE/NEET options are short; a 300-character option is almost always a parse
   that swallowed the next block.

---

## 2. Options recovery — still the biggest unlock, still not done

Unchanged from the last directive and now the top priority after §1. 6,148 of 11,579 rows
have zero options. Split by what is recoverable:

| situation | rows | method |
|---|---:|---|
| all four markers already in `question_text` | **2,025** | text segmentation, no vision |
| some markers present | 1,472 | segmentation + repair |
| no markers | 2,651 | vision re-read (`pdf_url` + `page` present on 5,496) |

For the 2,025: this is segmentation, not generation. **Hard constraint — every emitted
option string must appear verbatim as a substring of the source text.** Assert it in code
and quarantine any row that fails. That makes fabrication mechanically detectable rather
than a matter of trust.

For the 2,651: the model transcribes what is printed on the page. It must never infer or
compose options from the stem. A strong model asked to "give the four options" will
produce four plausible, well-formed, entirely invented distractors that are
indistinguishable from real ones downstream. Cross-check the transcribed count against
detected markers and flag every mismatch.

Record which path produced each row's options in an `option_source` field.

---

## 3. Diagram delivery is still at zero — ship the tranche

Production has **80** diagram questions, unchanged since this work began. **0** rows carry
the production `diagram` shape; the 25 pilot rows were wiped by the chain re-run you
disclosed. The R2 objects survive (deterministic keys) but nothing references them.

Diagram delivery is the stated priority and it is the least-delivered part of the project.
Stop gating it on whole-corpus completeness:

1. Fix the uploader's lost-update race first — it loads the file, uploads for an hour,
   then writes back rows the chain has since rewritten. Write per-row, or re-read
   immediately before write-back.
2. Then ship a first tranche: the **48 rows** that have 4 clean options + metadata +
   solution + an **officially verified** key + a resolving diagram asset. Upload their
   assets, emit the §3 `diagram` array, present them for insertion review.
3. A second tranche follows once our blind-solve results land.

48 trustworthy rows in production beats 11,579 in a raw file behind an unfinished upload,
and it exercises the whole path end to end while the rest of the recovery continues.

---

## 4. Cancel the 23:23 blind-solve cron

We are running verification here instead, to avoid spending your API quota:

- **Solver A:** Anthropic-family models, blind — keys withheld, repository reads under
  `data/` explicitly forbidden so the solver cannot read the key it is reproducing.
- **Second evidence source:** the printed mirror key. A model solve agreeing with a
  publisher's printed key is genuinely cross-source, since the key is not model-generated.
- **Tie-break:** DeepSeek via OpenRouter, on disagreements only (~20% of rows, well under
  a dollar). Note `api.deepseek.com` is network-blocked from this machine but OpenRouter
  proxies 18 DeepSeek models and reaches them fine.
- **Positive control:** 10 already-`official_verified` rows seeded unlabelled into the
  pilot; control recovery is reported separately and vetoes promotion if poor.

Keep the 22:47 classification resume — that is independent and useful.

One correction to your framing: the second-family situation was **not** unchanged.
`OPENAI_API_KEY` (130 models) and `OPENROUTER_API_KEY` (445 models, 59 families) are both
present in `.env` and both authenticate right now — verified. The run would not have had
to stop. Probe every configured provider before reporting a capability as unavailable.

---

## 5. A number to correct: the verification target was never ~430

The funnel's `any key: 432` counts rows whose answer entry holds *any* raw value. Filtered
to rows that actually have a usable `A`/`B`/`C`/`D` key **and** a resolving image:

- **116** eligible rows — 48 already `official_verified`, **68** unverified.

So ~367 of the 432 carry a "key" that never normalised to an option letter — mostly
out-of-range numerics like `120`, `800`, `138`. Those need their keys *normalised or
sourced*, not verified; there is nothing yet to check them against. Report them as a
distinct category rather than inside `key_present`, and check whether the raw value is a
real numerical answer or a stray page-number capture (202 distinct out-of-range values,
and `Answer: 2024 examination session` → `2024` is a known false-positive shape from the
widened numeric token).

---

## 6. Reporting

- Per-field fidelity counts (`question_text`, `options`, `solution.steps`, `explanations`).
- Every disagreement between a harvested leak letter and the stored key — that is a live
  test of the §1.1 fix.
- The options funnel per source, before and after, with `option_source` attribution.
- Substring-partition assertion pass/fail counts for the 2,025 segmentation rows.

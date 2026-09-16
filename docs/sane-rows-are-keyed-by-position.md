# A SANE verdict is keyed by position, and position is not identity

Found 2026-09-16, after the 29-chapter sweep. **This is the finding that
governs how much of Sessions E–H's SANE work survives.**

## The measurement

The four sheets record a judgement per `(subtopic_key, segment_index)`. A
precompute re-authors **the segments**, not merely their payloads. Comparing
the 86 judged n rows against the corpus after the sweep:

| | rows |
|---|---|
| objective essentially unchanged | **14** |
| objective CHANGED | **59** |
| segment index no longer exists | **13** |

So 72 of 86 judged rows now point at something other than what was judged.

## What it looks like

`oxidation-and-reduction-of-aldehydes-and-ketones` seg 2:

> judged: "Identify the reagents, observations, and **limitations** of Tollens',
> Fehling's, and Benedict's tests for aldehydes."
> now:    "Describe the Tollens' test, its reagent, observation, and the
> chemical equation for aldehyde oxidation."

The first is a three-way comparison and `reaction_scheme` was the wrong widget
for it — correctly classified kind (i). The second is a single reaction and
`reaction_scheme` is exactly right. **Same subtopic, same index, different
question.** A verdict of "n" carried forward would now be wrong, and a verdict
of "y" would be luck.

## Why this is the same defect this project keeps finding

It is the earthworm anchor again. A record was keyed to a POSITION while the
thing underneath changed, and nothing in the record could tell. It is why
`concept_assets` needed `label_set_sha256` and not just `label_set_version`: a
version says which revision you meant, a hash says whether what you are looking
at is still it.

The SANE sheets have the version and not the hash.

## What has been done

`scripts/apply_sane.py` now REFUSES to adopt a signed row whose objective has
changed or whose segment index no longer exists, and names each one. Adopting a
judgement about a rewritten segment is adopting it about something nobody read.

Verified both directions: `nucleophilic-addition` seg 3 (objective unchanged)
is accepted; `oxidation-and-reduction` seg 2 (objective rewritten) is refused
with the new text printed.

## What has NOT been done

**The sheets are not re-measured.** 72 rows need re-judging against the current
plans, which is a human pass, not a script. Until then:

* the adopted verdicts — physics 80.0%, chem 83.2%, bio 75.7%, maths 43.7% —
  describe a corpus that has since been re-authored. They are the best numbers
  that exist and they are stale. Every chapter is held either way, so nothing
  is currently resolving on a stale verdict;
* the H7 kind (i)/(ii)/(iii) classification inherits the same staleness for the
  72 rows. The 14 unchanged rows are sound.

## The fix, when someone writes it

A SANE row should carry a `segment_sha` — a hash of the objective plus the
stored payload at the moment of judgement — and any reader should compare it
before using the verdict. That turns silent decay into a refusal, exactly as
`label_set_sha256` did for published label sets.

Until then, **re-measure after any sweep.** A sheet written before a
regeneration describes a corpus that no longer exists.

# chem12 ch8 — the stored reaction_scheme payloads

**Seven payloads corrected on Raasikh's authorisation, 2026-09-12.** Originals
in `content/widget-payload-fixes/chem12-ch8-before.json`; each corrected
segment carries `example_widget_precompute.hand_corrected` so a later reader
does not mistake a hand fix for a generated one.

## The thing that matters more than the seven

`D1` was framed as "wrong reaction schemes corrected as content". While
locating them I ran every stored payload through the **client's own**
`reactionScheme.validate`, which nothing had done before:

    CLIENT WOULD DRAW 1 of 38
      27x every species label must be 1 to 10 characters
      25x step_reagent[i] must be at most 12 characters
       1x step 1 goes from a species to itself

**Thirty-seven of the thirty-eight stored payloads in this chapter would not
draw at all.** The chapter's 83.2% "sane" was judging payload CONTENT — is
this the right widget, does it match the objective — on payloads a student
would never have seen. The harness has a `client_validate` field and it is
`null` on all 113 rows; it was never run.

## Why they stored

The registry spec the model is given said:

> species (max 8 labels) … (max 8 steps), highlight_step, step_progress, caption.

and stopped. The character caps — **10 per species, 12 per reagent, 40 per
caption**, plus acyclicity and a real width/collision check at 343pt — live in
the client and **the server gate does not measure any of them**. So the model
wrote `3-hydroxy-2-methylpentanal` and a 64-character reagent string, the gate
stored them, and the board refuses them. This is precisely the "two validators
that drift" failure `widget_registry.py`'s own header warns about.

The spec now states the caps, gives condensed-formula examples, and says what
to do when the chemistry will not fit: **decline rather than truncate**,
because a shortened name teaches a string the exam does not print.

## The seven, and what was wrong

| segment | the error | the correction |
|---|---|---|
| preparation seg 1 | `LiAlH4` arrow drawn ketone → **aldehyde** | LiAlH4 takes `RCOR'` → `R2CHOH`, a secondary alcohol. Drawing the overshoot as RCHO → RCH2OH instead would have been correct chemistry but a **cycle**, which the widget refuses. |
| preparation seg 8 | `R'2Cd` drawn from `RCN`; Friedel–Crafts drawn from `RCOCl`, and again **ArCHO → ArCOCH3** | R'2Cd acts on the acyl chloride. The aromatic branch is removed rather than redrawn: `-CHO` is the deactivating meta-director this chapter teaches, so a ring already carrying it will not acylate. Three converging routes to RCHO is the segment's actual spine. |
| oxidation seg 5 | Clemmensen and Wolff–Kishner given **one identical reagent label** | `Zn-Hg/HCl` and `N2H4,KOH,Δ` — telling them apart is the whole segment. |
| nucleophilic seg 8 | arrow ends on the **reagent** `NH2OH`; the oxime is missing | product is `EtCH=NOH`; `NH2OH` moves to the reagent label where it belongs. |
| carboxylic seg 3 | final arrow draws **ester → H2O** | the mechanism ends at the ester; water is a by-product of the previous step and is named in its reagent label. |
| carboxylic seg 4 | reagent labels **shifted** — the anhydride reagent on an acyl-chloride arrow, and the anhydride arrow **blank** | `SOCl2` → RCOCl and `conc. H2SO4` → anhydride. PCl5/PCl3 move to the caption: three arrows between the same pair collide at 343pt and cannot be told apart. |
| carboxylic seg 6 | sodium **propanoate** decarboxylation drawn giving **CH4** | it gives ethane. `C2H5COONa → C2H6`; sodium acetate keeps CH4. |

## The eighth: aldol seg 5, deliberately NOT fixed

The crossed-aldol segment needs four product names. The shortest honest ones —
`3-OH-butanal`, `3-OH-2-Me-pentanal` — are 12 and 18 characters against a cap
of 10, and the validator refuses them. Abbreviations that *do* fit
(`2Me-3OH-C4`) pass the validator and teach a string no exam prints.

Measured both ways rather than asserted. The payload is left as it is and its
SANE verdict stays `n`: this is the wrong widget for that segment, which is
what the revised spec now tells the model to say.

## Where this leaves the chapter

    client would draw   1 of 38   before
                        8 of 38   after

The other 30 fail for the same reason and are not in the flagged set. They
need either regeneration against the corrected spec or the same hand pass —
**that is a bigger decision than seven rows and it is Raasikh's.**

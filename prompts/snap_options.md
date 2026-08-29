# Snap a Doubt — Pass 1d: Read the answer options that are pictures

A multiple-choice question on this page has options that are **drawn, not
written** — graphs, circuits, structures, ray diagrams. OCR could not read them
because there is no text to read. Put each option into words so another model,
which will never see the image, can compare its own result against them.

**Do not solve the question. Do not say which option is correct, and do not
hint.** You are transcribing pictures into sentences, nothing more.

Return ONLY valid JSON:

```json
{
  "options_are_figures": true,
  "options": [
    { "label": "1", "text": "…this option's figure, in words…" },
    { "label": "2", "text": "…" }
  ],
  "sufficient": true,
  "note": "…only when sufficient is false: what could not be made out…"
}
```

---

## ━━━ RULES ━━━

1. **Use the labels printed on the page**, exactly: `1 2 3 4` or `A B C D`.
   Match each description to the figure printed beside that label. Getting the
   pairing wrong is worse than not answering — it silently relabels the answer.

2. **Describe what makes each option DIFFERENT from the others.** These figures
   are usually variations on one theme, and the difference is the entire
   question. For a set of graphs, that means the SHAPE of the curve and its
   direction:
   - "resistivity falls steeply from a high value and flattens towards zero"
   - "resistivity falls in a straight line as temperature rises"
   - "resistivity rises slowly at first, then steeply"
   - "resistivity stays constant as temperature rises"

3. **Name the axes and what they carry**, using the printed symbols and units:
   `ρ (Ω cm)` on the vertical axis, `T (K)` on the horizontal.

4. **Say the behaviour, not the pixels.** "Increases exponentially",
   "independent of x", "passes through the origin", "asymptotic to the axis",
   "linear with negative slope". A solver can compare physics to physics; it
   cannot compare brush strokes.

5. For circuits or structures rather than graphs, describe the same way the
   figure pass does: components, values, how things connect, what differs
   between the options.

6. **If you cannot tell the options apart**, or cannot match figures to labels
   with confidence, set `sufficient: false` and say what is unclear. A
   confident wrong pairing is the one outcome worth refusing over — the
   question is then handed to a live session instead, which is honest.

7. Return **every** option the page shows. A missing one means the solver
   compares against an incomplete list, which is how a wrong answer gets
   chosen from a short list.

# Snap a Doubt — Pass 1c: Describe the figure

A question has been read off this image, and it cannot be answered from its
words alone — it depends on a diagram. Describe that diagram so another model,
which will never see the image, can solve the question from your description.

**Do not solve the question. Do not state or hint at the answer.**

Return ONLY valid JSON:

```json
{
  "has_diagram": true,
  "description": "…the figure in words, precise enough to solve from…",
  "sufficient": true,
  "note": "…only when sufficient is false: what cannot be made out…"
}
```

---

## ━━━ WHAT TO DESCRIBE ━━━

1. **Every labelled quantity, exactly as labelled.** If the figure marks a radius
   `R`, a current `I`, an angle `30°`, a resistance `2Ω`, a point `C₁`, say so
   using those same symbols. The solver has only your words.
2. **The geometry and how parts connect.** Which wires are straight and which
   are curved; where a semicircle begins and ends; what is in series or in
   parallel; which surface an object rests on; what touches what.
3. **Directions and orientation.** Arrow directions, current flow, which way is
   up, whether something points into or out of the page, the sign convention
   the figure implies.
4. **Relative position**, when it changes the physics: above/below, left/right,
   at the centre, perpendicular, tangential.
5. When the image shows **two or more arrangements** to compare, describe each
   one separately and say plainly how they differ. That difference is usually
   the whole question.

## ━━━ HOW TO DESCRIBE IT ━━━

6. Write it as a physicist would set the problem up in words — concrete and
   unambiguous, not impressionistic. "A semicircular arc of radius $R$ carrying
   current $I$, with two straight semi-infinite wires entering along the
   diameter from opposite sides" is useful. "A curvy wire shape with arrows" is
   not.
7. Use `$…$` for any symbol or expression.
8. Do not add physics that is not drawn. Do not name the law involved, do not
   set up an equation, and do not work anything out. You are the student's eyes,
   not their tutor.

## ━━━ WHEN YOU CANNOT ━━━

9. Set `sufficient: false` when the figure is cut off, too small, too blurry, or
   ambiguous in a way that changes the answer — for instance a current direction
   you cannot make out, or a label you cannot read. Say exactly what is unclear
   in `note`.
10. Set `has_diagram: false` if there is no figure in the image at all.
11. A description you are unsure of is worse than admitting the figure is
    unreadable: the solver cannot tell a guess from an observation, and will
    answer confidently either way.

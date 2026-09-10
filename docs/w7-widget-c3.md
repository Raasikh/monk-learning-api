# W7 — Widget C3 on simulator (live classes against production)

Two live classes, both against production (`/version` SHA `87534f9`), both on the
iPhone 17 simulator with the dev client. The directive: Physics 12 ch1
`field_lines`, Maths 12 ch8 `xy_plot`; fresh launch; params → deterministic
render; cue tracks reveal order; no coordinates or SVG emitted by the model.

## Physics 12 ch1 — Gauss's Law → `field_lines`

- First attempt died mid-class on a transient server error (`barge_in_text`
  abort + Deepgram 1011 + "Server disconnected"). The retry ran clean.
- Production log during precompute: `[WIDGET PRECOMPUTED] field_lines` on 6/7
  segments, `arch=high stored=6 rejected=1`.
- Reveal probe:
  `[reveal-probe] BUFFERED seq=5 type=diagram widget=field_lines` →
  `REVEALED seq=5 type=diagram widget=field_lines`.
- Board: the computed parallel-plates configuration with the derived readout
  `E 1.36e6 N/C  lines 12` — values the widget derives from params, not text
  the model wrote. Shot: `/tmp/g-shots/w7-fieldlines-board.png`.

## Maths 12 ch8 — Area Under a Simple Curve → `xy_plot`

Getting there surfaced a real precondition: **the exam profile was NEET**, so
the Drona subject menu was Physics/Chemistry/Biology and Maths did not exist in
the app at all. Switched the profile to JEE Main / Class 12 through the exam
flow (the onboarding stack then lands on the paywall; skipped via the
`monklearningapp://drona` deep link — nothing purchased). After the switch the
menu is Physics/Chemistry/Maths.

- Class: "Area Under a Simple Curve Bounded by the Axes" (Application of
  Integrals, 10 topics listed).
- First attempt: turn 1 (heading + 3 text segments, the strip idea) revealed,
  then the session dropped silently back to Home — nothing in the client log,
  same transient-server shape as the physics first attempt. Retry ran clean.
- Chapter figure prefetch correctly reports
  `[figures] chapter prefetch: 0 asset(s)` — a maths chapter has no
  illustration assets; the diagram arrives as a widget payload instead.
- Reveal probe (retry):

      BUFFERED seq=1 type=heading … seq=4 type=text
      BUFFERED seq=5 type=diagram widget=xy_plot
      REVEALED seq=1 … carriedBy=onItemStart(t_…_s1-0)
      REVEALED seq=2..4 carriedBy=END_OF_TURN_FLUSH
      REVEALED seq=5 type=diagram widget=xy_plot carriedBy=END_OF_TURN_FLUSH

- Board: y = x² + 1 shaded on [0, 2], axes 0–5 / 0–2, derived readout
  **`area 4.67`** — ∫₀²(x²+1)dx = 14/3 = 4.666…, i.e. the number is computed
  by `derive()` from the params, exactly right, not model-authored. The
  narration alongside it is the strip/rectangle derivation of the same
  integral. Shot: `/tmp/g-shots/w7-xyplot-board.png`.

## Params → deterministic render, no model geometry

Both boards carried `type=diagram` events naming a registry widget and a params
payload — no SVG string, no coordinates. Both readouts (`E 1.36e6 N/C`,
`area 4.67`) are client-side derivations that agree with hand computation,
which is only possible when the geometry comes from the widget's own maths.

## Cue / reveal-order observation (finding, not a defect)

In both maths runs only **seq 1** was revealed by `onItemStart` (paired with
its audio clip); seq 2–5 revealed via `END_OF_TURN_FLUSH`. The board is
correct — everything reveals, in order — but the per-sentence pairing carried
only the first segment in these sessions. Worth a look server-side at how
`audio_chunk.board_event` is being attached for later segments; the flush path
is doing the work the pairing path should.

## Still to capture

- [ ] Tap-to-answer evidence (waiting on a question turn in the live class).
- [ ] Exact-frame widget screenshots at 343×236 and 900×430 (extend
      `dev-widget-preview` with a 'frames' mode mirroring FigureLab — only
      after the live class ends; fast refresh kills a running class).

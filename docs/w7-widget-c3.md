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

## The reveal-order "finding" was the outage's signature — RESOLVED

In both maths runs only **seq 1** was revealed by `onItemStart`; seq 2–5 came
via `END_OF_TURN_FLUSH`. Root cause (found from the production log, not the
client): DeepSeek began echoing `deepseek-flash` for the pinned
`deepseek-v4-flash`, and tutor.py's strict model-echo equality check raised on
the FIRST chunk of every teaching turn. The failure fallback synthesized
exactly ONE audio clip per turn ("I didn't quite catch that — could you say it
once more?" — mis-blamed on the student because the client's synthetic 'Begin
lesson segment' kick-off counts as an utterance), so only one board event
could ride an `onItemStart`; the rest had nothing to pair with and flushed.
The boards looked perfect throughout because the failure path auto-populates
assigned board items and still serves precomputed widgets.

Fixed in API `8cb7c16` (evidence-dated alias map `models.KNOWN_MODEL_ECHOES`,
unknown echoes still refused, six unit tests incl. the failing fixture).
Post-fix verification class (bio11-ch7 cockroach, production): seq 1–5 each
`carriedBy=onItemStart(s1-0..s5-4)` — per-sentence pairing restored — turn
`failed=False`, 200-word narration, `ILLUSTRATION SERVED`, `DIAGRAM DROPPED 0`.
The maths xy_plot evidence above (payload → deterministic render, derived
`area 4.67`) was captured DURING the outage and stands: the widget path never
depended on the LLM turn succeeding.

## Tap-to-answer (production, post-fix)

Checkpoint mounted after audio drain: question "if a cockroach's exoskeleton
were one single rigid shell with no membranes at all, what would it lose?"
with 3 chips. Tapped "Its ability to bend and move freely" → answer turn ran:

    TURN SUMMARY seg=1/8 turn=2 phase=awaiting_answer->awaiting_answer
    grade=correct  words=173  llm=25.6s  failed=False

Client revealed the answer turn's four board items each on their own clip
(`onItemStart(s1-8..s4-11)` — playback ids continue across turns). Shots:
`docs/w7-shots/w7-tap-answer-board.png`.

## Still to capture

- [ ] Exact-frame widget screenshots at 343×236 and 900×430 (extend
      `dev-widget-preview` with a 'frames' mode mirroring FigureLab — only
      after the live class ends; fast refresh kills a running class).

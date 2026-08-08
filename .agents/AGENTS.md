# AGENTS.md — Monk Learning standing rules

Read this before every task. These are not suggestions.

---

## 1. EVIDENCE

**A claim is not a result.** Every report includes measured evidence or states
plainly that something was not measured.

- Raw query output, raw log lines, deployment IDs. Not prose summaries.
- **"Not measured" is an acceptable answer. Inventing a number is not.**
- Before writing a number, check it against the previous report. If they
  contradict, say so and explain which is right.
- Never present a figure from one system as a measurement of another. A Vercel
  build time is not a backend latency. A transliterator test is not an STT
  accuracy test.
- A violation rate of 0.0% must be provable. Trigger the counter deliberately
  and show it firing.

## 2. TESTS MUST EXERCISE THE REAL PATH

- `verify_full_loop.py` and any script calling backend functions directly
  **proves nothing about the app**. It has passed while production was broken at
  least five times.
- The real path is: browser → Vercel → Railway → WebSocket. Test that.
- Every assertion prints its own line. A single `PASSED` is not acceptable —
  when it fails we need to know which assertion.
- A test that cannot fail on a real bug has no value.

## 3. DEPLOYMENT

- **Confirm before reporting.** Vercel deployment ID + commit SHA + status
  **Ready**. Railway deployment SHA + timestamp.
- A pushed commit that failed to build changes nothing. This has happened twice.
- Run `npm run build` and the test suite **locally** before pushing.
- Local and production have diverged more than once. If you tested against
  `localhost`, say so.

## 4. NEVER FAIL SILENTLY

The most expensive pattern in this project: exception caught → logged → HTTP 200
returned → student sees something plausible → nobody notices for days.

- No `except: pass`. No bare except that swallows and continues.
- Any caught exception in a student-facing path emits an `error` event to the
  client.
- A turn producing speech but zero audio frames, zero board events, or a failed
  grade increments a counter and logs a violation.
- **Never fix by defaulting to success.** An unparsed grade is not `correct`.
  A zero-byte synthesis is not a success. This caused a real regression.

## 5. MODEL STRINGS

| Service | Model | Thinking |
|---|---|---|
| Planner | `deepseek-v4-pro` | OFF |
| Tutor | `deepseek-v4-flash` | OFF |
| Scoping | `deepseek-v4-flash` | OFF |
| Snap It Out transcription | `gpt-4o-mini` | — |

- **Never** `deepseek-chat` or `deepseek-reasoner`. Legacy aliases, and
  V4-Flash defaults to chain-of-thought unless explicitly disabled — it will
  spend the entire token budget thinking and return an empty string.
- Always pass `extra_body={"thinking": {"type": "disabled"}}`.
- Assert the returned model string at startup. Refuse to boot on mismatch.

## 6. SECRETS

- Never interpolate a secret into a log line, an exception message, or a report.
- Redact to the first six characters: `rk_live_d4Ov...`
- Never add auth bypasses to code that can reach production. A hardcoded token
  returning a valid user ID is an open door.

## 7. SESSION ARCHITECTURE

```
SESSION (one subtopic, ~30 min)
 └── SEGMENT × 6–9   (~3–4 min each, from the plan)
      └── TURN × 2–4  (Drona speaks, student answers)
```

- The **backend owns state and pacing.** The tutor *requests* a phase; the
  backend *decides*. `phase_request` is advisory.
- Backend computes per-turn board item assignment and tells the model exactly
  what to emit. The model does not decide pacing.
- The tutor emits **only** items from the current segment's `board_content`.
  Running out means advance to the checkpoint — never invent, never teach ahead.
- Board target: **6–9 authored items per segment**, ~60 across a session. Those
  items are the student's notes.

## 8. GRADING

- **Only the segment's checkpoint is graded.** Procedural questions, lightweight
  checks, and follow-ups return `grade: null`.
- A correct answer to a different question is never `incorrect`.
- Attempt cap is 1, enforced in code not only in the prompt.
- Never praise a non-`correct` grade with an unqualified opener — "Bilkul",
  "Bilkul sahi", "Perfect", "Exactly".
- **Sycophancy is the primary product risk.** When in doubt between `correct`
  and `partial`, choose `partial`.
- Re-run the 18-fixture grading-honesty suite after any `tutor.md` change.

## 9. DATA AND SECURITY

- RLS on every table. Owner-read via `auth.uid() = user_id`; **no insert/update
  policies** — FastAPI writes only.
- `questions`, `pdf_chunks`, `lesson_plans` — RLS ON with **zero policies**.
  They contain answers and rubrics.
- `model_answer`, `rubric`, `expected_misconceptions`, `grade`, `mistake_tag`,
  `phase_request`, `segment_complete` **never reach the client**.
- **Migrations must be applied, not just written.** `0007` and `0008` were both
  reported applied and were not. Verify with
  `information_schema.columns`, not the migration file.

## 10. VENDOR CONSTRAINTS

- **Rumik**: 50 concurrent connections, 100 RPM per account, 60s idle timeout.
  Ping frames do **not** reset the idle timer. Connections are leased per turn
  and released 4s after the last sentence.
- **Sarvam**: WebSocket STT returns 403 on our key — REST fallback in use. STT
  billed per audio second.
- Rate limits are handled with pre-synthesized cached filler audio. Never spend
  a request on a filler.

## 11. SCOPE

- Do not widen a validation rule to make something pass. If plans fail
  validation, fix the prompt — not the gate. (`expected_misconceptions` was
  loosened from 2–3 to 1–5 this way; it was wrong.)
- Report before fixing when asked to. A first run is a map of what breaks, not a
  patching session.
- If a directive says "report, don't fix" — report, don't fix.

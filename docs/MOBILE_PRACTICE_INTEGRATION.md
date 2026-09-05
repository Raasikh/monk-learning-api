# Mobile integration: Practice

Everything here is read directly from `app/routers/practice.py`, `app/auth.py`,
and `app/progress_scoring.py` as of 2026-09-05. If the code changes, this
drifts — treat the source files as ground truth over this document.

## The one thing that will NOT "just work"

Database fixes made this session (wrong answer keys corrected, duplicates
removed, corrupted tables normalized, mojibake fixed, metadata backfilled)
live in the `questions` table in Supabase. **Those are automatically
reflected for any client** — web, mobile, anything — because they're just
rows the API reads and returns as-is.

**The rendering fixes are not.** `QuestionStem.tsx` and `MathText.tsx` in the
web repo are presentation-layer React components. The API never runs them —
it returns raw `question_text` exactly as stored, and the web app parses that
raw text into structured UI (Assertion/Reason cards, match-the-following
tables, numbered statement lists, KaTeX-rendered LaTeX) entirely client-side.

Concretely, `question_text` can arrive looking like this:

```
Match List I with List II:

| List-I | List-II |
| :--- | :--- |
| A. Melting Point [K] | I. $T_1 > In > Ga$ |
| B. Ionic Radius | II. $B > T_1 > A_1$ |

Choose the correct answer from the options given below:
```

or this:

```
Given below are two statements.
Assertion (A): Glycogen is also known as animal starch.
Reason (R): Its structure is similar to amylopectin and is rather more highly branched.
```

If mobile renders `question_text` as a plain string, students will see raw
markdown pipes, `$...$` LaTeX source, and run-on Assertion/Reason paragraphs
— the exact bugs that were just fixed on web. Mobile needs equivalent
parsing, one of:

1. **If mobile is React Native**: `parseStem`/`classify`/`splitRow` in
   `QuestionStem.tsx` are plain JS/TS functions with no DOM dependency except
   the final render — the parsing logic can likely be reused close to
   verbatim, only the JSX output swapped for RN components.
2. **If mobile is native (Swift/Kotlin)**: re-implement the same rules
   natively. The rule set, in order:
   - Split on newlines. A label appearing **mid-line** (`Assertion (A): ... Reason (R): ...`
     on one line) gets a line break inserted before it first.
   - A line that is only a marker (`A.`, `(i)`, `3)`) with nothing else on it
     gets joined with the next non-empty line before anything else runs.
   - Consecutive lines starting and ending with `|` are a markdown table;
     the row directly under the header is a `| :--- | :--- |`-style
     separator, not data. Split each row on `|`, but **never split on a `|`
     that falls inside a `$...$` span** (LaTeX absolute-value notation like
     `$\left|x\right|$` uses bare pipes that are not cell boundaries).
   - A line matching `Assertion|Reason|Statement|Column` + optional
     `(A)`/`I`/`-` + `:`/`.` is a labelled block — but only if there's real
     text after the colon; an empty match (e.g. "Match Column I with
     Column II." — the trailing period after "Column II" looks like a label)
     must fall through to plain text, not render an empty card.
   - A line starting `(1)`, `1)`, `A.`, `(i)` etc. (letters run through H,
     not just D — five/six-item lists are common) is a list item. A single
     line can contain **multiple** items back to back
     (`a) Spongocoel b) Choanocytes`) — split on the marker boundary, but
     only if every resulting piece re-matches as a list item AND the markers
     are mutually distinct (this guard is what stops `"(0, 1)"` from being
     torn apart at the `1)` inside the interval).
   - A line starting with `choose|select|identify|match the|which of the...`
     is a closing instruction — render distinctly (web renders it italic/muted).
   - Exact regexes are in `src/components/QuestionStem.tsx` in the web repo
     if you want to port them character-for-character rather than re-derive.
3. **Recommended for the medium term**: move this parsing server-side. Add a
   field to the `/practice/next` response — e.g. `stem_blocks: [{kind, label,
   body}, ...]` or `stem_blocks: [{kind: "table", rows, hasHeader}, ...]` —
   computed once by the API using the same rules, so web, iOS, and Android
   all consume the same pre-structured output instead of three independent
   reimplementations drifting apart. Nobody has built this yet; it's a real
   backend change, not something already sitting in the code.

**LaTeX rendering**: every field (`question_text`, each option value, each
solution step) can contain `$...$`, `$$...$$`, `\(...\)`, `\[...\]` LaTeX,
including `\ce{...}` chemistry notation (mhchem) — roughly a quarter of the
bank is chemistry and uses it. Web uses KaTeX + the `katex/contrib/mhchem`
extension. Mobile needs an equivalent that supports mhchem specifically —
plain KaTeX/MathJax ports that omit the mhchem extension will fail on every
chemical equation. Options: embed a WebView running KaTeX (pixel-parity with
web, fastest to ship), or a native renderer (iosMath/SwiftMath on iOS,
JLaTeXMath on Android) — confirm mhchem or equivalent chemistry-notation
support before committing to a native library.

---

## Base URL

- **Local dev**: `http://localhost:8000`
- **Production**: whatever your Railway service's public domain is — not
  hardcoded anywhere in this repo, check the Railway dashboard. `railway.toml`
  only defines the start command (`uvicorn app.main:app --host 0.0.0.0 --port $PORT`)
  and `/health` as the healthcheck path.
- CORS (`app/main.py`) currently allow-lists `localhost:3000`, `*.vercel.app`,
  and `settings.allowed_origins_list` (env-configured). **This only matters
  for a WebView-based client** — CORS is a browser mechanism, a native HTTP
  client (Swift `URLSession`, Kotlin `OkHttp`, bare `fetch` in React Native)
  is not subject to it. If you do end up embedding a WebView, its origin may
  need adding to `allowed_origins_list`.

## Auth

Every endpoint below requires `Authorization: Bearer <supabase_access_token>`.

The token is a normal Supabase Auth session `access_token` — sign the user
in with the Supabase client SDK for your platform (`supabase-swift`,
`supabase-kt`, or the Supabase REST auth endpoints directly) against the same
Supabase project (`NEXT_PUBLIC_SUPABASE_URL` in the web repo's `.env.local`:
`https://tgbknrmnjwiokraddurx.supabase.co`), then pass the resulting
`access_token` as the Bearer token on every API call.

Server-side verification (`app/auth.py`): the token is checked against
Supabase's JWKS endpoint (`SUPABASE_JWKS_URL`, standard
`https://<project>.supabase.co/auth/v1/.well-known/jwks.json` shape),
accepts `ES256`/`HS256`/`RS256`, and does not check `aud`. A missing/invalid/
expired token returns `401` with `WWW-Authenticate: Bearer`.

---

## `POST /practice/next`

Selects one question for the user, applying exam/class filtering, quality
filtering, and the 21-attempt repeat-spacing tier logic.

**Request body** (all fields optional, all have defaults):
```json
{
  "exam": "jee" | "neet" | "both",        // default "both"
  "class_level": "11" | "12" | "both",    // default "both"
  "subject": "physics" | "chemistry" | "mathematics" | "biology" | null
}
```
- Invalid `exam`/`class_level` values silently fall back to `"both"`, not an error.
- `subject`, if given, overrides the weighted-random subject selection
  (JEE: physics/chem/maths equal weight; NEET: 50% biology / 25% chem / 25%
  physics, biology further split 50/50 botany/zoology; both: 25% each of all four).

**Response, success:**
```json
{
  "question_id": "uuid",
  "question_text": "raw markdown+LaTeX, see rendering section above",
  "question_type": "single_correct" | "numerical" | "assertion_reason" | "match_the_following",
  "options": { "A": "...", "B": "...", "C": "...", "D": "..." } | null,
  "chapter_name": "string | null",
  "concept": "string | null",
  "difficulty": 1 | 2 | 3 | 4 | 5 | null,
  "diagram": [ { "url": "...", "r2_key": "...", ... } ] | null
}
```
- `options` is **always `null` when `question_type == "numerical"`** — render
  a numeric input, not option buttons, for that type. This is exactly the
  bug that was found and fixed on web this session (52 questions were typed
  `numerical` with no `correct_value`, meaning the numeric-input branch hid
  real MCQ options entirely) — don't reintroduce it on mobile by assuming
  `question_type` and `options` are independent.
- **Option keys are not guaranteed to be `A`–`D`.** Some rows key options
  `"1"`–`"4"` instead. Render whatever keys are present; don't hardcode A–D.
- `diagram` is populated on a small minority of rows (36 out of ~12k at last
  count) — most questions have no image. When present it's a JSON array of
  descriptor objects with at least `url`; treat it defensively.
- `concept` is resolved through a curated concept table when available,
  falling back to the raw legacy tag — just display it as-is, no client logic needed.

**Response, exhausted pool:**
```json
{ "exhausted": true, "message": "No eligible practice questions available for subject '...' under selected exam/class filters." }
```
Handle this explicitly — it's a `200`, not an error status, just an empty result.

**Side effect**: calling this endpoint records a "serve" (starts a silent
pacing timer used by scoring — answering too fast doesn't score mastery
points). Don't call `/practice/next` speculatively/prefetch multiple ahead
without displaying them; each call burns a serve.

---

## `POST /practice/answer`

Grades an answer and records the attempt.

**Request body:**
```json
{
  "question_id": "uuid",
  "chosen_option": "A" | "1" | null,   // the OPTION KEY, not its display text
  "chosen_value": 12.5 | null           // for question_type == "numerical"
}
```

**Response:**
```json
{
  "is_correct": true | false,
  "correct_option": "B" | null,
  "correct_value": 42.0 | null,
  "solution": { "steps": ["Step 1: ...", "Step 2: ...", "..."] } | null,
  "scoring": { ... } | null
}
```
- Grading rule for non-numerical: `chosen_option.strip().lower() == correct_option.strip().lower()`
  — case-insensitive exact match on the **key**. Sending the option's display
  text instead of its key will always grade wrong.
- Grading rule for numerical: relative tolerance, not exact match — accepts
  within `max(1e-6, |key| × 0.5%)`, tightened to `±0.5` for integer-valued
  keys ≥ 200 (so e.g. 201 doesn't accept against a key of 200). A per-row
  `value_tolerance` overrides this when set and positive (in practice this
  is populated on almost no rows — don't assume it's usually in force).
- `solution.steps` is an array of strings, each independently containing
  LaTeX — render each step through the same math renderer as the stem, not
  as one pre-formatted block.
- **Multi-correct (comma-joined) keys are not supported by this grading
  logic** — a stored key like `"B,C"` would only ever match a `chosen_option`
  of the literal string `"B,C"`. Every such row in production was found
  ungradeable and quarantined this session; the currently-servable bank has
  zero of them. Don't build a multi-select answer UI expecting this endpoint
  to score it correctly if such questions are reintroduced later.
- `scoring` is `null` when the question has no concept tagging yet (some
  subjects aren't fully curated), otherwise an object with `scored: bool`,
  `reason: string | null` (e.g. `"repeat_attempt"`, `"under_time_floor"`,
  `"previously_served"` when `scored` is false), and on a real score,
  `difficulty` (the resolved band: `"easy"|"medium"|"hard"|"pyq_hard"`) and
  `concept_deltas: [{concept_id, role, before, after}]`. This mirrors what
  the Progress page consumes — treat it as opaque unless you're building
  mobile-side mastery UI, in which case read `app/progress_scoring.py` directly.

---

## `GET /practice/stats`

No request body. Returns lifetime stats for the authenticated user:
```json
{ "attempted": 130, "correct": 41, "accuracy": 31.5 }
```
`accuracy` is a percentage, one decimal place, `0.0` when `attempted == 0`.

---

## `POST /practice/explain`

Creates a Drona (live AI tutor) session seeded with a specific practice
question's full context, for a "explain this to me" flow. This is a
**separate, larger subsystem** (WebSocket-based live tutoring, not just
REST) — treat it as optional/advanced for an initial mobile build, not part
of the core practice loop.

```json
// request
{ "question_id": "uuid", "chosen_option": "A" | null, "chosen_value": 12.5 | null,
  "language": "en" | "hi" | null, "voice": "..." | null }
// response
{ "session_id": "uuid", "phase": "teaching", "language": "en", ... }
```
The actual tutor turn streams over a WebSocket (`/drona/session/{id}/live`),
not this endpoint — this call only creates the session row. If you want this
on mobile, it needs its own scoping pass; the Drona WS protocol isn't
documented here.

---

## Quick reference: what's already correct at the API layer

- Answer keys: independently re-verified this session, essentially 0 known
  wrong keys in the current servable pool.
- No question has a missing solution, missing key, or a key that doesn't
  match one of its own options.
- Every servable row has `concept` and `difficulty` populated (100% coverage
  as of this session).
- Duplicate questions and ungradeable (multi-correct) questions are already
  filtered out server-side via `needs_manual` — you will never receive one
  from `/practice/next`.

None of the above requires any mobile-side defensive logic. The rendering
section above is the one real gap.

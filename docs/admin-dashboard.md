# `/admin` — the founders' analytics dashboard

One page, served by this API, showing who signed up, who came back, what they
used and what it cost. Open to a fixed list of email addresses and nobody else.

**URL:** `https://monk-learning-api-production.up.railway.app/admin`

---

## Why it lives here and not in the mobile app

Two reasons, and the first is the one that decides it:

1. **Everything in the Expo bundle ships to every student's phone.** An
   `app/admin.tsx` route is compiled into the IPA and APK and reachable as a
   deep link. Table names, query shapes and all.
2. **It could not work there anyway.** The phone holds the *publishable* key
   under RLS and only touches `profiles` and `lesson_sections` directly. Every
   figure on this dashboard is read with the service key, which only this
   process has.

---

## Setup

### 1. Apply the migration

`migrations/0048_admin_analytics.sql`, pasted into the Supabase SQL editor
(that is how every other migration in this repo is applied — there is no
runner). It creates no tables: seven read-only functions over rows you already
have.

Then run the verification block at the bottom of the file. The last query must
return **zero rows** — it is checking that `anon` and `authenticated` were
stripped of EXECUTE, i.e. that the key in every student's app bundle cannot
call these functions.

### 2. Set two environment variables on Railway

| Variable | Value |
|---|---|
| `ADMIN_EMAILS` | `you@…,cofounder@…` — comma-separated, case-insensitive |
| `SUPABASE_PUBLISHABLE_KEY` | the same value as the mobile app's `EXPO_PUBLIC_SUPABASE_PUBLISHABLE_KEY` |

`SUPABASE_PUBLISHABLE_KEY` is public by design — it is inlined into every app
bundle already. The page needs it to run the same email OTP students do.

**`ADMIN_EMAILS` is what keeps people out.** Empty means *closed*, not open:
`require_admin` fails shut so a variable dropped in a redeploy can never expose
student rows. Neither variable is in the startup validator, so a deploy missing
them still boots — `/admin` just says what is wrong instead of taking the API
down with it.

### 3. Sign in

Same email OTP as the app. Enter your address, get a six-digit code, type it.
An address not on `ADMIN_EMAILS` is told so plainly on the sign-in screen —
that is the only place the distinction is ever made.

---

## How access control works

Every `/admin/api/*` route depends on `require_admin` (`app/auth.py`), which
verifies the Supabase JWT exactly as `get_current_user_id` does, then checks
the `email` claim against the allowlist.

**Every rejection is a 404, never a 403.** No token, expired token, forged
token, a real student's token — all identical, all "Not Found". A 403 would
confirm the route exists and that the caller merely lacks a role, which is the
half of the answer worth withholding. `tests/test_admin_gate.py` pins this.

Two independent layers, either of which alone would be enough:

- the allowlist above, and
- the SQL grant in 0048 — only `service_role` may execute the functions.

`/admin` itself and `/admin/config.json` are deliberately public: the first is
the sign-in screen, the second carries only the two values already shipped in
every app bundle. Neither exposes a single row.

---

## What the numbers mean

Read these before quoting any of them to an investor.

**Days are IST**, everywhere, not UTC. A student practising at 11pm in Delhi is
17:30 UTC; under UTC bucketing half your evening peak lands on "yesterday".

**"Signed up" is `auth.users`, "onboarded" is `profiles`.** A `profiles` row is
only written when onboarding *completes*, so the gap between those two tiles is
your onboarding drop-off — the one funnel measurable without client-side event
tracking. Anonymous sessions (no email) are excluded from every count.

**"Active" means one of four things:** answered a practice question, ran a
classroom session, snapped a doubt, or saved a note. That definition lives in
one place — `admin_activity()` in 0048 — so DAU, retention and the per-user
"last seen" column cannot drift apart. Add a fifth source there and every panel
picks it up.

**Retention is windowed, not exact-day.** "D7" means *returned on any day 7–13*.
With cohorts this size, exact-day retention is mostly zeroes. Percentages
divide by **eligible**, never by cohort size — a cohort that signed up
yesterday cannot have D7 retention yet, and shows "—" rather than a fake
collapse.

**Founder and test accounts are excluded by default.** They live in
`admin_excluded_users` (migration 0050) and are dropped from every aggregate:
signups, active users, retention cohorts, feature counts and LLM spend. This is
not cosmetic — when the list was introduced, four internal accounts were 99% of
all classroom sessions and 100% of all doubts, so every engagement number on the
page was a readout of the founders using their own product.

The **"internal" checkbox** in the header turns them back on, and while it is
ticked a banner says so on every tab — a screenshot travels without its
settings. The per-user drilldown never filters: asking for one account always
returns it, excluded or not.

To add someone:

```sql
insert into public.admin_excluded_users (user_id, email, reason)
select id, email, 'founder'
from auth.users where lower(email) = lower('you@example.com')
on conflict (user_id) do nothing;
```

To see the list: `select email, reason, created_at from public.admin_excluded_users;`
To undo one: `delete from public.admin_excluded_users where lower(email) = lower('...');`

**Turns are counted from `drona_turns`, not `drona_sessions.turn_count`** —
that column is declared but never written (0 of 826 rows), so it read as a flat
0.0 turns per session. Fixed in migration 0049; the column itself is still dead.

**Practice accuracy excludes gave-up attempts**, which is why migration 0043
added the `gave_up` column in the first place.

**Spend is split three ways, and only one of them is a unit economic.**
`llm_service_kinds` (migration 0051) classifies every `llm_calls.service`:

| kind | what it is | in per-user cost? |
|---|---|---|
| `student` | tutor turns, snap solves — scales with usage | **yes** |
| `content` | `segment` / `outline` / `widget_payload` — a lesson authored once into `lesson_plans` and replayed to everyone who takes it | no |
| `pipeline` | `gate_*`, emitted by `scripts/quality_gate.py` when a human runs it | no |

**Cost per active user divides student spend alone.** It used to divide *all*
spend, which made it rise as the lesson library grew and fall as students left —
a number pointing the wrong way. When the split was introduced, $21.14 of $30.40
was content and pipeline.

A service missing from `llm_service_kinds` becomes `unclassified` — never
`student` — and the Costs tab names it in a banner until you add it:

```sql
insert into public.llm_service_kinds (service, kind, note)
values ('my_new_service', 'student', 'what it does');
```

**Most `llm_calls` rows have no `user_id`, and that is mostly correct.**
Content and pipeline calls have no user by nature — a lesson is authored once
for everyone, and `quality_gate.py` is run by a human from a terminal.

The snap path *is* per-student and now records it: `user_id` is threaded from
`routers/doubts.py` down through `snap.py` to every `record_call`, as a
keyword-only argument defaulting to `None` so a script or test with no user
still books the call (as NULL — never dropped). `tests/test_snap_cost_attribution.py`
pins both halves of the rule: every snap site must attribute, and the planner
must not.

**Cost is whatever `llm_calls` recorded.** A model with no configured price
writes a null cost, which counts as $0 — never as a guess. If spend looks too
low, check the `LLM_PRICE_*` variables before believing it.

---

## Deleting an account

The per-user drawer has a delete control at the very bottom, below their whole
history, and confirmation is typing their email — not an OK dialog, which is a
reflex rather than a decision.

Deleting is a **soft delete that actually bites**: the account is hidden from
every number *and* `auth.users.banned_until` is pushed a century out, so GoTrue
refuses to issue them a new session. Restore clears both. Nothing of theirs is
dropped — doubts, notes, sessions and attempts all stay, which is what makes
the undo real.

Three things worth knowing before you use it:

- **There is a one-hour window.** A ban stops a *new* session; it does not
  invalidate an access token already on a phone. Tokens last an hour, so
  someone mid-lesson keeps working until their refresh is refused.
- **You cannot delete yourself, or another admin.** Enforced in
  `app/routers/admin.py`, because Postgres cannot see `ADMIN_EMAILS`. Both
  guards are about the 3am mis-click, not about malice.
- **This is not erasure.** Their content stays in Postgres and their photos
  stay in R2 under `doubts/{user_id}/`. A real deletion request — DPDP Act, or
  a parent asking — needs a separate irreversible job that also reaches R2, and
  it is deliberately not bolted onto a button that promises it can be undone.

Every delete and restore is written to `admin_user_audit` with the actor taken
from the signed-in admin's token, never from anything the client sent:

```sql
select action, email, actor, reason, at from public.admin_user_audit order by at desc;
```

## Voice spend (Rumik)

The Costs tab reads `llm_calls`, and only the LLM paths write there — Rumik,
Sarvam, Deepgram and Mathpix have never recorded a row. For Rumik that turned
out to be a display problem, not an instrumentation one:
`drona_turns.rumik_chars` and `.rumik_requests` are 100% populated and always
have been.

TTS bills per character, so the Voice card multiplies those characters by a
rate in `vendor_prices`, seeded with Rumik's published **Silk Mulberry** rate:
**₹0.50 per 1,000 characters = ₹500 per 1M**. Mulberry is what the code calls —
`RUMIK_MODEL = "mulberry"` in both `app/drona/voice_proxy.py` and
`app/followup_voice.py`. If you move tier (Muga is ₹0.99/1k), change the row:

```sql
update public.vendor_prices set price_per_1m_units = 990, currency = 'INR' where vendor = 'rumik';
```

**Rumik bills in rupees; the model vendors bill in dollars.** The two totals are
shown side by side in their own currencies and `grand_total_usd` stays null,
because combining them needs an exchange rate and a hardcoded one is wrong by a
little more every month. If a vendor is ever priced in USD the grand total
computes automatically.

Any vendor left with a NULL price shows usage and says "price not set" — the
same rule as `LLM_PRICE_*`, that an unpriced unit records nothing rather than
zero.

Only the **classroom** is counted. Ask-a-follow-up also speaks through Rumik and
has no per-turn row to count — recording it needs writes on a live path.
Sarvam, Deepgram and Mathpix have rows in `vendor_prices` but nothing counts
their usage yet.

## Lesson transcripts

Every classroom turn already stored what the student said (`utterance`, 99%
populated) and what the tutor replied (`raw_response.speech`, 100%). Clicking a
row under "Recent classes" in a user's drawer opens that lesson turn by turn,
with grade, mistake tag, off-topic tier, board-event count and characters
spoken.

One trap: `raw_response` is declared `jsonb` but holds a jsonb **string**,
because the writers pass `json.dumps(...)` into it. `->>'speech'` on it returns
NULL rather than erroring, which is why this needed checking against real rows.
`admin_jsonb()` unwraps either shape and returns NULL for anything malformed,
so one bad turn costs that turn rather than the whole transcript.

**Classroom latency is not recorded.** `drona_turns` declares `latency_ms`,
`tts_ms` and `llm_ms` and all three are 0% populated across every turn ever
taken. The transcript panel says so explicitly rather than rendering a
misleading 0ms. Filling them means timing in `tutor.py` / `scoped_turn.py`.

## What is missing

**Revenue and subscriptions.** There is no billing table anywhere in this repo
and no payment integration; `app/subscription.tsx` in the mobile app is UI with
nothing behind it. Rather than ship a panel of zeroes that looks like a
reporting bug, there is no revenue tab. Add one when billing exists.

**Screen views, in-app session length, and where onboarding is abandoned.**
This dashboard reports what the *server* recorded. Nothing tells it which
screen a student was on when they gave up. Closing that needs an `app_events`
table, a `POST /events` endpoint, and a `track()` call in the mobile app — at
which point [PostHog](https://github.com/PostHog/posthog) is worth pricing
against building it, since it has a React Native SDK and does funnels properly.

**Ad-hoc questions.** This page answers a fixed set. When you want to ask
something it does not cover, point [Metabase](https://github.com/metabase/metabase)
at the same database with a read-only Postgres role — the SQL in 0048 is a
usable starting point for its questions. The two compose; this page is the
five numbers you check every morning, Metabase is for everything else.

---

## Files

| Path | What it is |
|---|---|
| `migrations/0048_admin_analytics.sql` | every aggregation, computed in Postgres |
| `migrations/0049_…` / `0050_…` | turns fix; internal-account exclusion |
| `app/routers/admin.py` | the routes; one `.rpc()` each, no arithmetic |
| `app/auth.py` → `require_admin` | the allowlist gate |
| `app/admin_ui/index.html` | the page — no build step, one CDN dependency |
| `tests/test_admin_gate.py` | proves the gate is shut |

Aggregation is in SQL rather than Python on purpose: PostgREST caps a response
at 1000 rows and reports no error when it truncates (see `app/db.py`), so a DAU
counted by pulling rows into the API is wrong the day the table outgrows a
page — and wrong without saying so.

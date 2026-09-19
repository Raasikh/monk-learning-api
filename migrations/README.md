# 🗄️ `migrations/` — Database DDL Migrations

The `migrations/` directory contains all PostgreSQL database DDL migration scripts executed on Supabase. These scripts define table schemas, Row Level Security (RLS) policies, indexes, and constraints.

---

## 📂 Migration Log

| File | Feature / Table Added | Key Columns & Constraints |
|---|---|---|
| `0001_initial.sql` | Users, Chapters, PDF Chunks | Initial core tables & pgvector embeddings |
| `0005_drona.sql` | `lesson_plans`, `drona_sessions`, `drona_turns` | Core Drona tutoring state tables |
| `0006_misconceptions.sql` | `student_misconceptions` | Logs student diagnostic mistake tags |
| `0007_wellbeing.sql` | `drona_wellbeing_flags` | Logs Tier 5 crisis safety flags |
| `0008_metrics.sql` | `drona_platform_metrics` | Rumik/Sarvam latency & active session telemetry |
| `0009_telemetry.sql` | Persistent telemetry columns | `pool_exhaustion_count`, `ended_reason`, `violations` |
| `0010_rate_limit_hits.sql` | `drona_rate_limit_hits` | Telemetry table for Rumik/Sarvam vendor rate limits |
| `0011_drona_tutor_voice.sql` | `tutor_voice` column | Adds `female` (Veda/Ira) vs `male` (Drona/Lucas) persona choice |
| `0012_notes_and_doubts.sql` | `drona_notes`, `doubts`, `doubt_reports` | Notes saved from sessions; Snap a Doubt results; wrong-answer reports |
| _(0013–0047 not logged here — see the files)_ | | |
| `0048_admin_analytics.sql` | `admin_*()` read functions | Aggregations behind `/admin`. No tables: seven SECURITY DEFINER functions over existing rows. **EXECUTE is revoked from `anon` and `authenticated` and granted only to `service_role`** — the mobile app's key cannot call them. See `docs/admin-dashboard.md`. |
| `0049_admin_turns_from_drona_turns.sql` | replaces `admin_features` + `admin_user` | `drona_sessions.turn_count` is a permanent 0 — nothing has ever written to it. Turns are now counted from `drona_turns`. |
| `0050_admin_exclude_internal.sql` | `admin_excluded_users` | Keeps founder/test accounts out of the aggregates (they were 99% of sessions, 100% of doubts). All `admin_*` functions gain `p_include_internal boolean default false`. **Drops and recreates the functions** — the re-grant block at the foot is mandatory, not decorative. |
| `0051_admin_cost_kinds.sql` | `llm_service_kinds` | Splits LLM spend into student-serving / content authoring / offline pipeline. `cost_per_active_user` now divides **student spend only** — it was dividing lesson authoring and `quality_gate.py` runs by the student count. Unknown services default to `unclassified`, never `student`. |
| `0053_admin_delete_user.sql` | `admin_deleted_users`, `admin_user_audit` | Soft-delete a student from /admin: hidden from every number **and banned from signing in** (`auth.users.banned_until`). Reversible — nothing is dropped. Append-only audit of who deleted whom and why. |
| `0054_admin_voice_and_transcripts.sql` | `vendor_prices`, `admin_session()` | Rumik TTS spend on the Costs tab, computed from `drona_turns.rumik_chars` (already 100% populated). Price lives in `vendor_prices` and ships **NULL** — usage shows, money does not, until you set it. Also a per-lesson transcript: `utterance` + `raw_response.speech` were always recorded and never displayed. |
| `0055_admin_costs_daily_one_pass.sql` | `admin_settings` | **Fixes a live 500**: `admin_costs` timed out past 30 days because its daily series ran a correlated subquery per day per measure over 82k `llm_calls` rows. Now one grouped pass. Also adds `inr_per_usd = 95`, so INR-billed vendors convert into the USD totals from one editable row. |
| `0056_admin_user_cost_and_latency.sql` | replaces `admin_user` | Per-student cost (LLM / TTS / STT) and latency on the profile. STT reports `recorded: false` and LLM carries an attribution caveat, so a partial total cannot pass as a complete one. |
| `0057_admin_session_turn_latency.sql` | replaces `admin_session` | Reports the turn timings `tutor.py` and `scoped_turn.py` now write. `timed_turns` distinguishes a lesson with no timings from one that was instant. |
| `0058_snap_stage_timings.sql` | `doubts.timings` jsonb, `admin_snap_latency()` | Persists the snap stage breakdown app/snap.py has computed and logged all along — ocr / structure / transcribe / diagram / options / solve. Answers *why* photo-to-answer p95 is 60–110s, which `latency_ms` alone never could. |

> [!WARNING]
> **`0012` reconciles a pre-existing `doubts` stub.** The table already existed
> with `image_url`, `transcribed_question`, `question_latex`, `answer_json` and
> `solved`. `create table if not exists` would have silently skipped every new
> column, so `0012` uses `alter table ... add column if not exists` and drops the
> superseded columns behind a guard that refuses to run if the table has rows.
> Snap a Doubt images live in **Cloudflare R2**, not Postgres and not Supabase
> Storage — the row stores the object key (`doubts/{user_id}/{doubt_id}.jpg`),
> never a public URL.

---

## 🛡️ Security & Row Level Security (RLS)

All tables strictly enforce **AGENTS.md Rule 9**:

> [!CAUTION]
> **RLS Policy Enforcement**:
> - Student tables (`drona_sessions`, `drona_turns`, `student_misconceptions`) use owner-read policies (`auth.uid() = user_id`).
> - Content tables (`questions`, `pdf_chunks`, `lesson_plans`) have **RLS ENABLED with ZERO policies**, preventing direct client-side reads of rubrics or answers. FastAPI writes directly using the service role key.

---

### Verification Query
After applying a migration, verify columns with `information_schema.columns`:
```sql
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_name = 'drona_sessions';
```

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

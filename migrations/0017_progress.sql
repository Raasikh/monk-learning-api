-- ============================================================================
-- 0017_progress.sql — Progress page: Monk Score foundations
--
-- Spec: "The Progress page: how every number is made" (product spec, Aug 2026).
-- This migration creates every table the scoring system needs. It contains NO
-- scoring logic — all math lives in FastAPI; all constants live in
-- progress_config so they can be tuned in production without a deploy.
--
-- LIVE STATE THIS WAS WRITTEN AGAINST (verified 2026-08-15):
--   chapters            106 rows (phy 28 / chem 19 / math 27 / bio 32)
--   questions           4,989 rows — free-text `concept` (648 distinct),
--                       numeric `difficulty` 1–5 with 1,784 NULLs
--   subtopic_index      782 rows across all 106 chapters (Drona lessons)
--   practice_attempts   has mode + mock_run_id; NO timing column
--   concepts / concept_mastery / snapshots / user_settings   ABSENT
--
-- DESIGN DECISIONS ENCODED HERE:
--   * `concepts` is the single canonical taxonomy (~20–25 per chapter, drawn
--     from Drona subtopics + question tags, DeepSeek-curated). The two old
--     vocabularies (questions.concept free text, subtopic_index.subtopic) are
--     mapped onto it via concept_aliases — neither old column is touched.
--   * Ceiling wins over running-max: snapshots store raw, display and ceiling
--     separately so "display = min(running_max, ceiling)" is a view-layer rule.
--   * All constants (Gbase=14, Lbase=5, Dq map, half-lives, flag penalty 18…)
--     are seeded into progress_config as one versioned jsonb row.
--
-- RLS: owner-read on user-scoped tables (the web app reads Supabase directly
-- under the student's session). Taxonomy/config tables are readable by any
-- authenticated user. NO insert/update/delete policies anywhere — FastAPI
-- holds the service role key and does every write (AGENTS.md Rule 9).
--
-- Re-runnable: every statement is guarded.
-- ============================================================================

begin;

-- ─────────────────────────────────────────────────────────────────────────────
-- 1. concepts — the canonical taxonomy. The atomic unit of the Monk Score.
--    ~20–25 per chapter → ~2,300 rows once curation lands. Rows are seeded by
--    the DeepSeek curation job, NOT by this migration.
-- ─────────────────────────────────────────────────────────────────────────────
create table if not exists concepts (
  id            uuid primary key default gen_random_uuid(),
  chapter_id    uuid not null references chapters(id) on delete cascade,
  name          text not null,
  key           text not null,                      -- stable slug, e.g. "rolling-without-slipping"
  exams         text[] not null default '{jee,neet}',
  display_order smallint not null default 0,        -- syllabus order within the chapter
  active        boolean not null default true,      -- retire without deleting history
  created_at    timestamptz not null default now(),
  unique (chapter_id, key)
);
create index if not exists idx_concepts_chapter on concepts (chapter_id);

-- ─────────────────────────────────────────────────────────────────────────────
-- 2. concept_aliases — maps BOTH legacy vocabularies onto the taxonomy:
--    the 648 free-text questions.concept tags and the 782 Drona subtopics.
--    This is what lets Drona lesson activity find its concept (×0.6 credit)
--    and lets old question tags resolve without rewriting the questions table.
-- ─────────────────────────────────────────────────────────────────────────────
create table if not exists concept_aliases (
  id         uuid primary key default gen_random_uuid(),
  concept_id uuid not null references concepts(id) on delete cascade,
  alias      text not null,
  source     text not null check (source in ('question_tag', 'subtopic')),
  created_at timestamptz not null default now(),
  unique (alias, source)
);
create index if not exists idx_concept_aliases_concept on concept_aliases (concept_id);

-- ─────────────────────────────────────────────────────────────────────────────
-- 3. question_concepts — replaces the single free-text tag for SCORING.
--    One primary (100% of gain) + up to two secondary (35% each, spec §4.3).
--    questions.concept stays untouched; nothing existing breaks.
-- ─────────────────────────────────────────────────────────────────────────────
create table if not exists question_concepts (
  question_id uuid not null references questions(id) on delete cascade,
  concept_id  uuid not null references concepts(id) on delete cascade,
  role        text not null check (role in ('primary', 'secondary')),
  created_at  timestamptz not null default now(),
  primary key (question_id, concept_id)
);
-- exactly one primary per question
create unique index if not exists idx_question_concepts_one_primary
  on question_concepts (question_id) where role = 'primary';
create index if not exists idx_question_concepts_concept on question_concepts (concept_id);

-- ─────────────────────────────────────────────────────────────────────────────
-- 4. chapter_exam_weights — wch, the exam-mark weight per chapter (spec §6).
--    Editorial data researched from published paper analyses; source_url and
--    sourced_at record where each number came from and when.
-- ─────────────────────────────────────────────────────────────────────────────
create table if not exists chapter_exam_weights (
  chapter_id uuid not null references chapters(id) on delete cascade,
  exam       text not null check (exam in ('jee', 'neet')),
  avg_marks  numeric(5,2) not null check (avg_marks >= 0),
  source_url text,
  sourced_at timestamptz not null default now(),
  primary key (chapter_id, exam)
);

-- ─────────────────────────────────────────────────────────────────────────────
-- 5. concept_mastery — per user × concept, exactly spec §16.1.
--    Rows are created lazily on first evidence; absence of a row = Not started.
-- ─────────────────────────────────────────────────────────────────────────────
create table if not exists concept_mastery (
  user_id          uuid not null,
  concept_id       uuid not null references concepts(id) on delete cascade,
  mastery          numeric(5,2) not null default 0 check (mastery between 0 and 100),
  peak_mastery     numeric(5,2) not null default 0,   -- for decay + flag logic
  attempts_first   integer not null default 0,
  correct_first    integer not null default 0,
  proven_count     integer not null default 0,        -- re-proofs → half-life tier
  half_life_days   smallint not null default 21,      -- 21 / 45 / 90 (spec §10.1)
  last_evidence_at timestamptz,
  flag_state       text not null default 'none' check (flag_state in ('none', 'pending', 'flagged')),
  flagged_at       timestamptz,                       -- oldest-flag ranking (rec card 2)
  next_retest_at   timestamptz,                       -- spaced re-test queue
  updated_at       timestamptz not null default now(),
  primary key (user_id, concept_id)
);
create index if not exists idx_concept_mastery_flags
  on concept_mastery (user_id, flagged_at) where flag_state = 'flagged';
create index if not exists idx_concept_mastery_retest
  on concept_mastery (user_id, next_retest_at) where next_retest_at is not null;

-- ─────────────────────────────────────────────────────────────────────────────
-- 6. question_serves — the question.served event (spec §16.2).
--    Burn-on-render (an item is "seen" the instant it renders, §15) and the
--    silent timer for pace (§11) + the answer-time guess floor (§15).
--    practice_attempts stays as-is; this table is the timing/burn authority.
-- ─────────────────────────────────────────────────────────────────────────────
create table if not exists question_serves (
  id                uuid primary key default gen_random_uuid(),
  user_id           uuid not null,
  question_id       uuid not null references questions(id) on delete cascade,
  context           text not null default 'practice'
                    check (context in ('practice', 'mock', 'drona', 'retest', 'diagnostic')),
  served_at         timestamptz not null default now(),
  answered_at       timestamptz,
  time_to_answer_ms integer,
  first_serve       boolean not null default true    -- false ⇒ burned, never scores
);
create index if not exists idx_question_serves_user_q on question_serves (user_id, question_id);
create index if not exists idx_question_serves_pace
  on question_serves (user_id, served_at) where time_to_answer_ms is not null;

-- ─────────────────────────────────────────────────────────────────────────────
-- 7. progress_snapshots — nightly per-user snapshot (spec §16.2/§7).
--    Powers the +14 weekly delta, the 8-week climb bar, and Drona's word.
--    raw / display / ceiling stored separately: display = min(max(raw so far), ceiling).
-- ─────────────────────────────────────────────────────────────────────────────
create table if not exists progress_snapshots (
  user_id            uuid not null,
  snapshot_date      date not null,                  -- user-local date (3 AM job)
  monk_score_raw     numeric(6,1) not null default 0,
  monk_score_display numeric(6,1) not null default 0,
  ceiling            numeric(6,1) not null default 1000,
  flagged_count      smallint not null default 0,
  subject_scores     jsonb not null default '{}'::jsonb,  -- {"physics": 764, ...}
  counters           jsonb not null default '{}'::jsonb,  -- ledger totals (spec §13)
  drona_word         text,                           -- block 6, regenerated nightly
  created_at         timestamptz not null default now(),
  primary key (user_id, snapshot_date)
);

-- ─────────────────────────────────────────────────────────────────────────────
-- 8. progress_config — THE tuning surface. One active versioned jsonb row.
--    Change a constant: insert a new row with version+1, flip `active`.
--    History stays, so past behaviour is always explainable.
-- ─────────────────────────────────────────────────────────────────────────────
create table if not exists progress_config (
  version    integer primary key,
  active     boolean not null default false,
  config     jsonb not null,
  note       text,
  created_at timestamptz not null default now()
);
-- exactly one active version
create unique index if not exists idx_progress_config_one_active
  on progress_config (active) where active;

insert into progress_config (version, active, note, config)
values (1, true, 'Spec launch constants — expected to move once real cohort data lands.',
'{
  "g_base": 14,
  "l_base": 5,
  "difficulty_multipliers": { "easy": 0.7, "medium": 1.0, "hard": 1.4, "pyq_hard": 1.6 },
  "difficulty_map":         { "1": "easy", "2": "easy", "3": "medium", "4": "hard", "5": "pyq_hard", "null": "medium" },
  "secondary_concept_weight": 0.35,
  "mock_multiplier": 1.15,
  "drona_check_multiplier": 0.6,
  "strong_threshold": 80,
  "improving_threshold": 45,
  "improving_floor": 45,
  "flag_decay_threshold": 65,
  "flag_ceiling_penalty": 18,
  "half_lives_days": [21, 45, 90],
  "answer_time_floor_ms": { "easy": 4000, "medium": 4000, "hard": 8000, "pyq_hard": 8000 },
  "streak_escalate_after": 12,
  "recency_multiplier": 1.2,
  "recency_window_days": 14,
  "pace_targets_sec": {
    "jee":  { "physics": 174, "chemistry": 120, "mathematics": 210 },
    "neet": { "physics": 100, "chemistry": 70,  "biology": 55 }
  },
  "pace_over_target_alert": 0.10,
  "pace_diagnosis": { "slow_over_pct": 0.15, "slow_min_accuracy": 0.80,
                      "rush_under_pct": 0.15, "rush_max_accuracy": 0.75 },
  "subject_marks": {
    "jee":  { "physics": 100, "chemistry": 100, "mathematics": 100 },
    "neet": { "physics": 180, "chemistry": 180, "biology": 360 }
  }
}'::jsonb)
on conflict (version) do nothing;

-- ─────────────────────────────────────────────────────────────────────────────
-- 9. user_settings — timezone (per-user 3 AM snapshot job) + target exam
--    (drives which weight set scores the student). Nothing stores either today.
--    Timezone is captured by the web app at login (IANA name).
-- ─────────────────────────────────────────────────────────────────────────────
create table if not exists user_settings (
  user_id     uuid primary key,
  timezone    text not null default 'Asia/Kolkata',
  target_exam text not null default 'jee' check (target_exam in ('jee', 'neet', 'both')),
  updated_at  timestamptz not null default now()
);

-- ─────────────────────────────────────────────────────────────────────────────
-- RLS
-- ─────────────────────────────────────────────────────────────────────────────
alter table concepts             enable row level security;
alter table concept_aliases      enable row level security;
alter table question_concepts    enable row level security;
alter table chapter_exam_weights enable row level security;
alter table concept_mastery      enable row level security;
alter table question_serves      enable row level security;
alter table progress_snapshots   enable row level security;
alter table progress_config      enable row level security;
alter table user_settings        enable row level security;

-- taxonomy + config: readable by any signed-in student (needed to render the
-- full greyed syllabus, spec §15 — the syllabus shown is always complete)
do $$ begin
  if not exists (select 1 from pg_policies where tablename = 'concepts' and policyname = 'concepts_read_all') then
    create policy concepts_read_all on concepts for select to authenticated using (true);
  end if;
  if not exists (select 1 from pg_policies where tablename = 'concept_aliases' and policyname = 'concept_aliases_read_all') then
    create policy concept_aliases_read_all on concept_aliases for select to authenticated using (true);
  end if;
  if not exists (select 1 from pg_policies where tablename = 'question_concepts' and policyname = 'question_concepts_read_all') then
    create policy question_concepts_read_all on question_concepts for select to authenticated using (true);
  end if;
  if not exists (select 1 from pg_policies where tablename = 'chapter_exam_weights' and policyname = 'chapter_exam_weights_read_all') then
    create policy chapter_exam_weights_read_all on chapter_exam_weights for select to authenticated using (true);
  end if;
  if not exists (select 1 from pg_policies where tablename = 'progress_config' and policyname = 'progress_config_read_all') then
    create policy progress_config_read_all on progress_config for select to authenticated using (true);
  end if;
end $$;

-- user-scoped: owner-read only; FastAPI (service role) does every write
do $$ begin
  if not exists (select 1 from pg_policies where tablename = 'concept_mastery' and policyname = 'concept_mastery_owner_read') then
    create policy concept_mastery_owner_read on concept_mastery for select to authenticated using (auth.uid() = user_id);
  end if;
  if not exists (select 1 from pg_policies where tablename = 'question_serves' and policyname = 'question_serves_owner_read') then
    create policy question_serves_owner_read on question_serves for select to authenticated using (auth.uid() = user_id);
  end if;
  if not exists (select 1 from pg_policies where tablename = 'progress_snapshots' and policyname = 'progress_snapshots_owner_read') then
    create policy progress_snapshots_owner_read on progress_snapshots for select to authenticated using (auth.uid() = user_id);
  end if;
  if not exists (select 1 from pg_policies where tablename = 'user_settings' and policyname = 'user_settings_owner_read') then
    create policy user_settings_owner_read on user_settings for select to authenticated using (auth.uid() = user_id);
  end if;
end $$;

commit;

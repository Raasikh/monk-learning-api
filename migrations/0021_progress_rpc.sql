-- 0021 — progress_user_bundle(): one round trip for the Progress page
--
-- /progress needs five per-user reads from five unrelated tables: the exam
-- entitlement, concept mastery, score snapshots, and two lifetime counts.
-- PostgREST can only fetch tables together when a foreign key relates them,
-- and these are unrelated, so each was its own HTTP request — ~325ms apiece of
-- almost pure network latency, 1.65s in total, for payloads measured at 0, 4,
-- 0, 8 and 9 rows.
--
-- Running them concurrently from Python hid the latency but introduced the
-- codebase's only threaded Supabase access. Doing the work inside Postgres
-- removes both problems: one request, no threads.
--
-- SECURITY INVOKER (the default) is deliberate. This function must NOT bypass
-- row-level security — it runs as the caller, so a user can only ever read
-- their own rows, exactly as the five separate queries did. Never change this
-- to SECURITY DEFINER without adding an explicit user_id ownership check.

create or replace function progress_user_bundle(p_user_id uuid)
returns jsonb
language sql
stable
as $$
  select jsonb_build_object(
    'profile', (
      select to_jsonb(t) from (
        select target_exam from profiles where id = p_user_id limit 1
      ) t
    ),
    'mastery', coalesce((
      select jsonb_agg(to_jsonb(t)) from (
        select concept_id, mastery, attempts_first, correct_first,
               flag_state, flagged_at
        from concept_mastery
        where user_id = p_user_id
      ) t
    ), '[]'::jsonb),
    'snapshots', coalesce((
      select jsonb_agg(to_jsonb(t)) from (
        select snapshot_date, monk_score_display, monk_score_raw
        from progress_snapshots
        where user_id = p_user_id
        order by snapshot_date desc
        limit 60
      ) t
    ), '[]'::jsonb),
    'attempts', (
      select count(*) from practice_attempts where user_id = p_user_id
    ),
    'doubts', (
      select count(*) from doubts where user_id = p_user_id and solved is true
    )
  );
$$;

comment on function progress_user_bundle(uuid) is
  'Every per-user read the Progress page needs, in one round trip. Replaces five separate PostgREST calls. SECURITY INVOKER: respects RLS, callers see only their own rows.';

-- The five underlying queries all filter on user_id; these make each of them an
-- index scan rather than a sequential one now that they run in a single
-- statement. concept_mastery is already covered by its (user_id, concept_id)
-- primary key.
create index if not exists idx_progress_snapshots_user_date
  on progress_snapshots (user_id, snapshot_date desc);
create index if not exists idx_practice_attempts_user
  on practice_attempts (user_id);
create index if not exists idx_doubts_user_solved
  on doubts (user_id) where solved is true;

grant execute on function progress_user_bundle(uuid) to authenticated;

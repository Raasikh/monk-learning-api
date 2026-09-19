-- 0053_admin_delete_user.sql
--
-- Delete a student account from /admin — reversibly, and for real.
--
-- "For real" is the point. The dashboard already had `admin_excluded_users`,
-- which hides an account from every number; a delete button that only did that
-- would be the same mechanism wearing a scarier word. So deleting an account
-- also BANS IT: `auth.users.banned_until` is pushed a century out, and GoTrue
-- refuses to mint a session for a banned user. The student cannot sign in
-- again until someone restores them.
--
-- "Reversibly" is the other half. Nothing is dropped. The row stays, the
-- student's doubts and notes and sessions stay, and `admin_restore_user`
-- puts everything back — including the ban. A destructive admin action that
-- one mis-click can perform should be a destructive admin action that one
-- click can undo.
--
-- ─── What this does NOT do ─────────────────────────────────────────────────
--
-- It does not satisfy a legal erasure request. The student's content is still
-- in Postgres and their photos are still in R2; only their access is gone.
-- A real erasure needs the content purged too, which is irreversible and is
-- deliberately not built here — see the note at the foot of this file.
--
-- ─── The one-hour window ───────────────────────────────────────────────────
--
-- A ban stops a NEW session being issued. It does not invalidate an access
-- token already in a phone's memory, and this project's tokens last an hour
-- (Supabase default). So a student who is mid-lesson when you delete them
-- keeps working until their token expires and the refresh is refused. That is
-- a property of JWT auth, not a bug here, but it is worth knowing before you
-- use this on someone you actually need out immediately.
--
-- ─── Two tables, on purpose ────────────────────────────────────────────────
--
--   admin_deleted_users  CURRENT state. Row present = deleted. One PK lookup,
--                        which is what the six aggregate functions join on.
--   admin_user_audit     APPEND-ONLY history. Who deleted whom, when, and why
--                        — and every restore too. Deriving "is deleted" from a
--                        log's latest row would make every aggregate pay for a
--                        window function; keeping both costs one small table.

begin;

-- ───────────────────────────────────────────────────────────────────────────
-- State.
-- ───────────────────────────────────────────────────────────────────────────
create table if not exists public.admin_deleted_users (
  user_id    uuid primary key references auth.users(id) on delete cascade,
  email      text,
  reason     text not null default '',
  deleted_by text not null default '',
  deleted_at timestamptz not null default now()
);

comment on table public.admin_deleted_users is
  'Soft-deleted student accounts. Row present = deleted: hidden from /admin '
  'and banned from signing in. Removed by admin_restore_user(). Nothing of '
  'theirs is dropped — see migrations/0053.';

-- ───────────────────────────────────────────────────────────────────────────
-- History. Append-only; never updated, never deleted from.
-- ───────────────────────────────────────────────────────────────────────────
create table if not exists public.admin_user_audit (
  id      bigint generated always as identity primary key,
  user_id uuid not null,
  email   text,
  action  text not null check (action in ('delete', 'restore')),
  actor   text not null,
  reason  text not null default '',
  at      timestamptz not null default now()
);

-- No FK to auth.users on purpose: if the account is ever hard-deleted for
-- real, the record of who removed it must outlive it.
create index if not exists admin_user_audit_user_idx on public.admin_user_audit (user_id, at desc);
create index if not exists admin_user_audit_at_idx   on public.admin_user_audit (at desc);

do $perms$
declare t text;
begin
  foreach t in array array['public.admin_deleted_users', 'public.admin_user_audit'] loop
    execute format('alter table %s enable row level security', t);
    execute format('revoke all on table %s from public', t);
    execute format('revoke all on table %s from anon', t);
    execute format('revoke all on table %s from authenticated', t);
    execute format('grant all on table %s to service_role', t);
  end loop;
end
$perms$;


-- ───────────────────────────────────────────────────────────────────────────
-- admin_hidden_users — one definition of "leave this account out".
--
-- Internal accounts and deleted accounts are hidden for different reasons but
-- by the same rule, and the six aggregate functions should not each carry
-- their own copy of that union. Adding a third category later is one edit
-- here rather than six.
-- ───────────────────────────────────────────────────────────────────────────
create or replace function public.admin_hidden_users(p_include boolean default false)
returns table (user_id uuid)
language sql
stable
security definer
set search_path = public
as $fn$
  select x.user_id from public.admin_excluded_users x where not coalesce(p_include, false)
  union
  select d.user_id from public.admin_deleted_users  d where not coalesce(p_include, false)
$fn$;


-- ───────────────────────────────────────────────────────────────────────────
-- admin_delete_user
--
-- Returns a jsonb verdict rather than raising, so the API can tell the
-- difference between "no such user" and "already deleted" and say which.
-- Idempotent: deleting an already-deleted account is a no-op that reports so.
-- ───────────────────────────────────────────────────────────────────────────
create or replace function public.admin_delete_user(
  p_user_id uuid,
  p_actor   text,
  p_reason  text default ''
)
returns jsonb
language plpgsql
security definer
set search_path = public
as $fn$
declare
  v_email text;
  v_already boolean;
begin
  select email into v_email from auth.users where id = p_user_id;
  if not found then
    return jsonb_build_object('ok', false, 'error', 'no_such_user');
  end if;

  select exists (select 1 from public.admin_deleted_users where user_id = p_user_id)
    into v_already;
  if v_already then
    return jsonb_build_object('ok', true, 'already', true, 'email', v_email);
  end if;

  insert into public.admin_deleted_users (user_id, email, reason, deleted_by)
  values (p_user_id, v_email, coalesce(p_reason, ''), coalesce(p_actor, 'unknown'));

  -- The part that makes this a delete and not a filter. A century out rather
  -- than 'infinity': GoTrue only ever compares banned_until against now(), and
  -- a real timestamp survives every client and dashboard that would choke on
  -- an infinite one.
  update auth.users
     set banned_until = now() + interval '100 years'
   where id = p_user_id;

  insert into public.admin_user_audit (user_id, email, action, actor, reason)
  values (p_user_id, v_email, 'delete', coalesce(p_actor, 'unknown'), coalesce(p_reason, ''));

  return jsonb_build_object('ok', true, 'already', false, 'email', v_email,
                            'banned_until', (select banned_until from auth.users where id = p_user_id));
end
$fn$;


-- ───────────────────────────────────────────────────────────────────────────
-- admin_restore_user — the undo. Clears the ban and the deleted row.
-- ───────────────────────────────────────────────────────────────────────────
create or replace function public.admin_restore_user(
  p_user_id uuid,
  p_actor   text
)
returns jsonb
language plpgsql
security definer
set search_path = public
as $fn$
declare
  v_email text;
  -- integer, not boolean: GET DIAGNOSTICS ROW_COUNT yields a count. Declared
  -- boolean it parsed fine and raised "operator does not exist: boolean >
  -- integer" only when the function actually ran — i.e. the undo for a
  -- destructive action was broken in exactly the case you would need it.
  v_rows integer;
begin
  select email into v_email from auth.users where id = p_user_id;
  if not found then
    return jsonb_build_object('ok', false, 'error', 'no_such_user');
  end if;

  delete from public.admin_deleted_users where user_id = p_user_id;
  get diagnostics v_rows = row_count;

  -- Cleared unconditionally, not only when a deleted row existed: an account
  -- banned by hand in the Supabase dashboard should still be rescuable here.
  update auth.users set banned_until = null where id = p_user_id;

  if v_rows > 0 then
    insert into public.admin_user_audit (user_id, email, action, actor)
    values (p_user_id, v_email, 'restore', coalesce(p_actor, 'unknown'));
  end if;

  return jsonb_build_object('ok', true, 'was_deleted', v_rows > 0, 'email', v_email);
end
$fn$;


-- ───────────────────────────────────────────────────────────────────────────
-- The six readers, now hiding deleted accounts as well as internal ones.
-- Signatures are unchanged, so `create or replace` keeps 0050/0051's grants.
-- The existing p_include_internal flag reveals BOTH categories: they mean the
-- same thing to a reader of the numbers — "not a real active student" — and
-- two separate toggles would be a distinction without a difference on screen.
-- ───────────────────────────────────────────────────────────────────────────
create or replace function public.admin_activity(
  p_from timestamptz,
  p_include_internal boolean default false
)
returns table (user_id uuid, at timestamptz)
language sql
stable
security definer
set search_path = public
as $fn$
  with ex as (select h.user_id from public.admin_hidden_users(p_include_internal) h),
  all_activity as (
    select a.user_id, a.created_at from public.practice_attempts a
      where a.created_at >= p_from and a.user_id is not null
    union all
    select s.user_id, s.created_at from public.drona_sessions s
      where s.created_at >= p_from and s.user_id is not null
    union all
    select d.user_id, d.created_at from public.doubts d
      where d.created_at >= p_from and d.user_id is not null
    union all
    select n.user_id, n.created_at from public.notes n
      where n.created_at >= p_from and n.user_id is not null
  )
  select t.user_id, t.created_at
  from all_activity t
  where not exists (select 1 from ex where ex.user_id = t.user_id)
$fn$;

commit;

-- ───────────────────────────────────────────────────────────────────────────
-- The remaining readers each swap their inline `ex` CTE for the shared helper.
-- Done as a separate transaction so a failure here cannot roll back the tables
-- above, which are the part that must exist for the API to boot.
-- ───────────────────────────────────────────────────────────────────────────
begin;

do $patch$
declare
  fn record;
  src text;
  patched text;
  n int := 0;
begin
  for fn in
    select p.oid, p.proname, pg_get_functiondef(p.oid) as def
    from pg_proc p
    join pg_namespace ns on ns.oid = p.pronamespace
    where ns.nspname = 'public'
      -- admin_users and admin_user are NOT patched here: they also need a
      -- `deleted` flag in their output, so they are written out in full below
      -- where the change is reviewable rather than done by string surgery.
      and p.proname in ('admin_overview','admin_retention','admin_features',
                        'admin_costs')
  loop
    src := fn.def;
    -- Every one of them declares the same CTE verbatim (0050/0051).
    patched := replace(
      src,
      'ex as (
  select x.user_id from public.admin_excluded_users x
  where not coalesce(p_include_internal, false)
)',
      'ex as (
  select h.user_id from public.admin_hidden_users(p_include_internal) h
)');
    if patched = src then
      raise exception
        'could not patch %(): its `ex` CTE does not match the expected text. '
        'Apply 0050 and 0051 first, or edit this migration to match.', fn.proname;
    end if;
    execute patched;
    n := n + 1;
  end loop;
  raise notice 'patched % reader functions to hide deleted accounts', n;
end
$patch$;


-- ───────────────────────────────────────────────────────────────────────────
-- admin_users — hides deleted accounts, and flags the ones it shows.
-- Signature unchanged, so 0051's grant carries over.
-- ───────────────────────────────────────────────────────────────────────────
create or replace function public.admin_users(
  p_q      text default null,
  p_limit  int  default 50,
  p_offset int  default 0,
  p_sort   text default 'recent',
  p_include_internal boolean default false
)
returns jsonb
language sql
stable
security definer
set search_path = public
as $fn$
with args as (
  select nullif(trim(coalesce(p_q, '')), '')        as q,
         least(greatest(coalesce(p_limit, 50), 1), 200) as lim,
         greatest(coalesce(p_offset, 0), 0)         as off,
         coalesce(p_sort, 'recent')                 as sort
),
ex as (select h.user_id from public.admin_hidden_users(p_include_internal) h),
filtered as (
  select u.id as user_id, u.email, u.created_at as signed_up_at,
         u.last_sign_in_at,
         pr.display_name, pr.target_exam, pr.enrolled_class, pr.phone,
         exists (select 1 from public.admin_excluded_users z where z.user_id = u.id) as internal,
         exists (select 1 from public.admin_deleted_users  z where z.user_id = u.id) as deleted
  from auth.users u
  left join public.profiles pr on pr.id = u.id
  where u.email is not null
    and not exists (select 1 from ex where ex.user_id = u.id)
    and (
      (select q from args) is null
      or u.email                          ilike '%' || (select q from args) || '%'
      or coalesce(pr.display_name, '')    ilike '%' || (select q from args) || '%'
      or coalesce(pr.phone, '')           ilike '%' || (select q from args) || '%'
      or u.id::text                        =           (select q from args)
    )
),
stats as (
  select f.*,
    (select count(*) from public.practice_attempts a where a.user_id = f.user_id) as attempts,
    (select count(*) from public.practice_attempts a
       where a.user_id = f.user_id and a.is_correct)                              as correct,
    (select count(*) from public.drona_sessions s where s.user_id = f.user_id)    as sessions,
    (select count(*) from public.doubts d where d.user_id = f.user_id)            as doubts,
    (select count(*) from public.notes n where n.user_id = f.user_id)             as notes,
    (select round(coalesce(sum(l.cost_usd), 0)::numeric, 4)
       from public.llm_calls l where l.user_id = f.user_id)                        as cost_usd,
    greatest(
      (select max(a.created_at)   from public.practice_attempts a where a.user_id = f.user_id),
      (select max(s.last_turn_at) from public.drona_sessions   s where s.user_id = f.user_id),
      (select max(d.created_at)   from public.doubts           d where d.user_id = f.user_id),
      (select max(n.created_at)   from public.notes            n where n.user_id = f.user_id)
    )                                                                              as last_active_at
  from filtered f
),
ranked as (
  select s.*, row_number() over (
    order by
      case when (select sort from args) = 'attempts' then s.attempts       end desc nulls last,
      case when (select sort from args) = 'cost'     then s.cost_usd       end desc nulls last,
      case when (select sort from args) = 'active'   then s.last_active_at end desc nulls last,
      s.signed_up_at desc
  ) as rn
  from stats s
)
select jsonb_build_object(
  'total',  (select count(*) from filtered),
  'limit',  (select lim from args),
  'offset', (select off from args),
  'sort',   (select sort from args),
  'includes_internal', coalesce(p_include_internal, false),
  'rows', (
    select coalesce(jsonb_agg(jsonb_build_object(
      'user_id', user_id, 'email', email, 'display_name', display_name,
      'phone', phone, 'target_exam', target_exam, 'enrolled_class', enrolled_class,
      'onboarded', display_name is not null,
      'internal', internal, 'deleted', deleted,
      'signed_up_at', signed_up_at, 'last_sign_in_at', last_sign_in_at,
      'last_active_at', last_active_at,
      'attempts', attempts,
      'accuracy', round(100.0 * correct / nullif(attempts, 0), 1),
      'sessions', sessions, 'doubts', doubts, 'notes', notes, 'cost_usd', cost_usd
    ) order by rn), '[]'::jsonb)
    from ranked
    where rn >  (select off from args)
      and rn <= (select off from args) + (select lim from args)
  )
)
$fn$;


-- ───────────────────────────────────────────────────────────────────────────
-- admin_user — still never filters. A deleted account's page must open, or
-- there is no way to press Restore.
-- ───────────────────────────────────────────────────────────────────────────
create or replace function public.admin_user(p_user_id uuid, p_days int default 30)
returns jsonb
language sql
stable
security definer
set search_path = public
as $fn$
with p as (
  select greatest(coalesce(p_days, 30), 1) as days,
         (now() at time zone 'Asia/Kolkata')::date as today
),
b as (
  select days, today,
         (today - (days - 1))::date as from_day,
         (((today - (days - 1))::timestamp) at time zone 'Asia/Kolkata') as from_ts
  from p
),
u as (
  select id, email, created_at, last_sign_in_at, banned_until
  from auth.users where id = p_user_id
),
days as (
  select d::date as day
  from generate_series((select from_day from b), (select today from b), interval '1 day') d
),
act as (
  select (a.at at time zone 'Asia/Kolkata')::date as day
  from public.admin_activity((select from_ts from b), true) a
  where a.user_id = p_user_id
)
select case when not exists (select 1 from u) then null else jsonb_build_object(
  'user_id',         p_user_id,
  'email',           (select email from u),
  'signed_up_at',    (select created_at from u),
  'last_sign_in_at', (select last_sign_in_at from u),
  'internal',        exists (select 1 from public.admin_excluded_users z where z.user_id = p_user_id),
  'deleted',         exists (select 1 from public.admin_deleted_users  z where z.user_id = p_user_id),
  'banned_until',    (select banned_until from u),
  'deletion', (
    select to_jsonb(x) from (
      select reason, deleted_by, deleted_at
      from public.admin_deleted_users where user_id = p_user_id
    ) x
  ),
  'profile', (
    select to_jsonb(x) from (
      select display_name, phone, phone_verified, target_exam, enrolled_class, created_at
      from public.profiles where id = p_user_id
    ) x
  ),
  'totals', jsonb_build_object(
    'attempts', (select count(*) from public.practice_attempts where user_id = p_user_id),
    'correct',  (select count(*) from public.practice_attempts where user_id = p_user_id and is_correct),
    'gave_up',  (select count(*) from public.practice_attempts where user_id = p_user_id and gave_up),
    'sessions', (select count(*) from public.drona_sessions where user_id = p_user_id),
    'sessions_completed', (select count(*) from public.drona_sessions
                           where user_id = p_user_id and phase = 'complete'),
    'turns',    (select count(*) from public.drona_turns t
                 where t.session_id in (select id from public.drona_sessions where user_id = p_user_id)),
    'doubts',   (select count(*) from public.doubts where user_id = p_user_id),
    'doubts_solved', (select count(*) from public.doubts where user_id = p_user_id and solved),
    'notes',    (select count(*) from public.notes where user_id = p_user_id),
    'cost_usd', (select round(coalesce(sum(cost_usd), 0)::numeric, 4)
                 from public.llm_calls where user_id = p_user_id),
    'last_active_at', greatest(
      (select max(created_at)   from public.practice_attempts where user_id = p_user_id),
      (select max(last_turn_at) from public.drona_sessions   where user_id = p_user_id),
      (select max(created_at)   from public.doubts           where user_id = p_user_id),
      (select max(created_at)   from public.notes            where user_id = p_user_id)
    )
  ),
  'daily', (
    select coalesce(jsonb_agg(jsonb_build_object(
             'day', d.day,
             'events', (select count(*) from act where act.day = d.day)
           ) order by d.day), '[]'::jsonb)
    from days d
  ),
  'recent_sessions', (
    select coalesce(jsonb_agg(to_jsonb(x) order by x.created_at desc), '[]'::jsonb)
    from (select s.id, s.mode, s.language, s.phase, s.subtopic_key,
                 (select count(*) from public.drona_turns t where t.session_id = s.id) as turn_count,
                 s.cost_usd, s.created_at, s.completed_at
          from public.drona_sessions s where s.user_id = p_user_id
          order by s.created_at desc limit 15) x
  ),
  'recent_doubts', (
    select coalesce(jsonb_agg(to_jsonb(x) order by x.created_at desc), '[]'::jsonb)
    from (select id, chapter, concept, solved, status, question_text, created_at
          from public.doubts where user_id = p_user_id
          order by created_at desc limit 15) x
  ),
  'recent_notes', (
    select coalesce(jsonb_agg(to_jsonb(x) order by x.created_at desc), '[]'::jsonb)
    from (select id, chapter_id, item_count, segments_covered, total_segments, created_at
          from public.notes where user_id = p_user_id
          order by created_at desc limit 15) x
  )
) end
$fn$;


-- ───────────────────────────────────────────────────────────────────────────
-- Lock the new functions. admin_hidden_users, admin_delete_user and
-- admin_restore_user are NEW, and a new function grants EXECUTE to PUBLIC —
-- which in Supabase is `anon` and `authenticated`, i.e. the key in every
-- student's app bundle. A student able to call admin_delete_user would be able
-- to ban any account in the system.
-- ───────────────────────────────────────────────────────────────────────────
do $grants$
declare fn text;
begin
  foreach fn in array array[
    'public.admin_hidden_users(boolean)',
    'public.admin_delete_user(uuid,text,text)',
    'public.admin_restore_user(uuid,text)',
    'public.admin_activity(timestamptz,boolean)',
    'public.admin_overview(int,boolean)',
    'public.admin_retention(int,boolean)',
    'public.admin_features(int,boolean)',
    'public.admin_costs(int,boolean)',
    'public.admin_users(text,int,int,text,boolean)',
    'public.admin_user(uuid,int)'
  ] loop
    execute format('revoke all on function %s from public', fn);
    execute format('revoke all on function %s from anon', fn);
    execute format('revoke all on function %s from authenticated', fn);
    execute format('grant execute on function %s to service_role', fn);
  end loop;
end
$grants$;

commit;

notify pgrst, 'reload schema';

-- ─── Verification ──────────────────────────────────────────────────────────
--
--   -- deleted accounts drop out of the numbers, and come back with the toggle
--   select public.admin_overview(30)->'totals'->>'users_total';
--   select public.admin_overview(30, true)->'totals'->>'users_total';
--
--   -- who has been deleted, and by whom
--   select email, deleted_by, reason, deleted_at from public.admin_deleted_users;
--   select * from public.admin_user_audit order by at desc limit 20;
--
-- And the one that matters — MUST return zero rows:
--
--   select p.proname, a.rolname
--   from pg_proc p cross join lateral aclexplode(p.proacl) acl
--   join pg_roles a on a.oid = acl.grantee
--   where p.proname like 'admin\_%' and a.rolname in ('anon','authenticated');
--
-- ─── Not built, deliberately ───────────────────────────────────────────────
--
-- Erasure. This removes access, not content: the student's doubts, notes,
-- sessions and attempts stay in Postgres, and their snapped photos stay in R2
-- under doubts/{user_id}/. If you ever need to honour a real deletion request
-- — India's DPDP Act, or a parent asking — that is a separate, irreversible
-- job that must also reach R2, and it should be written deliberately rather
-- than bolted onto a button that currently promises it can be undone.

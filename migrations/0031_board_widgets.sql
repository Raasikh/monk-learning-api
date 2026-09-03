-- 0031_board_widgets.sql
-- Board widget runtime: lesson readiness, board payloads, and licensed assets.
-- Written for Postgres 15 / Supabase. Idempotent where practical.
--
-- FIXED ARTIFACT, NOT YET APPLIED. Originally drafted as 0021_board_widgets.sql
-- against the widget-runtime spec bundle, before that number was taken by the
-- real, applied 0021_progress_rpc.sql (a progress_user_bundle() RPC, unrelated)
-- — renumbered here to the next free slot. It also referenced
-- `concepts(concept_id)`; the real table's primary key is `concepts(id)`
-- (0017_progress.sql), so every FK below was fixed to match. This is the exact
-- same class of bug this file's own NOTE ON INDEXES already warns about
-- (`subject`/`class_level` assumed on `concepts` instead of `chapters`) —
-- caught before running this time, not after.
--
-- Do not run this against the shared production database until the widget
-- runtime's precompute pipeline is actually being built. See
-- app/dev-widget-preview.tsx (monklearning-mobile) and
-- docs/asset-flow.md's PROPOSAL header for why: the pipeline that would ever
-- write a row into `board_events` does not exist yet, so these tables would
-- sit empty.

begin;

-- ---------------------------------------------------------------- lesson state
-- Which concepts are actually ready to teach. This is what gates visibility in
-- the app: a concept with no precomputed lesson must not be selectable, because
-- a half-generated lesson is worse to a student than an absent one.
do $$ begin
  create type lesson_status as enum ('none','planned','generating','ready','failed','stale');
exception when duplicate_object then null; end $$;

alter table concepts
  add column if not exists lesson_status  lesson_status not null default 'none',
  add column if not exists lesson_built_at timestamptz,
  add column if not exists lesson_version   int not null default 0;

-- NOTE ON INDEXES
-- An earlier draft indexed concepts (subject, class_level, display_order). Those
-- columns come from the chapters join, not from concepts, so that index failed
-- with 42703. The two below reference only concept_id, chapter_id and the columns
-- this migration itself adds — nothing inferred.
--
-- The subject/class-scoped index belongs in 0021b_indexes.sql (still in
-- /Users/raasikhnaveed/Downloads/migrations/ — not yet copied into this repo's
-- migrations/, since it is applied after 0021a_probe.sql confirms where those
-- columns actually live in THIS project's schema).

create index if not exists concepts_ready_idx
  on concepts (lesson_status);

create index if not exists concepts_backlog_idx
  on concepts (lesson_status)
  where lesson_status in ('none','failed','stale');

-- ------------------------------------------------------------- board payloads
-- One row per diagram on the board. Layers ABOVE the existing tier-3
-- concept_diagrams (0029) rather than replacing it: this is tiers 1
-- (precomputed) and 2 (live) of the widget registry; fallback_svg here is the
-- same escape hatch concept_diagrams already serves.
do $$ begin
  create type board_tier as enum ('precomputed','live','fallback_svg');
exception when duplicate_object then null; end $$;

create table if not exists board_events (
  id            uuid primary key default gen_random_uuid(),
  concept_id    uuid not null references concepts(id) on delete cascade,
  section_index int  not null,
  seq           int  not null,
  tier          board_tier not null,

  -- registry payload; null only when tier = 'fallback_svg'
  widget_id     text,
  widget_version int,
  params        jsonb,
  annotate      jsonb not null default '[]'::jsonb,
  cues          jsonb not null default '[]'::jsonb,

  -- tier-3 escape hatch: the generated SVG string the board already renders
  fallback_svg  text,

  verified_at   timestamptz,   -- passed scripts/verify-render.mjs
  created_at    timestamptz not null default now(),

  constraint board_events_seq_unique unique (concept_id, section_index, seq),
  constraint board_events_payload_shape check (
    (tier = 'fallback_svg' and fallback_svg is not null and widget_id is null)
    or (tier <> 'fallback_svg' and widget_id is not null and widget_version is not null and params is not null)
  )
);

create index if not exists board_events_concept_idx on board_events (concept_id, section_index, seq);
create index if not exists board_events_widget_idx  on board_events (widget_id) where widget_id is not null;

-- The gap queue. Every tier-3 render is a measurement, not a failure: this table
-- is what ranks which widget or illustration to build next. Drive its rate to
-- near zero on the core syllabus.
create table if not exists board_gaps (
  id           bigserial primary key,
  concept_id   uuid references concepts(id) on delete set null,
  chapter_id   uuid,
  reason       text not null,        -- unknown_widget | invalid_params | no_asset_match | no_widget_for_type
  detail       jsonb not null default '{}'::jsonb,
  student_query text,                -- present when it came from a live doubt
  occurred_at  timestamptz not null default now()
);
create index if not exists board_gaps_rank_idx on board_gaps (reason, occurred_at desc);

-- -------------------------------------------------------------------- assets
-- The 149 authored illustrations. Licence columns are NOT NULL on purpose:
-- an asset with no recorded licence must be impossible to insert, not merely
-- discouraged. Retrofitting attribution across thousands of rows is far more
-- expensive than refusing the insert.
create table if not exists concept_assets (
  id            uuid primary key default gen_random_uuid(),
  concept_id    uuid not null references concepts(id) on delete cascade,
  asset_slug    text not null,
  version       int  not null default 1,
  format        text not null check (format in ('svg','webp','avif','png')),
  r2_key        text not null,
  width         int  not null check (width  > 0),
  height        int  not null check (height > 0),

  caption       text  not null,                       -- what the doubt endpoint matches on
  regions       jsonb not null default '{}'::jsonb,   -- see asset-pipeline.md §6a

  source        text  not null,                       -- must be on the allowlist
  source_url    text  not null,
  licence       text  not null,
  licence_url   text  not null,
  author        text  not null,
  attribution   text  not null,                       -- exact credit line to render
  adapted       bool  not null default false,

  normalised_at timestamptz,                          -- null = has not passed §6, must not ship
  review_by     text  not null,
  created_at    timestamptz not null default now(),

  constraint concept_assets_slug_version unique (asset_slug, version),

  -- The licence gate, enforced in the database rather than in a script someone
  -- can forget to run. NC / ND / SA never enter the table.
  constraint concept_assets_licence_allowlist check (
    licence in ('CC0','Public domain','CC BY 4.0','CC BY 3.0','CC BY 2.0',
                'MIT','NIH BioArt PD','US Gov PD','Commissioned — assigned')
  ),
  constraint concept_assets_source_allowlist check (
    source in ('nih_bioart','health_icons','bioicons','niaid_flickr','nlm','nci_visuals',
               'servier_smart','wikimedia_commons','bhl','phylopic','commissioned')
  )
);

create index if not exists concept_assets_concept_idx on concept_assets (concept_id);
create index if not exists concept_assets_ready_idx   on concept_assets (concept_id)
  where normalised_at is not null;

-- An un-normalised asset is exactly the one that renders as a black rectangle on
-- device. Make it unreachable through the read path rather than trusting callers.
create or replace view concept_assets_live as
  select * from concept_assets where normalised_at is not null;

commit;

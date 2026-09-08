-- 0036_concept_asset_sets.sql
--
-- WRITTEN, NOT APPLIED. Apply by hand in the Supabase SQL editor after review.
-- Additive and safe to apply against a populated table: both columns have
-- defaults, and `concept_assets` currently holds 0 rows.
--
-- WHAT THIS IS FOR
-- ================
-- drona-illustrations-v1 delivers 112 assets across 48 concepts. Most concepts
-- have several: `--a`, `--b`, `--c`. Cockroach morphology is a 2-asset set,
-- connective tissue and Phylum Arthropoda are 6-asset sets.
--
-- 0035 modelled one asset per concept. `concept_id` is nullable and there is no
-- ordering, so six rows for one concept are six unordered rows that happen to
-- share a foreign key. A board needs to know WHICH plate is the default and
-- what order the rest come in — "the first figure" is a fact about the set, and
-- the set has to be able to state it.
--
-- WHY A SLUG COLUMN RATHER THAN A JOIN THROUGH concept_id
-- =======================================================
-- `concept_id` stays and stays authoritative for the lookup: slot 3 resolves
-- (chapter_id, subtopic_key) -> concepts.id -> the set. `concept_slug` is not a
-- second key, it is the MANIFEST's own name for the group, recorded so a bucket
-- listing, the work order and this table can be compared by eye without a join.
-- It is also what survives a concept being renamed in `concepts`, which is why
-- it is NOT NULL: a row whose group nobody can name is a row nobody can audit.
--
-- THE UNIQUE CONSTRAINT IS THE POINT
-- ==================================
-- unique (concept_slug, sub_index) makes a duplicate ordinal impossible rather
-- than unlikely. Two rows both claiming to be figure 0 of one concept is the
-- failure that puts an arbitrary plate on a board and looks deliberate —
-- exactly the shape `asset_slug`'s own unique constraint already prevents for
-- the file. This is the same guarantee for the SET.
--
-- `asset_object_key()` is UNCHANGED. Keys stay `concept-assets/{asset_slug}.
-- {ext}`, byte-identical to the manifest's `file` column, so nothing about the
-- bucket layout depends on this migration.

begin;

alter table public.concept_assets
  -- The manifest's `concept_slug`. Backfilled from asset_slug below for any
  -- pre-existing row: with no `--letter` suffix the asset IS its own group.
  add column if not exists concept_slug text,

  -- `--a` = 0, `--b` = 1, ... A slug with no suffix is 0, because a concept
  -- with one asset is a set of one and must not be a special case anywhere
  -- downstream. DEFAULT 0 rather than NULL: "no ordinal" is not a state a set
  -- member can be in, and a nullable ordinal would sort unpredictably.
  add column if not exists sub_index smallint not null default 0;

-- Backfill BEFORE the NOT NULL, so an existing row cannot block the migration.
-- `split_part(asset_slug, '--', 1)` is wrong for slugs that legitimately
-- contain '--' inside the concept name (e.g.
-- `bio11-ch6-simple-permanent-tissues--parenchyma--...`), so the suffix is
-- stripped only when it is a SINGLE trailing letter.
update public.concept_assets
   set concept_slug = case
         when asset_slug ~ '--[a-z]$' then left(asset_slug, length(asset_slug) - 3)
         else asset_slug
       end
 where concept_slug is null;

update public.concept_assets
   set sub_index = case
         when asset_slug ~ '--[a-z]$' then ascii(right(asset_slug, 1)) - ascii('a')
         else 0
       end
 where sub_index = 0 and asset_slug ~ '--[a-z]$';

alter table public.concept_assets
  alter column concept_slug set not null;

-- A concept cannot have two figure-0s, or two figure-1s.
create unique index if not exists concept_assets_set_ordinal_idx
  on public.concept_assets (concept_slug, sub_index);

-- Slot 3 reads the set by concept and orders it. Without this the ordering is
-- a sort over a sequential scan on every turn that resolves an illustration.
create index if not exists concept_assets_concept_set_idx
  on public.concept_assets (concept_id, sub_index);

alter table public.concept_assets
  -- 0 is figure a. 25 is figure z. Beyond that the set is not a figure set.
  add constraint concept_assets_sub_index_range
    check (sub_index >= 0 and sub_index <= 25);

commit;

-- ------------------------------------------------------------- verification
-- After the step-4 ingest of drona-illustrations-v1:
--
--   -- 112 assets across 48 concepts
--   select count(*) as assets, count(distinct concept_slug) as concepts
--     from concept_assets;
--
--   -- every set starts at 0 and has no gaps; a gap means a row was refused
--   -- and the set silently renumbered around it
--   select concept_slug,
--          count(*)                             as n,
--          min(sub_index)                       as first,
--          max(sub_index)                       as last
--     from concept_assets
--    group by 1
--   having min(sub_index) <> 0 or max(sub_index) <> count(*) - 1;
--
--   -- the sets the C3 pass exercises
--   select concept_slug, sub_index, asset_slug
--     from concept_assets
--    where concept_slug like '%cockroach%' or concept_slug like '%connective%'
--       or concept_slug like '%arthropoda%'
--    order by concept_slug, sub_index;
--
-- DELIBERATELY NOT ADDED: a `figure_letter` column. The letter is presentation
-- of `sub_index`, derivable with chr(97 + sub_index), and storing both is two
-- fields that can disagree about the same fact.

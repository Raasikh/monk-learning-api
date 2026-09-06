-- 0035_concept_assets.sql
--
-- WRITTEN, NOT APPLIED. Apply by hand in the Supabase SQL editor after review;
-- this repo holds PostgREST credentials only, which cannot run DDL.
--
-- WHAT THIS IS
-- ============
-- The registry of illustration masters — the raster plates that
-- docs/label-layer.md (mobile repo) draws our own bilingual label layer over.
-- One row per figure. The file itself lives in R2; this table is what says the
-- file is allowed to exist.
--
-- scripts/ingest_asset.py is the only writer. Nothing else should insert here.
--
--
-- WHY THE PROVENANCE COLUMNS ARE SHAPED LIKE THIS
-- ===============================================
-- Six provenance failures in this project, all the same bug — a field that
-- could be satisfied by a plausible value nobody supplied:
--
--   prompt_version   populated, but a sha over ALL prompts; did not move when
--                    the planner moved. Traceable-looking, not traceable.
--   grounded         always true. A boolean that never took its other value.
--   topic_hash       NULL in 20 of 20 rows. Never populated at all.
--   page_start       hardcoded to 1 across 5,266 rows — and it failed
--                    PRECISELY BECAUSE A DEFAULT EXISTED. The column was never
--                    missing, so no completeness check ever complained.
--   (six docs)       cited in lib/widgets/CLAUDE.md as reviewed; never written.
--   source_model     named a model that did not produce the row.
--
-- Every one passed a NOT NULL check while asserting nothing. So NOT NULL alone
-- is not the defence here; it is the floor. Four layers:
--
--   1. NOT NULL and NO DEFAULT on licence, source_url, author, anchor_book,
--      generator_model, prompt_sha, text_check, labelled_reference_file,
--      labelled_reference_sha256, arrived_labelled, manifest_status.
--        -> a bare INSERT that omits licence raises
--           23502 null value in column "licence" violates not-null constraint
--           and no row appears. That is the check that fails loudly, and it
--           fails at the DATABASE, not only in the ingest script, so a
--           hand-written INSERT in the SQL editor cannot get past it either.
--
--   2. A CLOSED ENUM on licence (concept_assets_licence_enum). An unusable
--      licence is not a value-with-a-warning; it is not a member of the type.
--      Share-alike and non-commercial art cannot be RECORDED, so it cannot be
--      shipped and cannot be argued about later.
--
--   3. A PLACEHOLDER DENYLIST on every free-text provenance string
--      (concept_assets_no_placeholders). NOT NULL stops `null`. It does not
--      stop 'unknown', and 'unknown' is what actually gets typed. This is the
--      constraint that catches the page_start shape: a value that is present,
--      well-formed, and asserts nothing.
--
--   4. text_check records WHICH DETECTOR SPOKE rather than a boolean pass.
--      See THE TEXT CHECK below. This is the layer aimed specifically at
--      `grounded`, which was a boolean that only ever took one value because
--      nothing actually computed it.
--
-- No DEFAULT is written for any provenance column anywhere in this file. That
-- is deliberate and is the single most important line in the migration: a
-- default is what turned page_start into 5,266 rows of silence.
--
--
-- THE LICENCE ENUM, AND THE MEASURED RULE BEHIND IT
-- =================================================
-- docs/label-layer.md §4.3, unchanged — this table implements that enum, it
-- does not invent a second one.
--
--   CC0-1.0 | CC-BY-4.0 | CC-BY-3.0 | CC-BY-2.5 | PD-US-gov | PD-old-70
--
-- No CC-BY-SA-* member. No *-NC-* member. The measured rule from the 149-figure
-- audit is that the split is by WHO DREW IT, not by how good it looks:
--
--   community-drawn Wikipedia/Commons schematics  -> CC BY-SA   -> UNUSABLE
--   institution-dropped art                       -> CC BY / PD -> USABLE
--     OpenStax / CNX      CC BY 4.0 (older CNX mirrors CC BY 3.0 / 2.5)
--     NIH BioArt          CC BY 4.0
--     Berkshire           CC0 1.0
--     CDC PHIL            PD-US-gov (works of federal employees)
--     Servier Medical Art CC BY 4.0
--
-- Share-alike is excluded because it is viral into a closed-source app, not
-- because it is low quality — the CC BY-SA schematics are the BEST-labelled art
-- in the audit, which is exactly why an enum is needed rather than a note in a
-- doc. NCERT figures are all-rights-reserved: never reproduced, traced or
-- redrawn from, and there is deliberately no enum member that could describe
-- one.
--
-- WIDENING THIS ENUM IS A CODE REVIEW, NOT A CONFIG CHANGE, and it is never the
-- way to make a manifest row fit.
--
--
-- licence AND anchor_book ARE DIFFERENT FACTS ABOUT DIFFERENT WORKS
-- ================================================================
-- The 48-figure work order generates each plate from a pre-1931 engraving —
-- Strasburger, Parker & Haswell, Gray's Anatomy, Kerner & Oliver, Milnes
-- Marshall, Miall & Denny. Those anchors are public domain by age.
--
-- The shipped file is NOT the anchor. It is a new work derived from it, and a
-- derivative of a PD work is not automatically PD. So the two live in two
-- columns and are never collapsed:
--
--   anchor_book  the public-domain plate it was derived from
--   licence      the licence of the file we actually ship, supplied per row in
--                illustration-manifest.csv and validated against the enum
--
-- Letting anchor_book stand in for licence would give a licence column that is
-- fully populated, entirely plausible, and records a conclusion nobody stated.
-- That is the shape of all six prior failures and would be the seventh.
--
--
-- THE TEXT CHECK
-- ==============
-- The work order says the unlabelled master contains no text of any kind. The
-- obvious column for that is `master_has_no_text boolean`, and it would be
-- `grounded` again: always true, because the only thing that ever writes it is
-- the code path that already decided to write the row.
--
-- So the column records WHICH DETECTOR SPOKE:
--
--   ocr-clean                        real OCR ran and found nothing
--   heuristic-clean-ocr-unavailable  the shape heuristic found nothing and no
--                                    OCR engine was installed. NOT a pass —
--                                    the absence of evidence, recorded.
--
-- ('ocr-found-text' and 'heuristic-found-text' are refusals and never reach a
-- row, so they are not enum members here.)
--
-- No OCR engine is installed today, so every row from the current environment
-- will say 'heuristic-clean-ocr-unavailable', and
--
--   select text_check, count(*) from concept_assets group by 1;
--
-- says exactly how many assets were never really checked. That is a queryable
-- admission instead of a green tick. See scripts/asset_text_probe.py for the
-- measured blind spots — single-character labels 0/30 detected, display text
-- 0/30 in the strict tier.
--
--
-- WHY syllabus_gap IS NULLABLE HERE AND NOT NULLABLE IN THE FIGURE RECORD
-- ======================================================================
-- docs/label-layer.md §4.5 makes NULL a hard error: '[]' means "an author
-- checked and found no required structure missing", and the distinction between
-- that and "nobody looked" is the entire content of the field.
--
-- That rule is right for the FIGURE RECORD, which is written after a subject
-- author has reviewed the plate. It is wrong at INGEST, which happens before.
-- The manifest carries must_show and ncert_labels — what the art SHOULD
-- contain — and nothing that says what it does contain; only a human looking at
-- the plate can say that.
--
-- So the ingest writes NULL and means it. Writing '{}' would assert that a
-- check happened, 48 times in one run, and that is the page_start failure
-- exactly. The invariant "not shippable while syllabus_gap is NULL" belongs to
-- the mobile-side gate, where a human has actually looked, and
-- `ingest_asset.py verify` counts the NULLs so the backlog stays visible.

begin;

-- --------------------------------------------------------------------- table
create table if not exists public.concept_assets (
  id            uuid primary key default gen_random_uuid(),

  -- The filename key, straight from illustration-manifest.csv. Stable and
  -- never reused: it is what the R2 key is derived from, what the mobile figure
  -- record points at, and the join into content/concept-archetypes.csv (all 48
  -- work-order concepts match that file exactly today).
  --
  -- NOTE THE DOUBLE HYPHEN, e.g.
  --   bio11-ch7-cockroach--nervous-system-and-reproduction
  -- It is where a colon or comma in the concept name went. It is significant
  -- and is preserved, never normalised: collapsing it would produce a string
  -- that no longer matches the files, the manifest, or the archetypes CSV.
  --
  -- UNIQUE is what makes re-ingest an update instead of a duplicate.
  asset_slug    text not null unique,

  -- NULLABLE ON PURPOSE. One plate of the nephron serves "structure of the
  -- nephron", "counter-current multiplier" and "selective reabsorption". A NOT
  -- NULL concept_id would force three byte-identical uploads, and then three
  -- rows that can drift apart. This column names the PRIMARY concept; null
  -- means chapter-level art.
  concept_id    uuid references public.concepts(id) on delete set null,

  -- Routing metadata, denormalised so a verify sweep does not need three
  -- joins. Nullable: an asset can arrive before it is filed.
  chapter_id    uuid references public.chapters(id) on delete set null,
  subject       text,
  class_level   smallint,

  -- ------------------------------------------------------------- the object
  -- 'concept-assets/<asset_slug>.png' in the ILLUSTRATIONS bucket, never in the
  -- doubts bucket — see app/storage_r2.py for why those are separate buckets
  -- and not two prefixes in one. Byte-identical to the manifest's
  -- file_unlabelled, so the join is checkable by eye against a bucket listing.
  --
  -- ONLY THE UNLABELLED MASTER IS STORED. The labelled file is Gemini's proof
  -- that every required structure is present; our own bilingual label layer is
  -- drawn over the master at render time, so shipping burnt-in English labels
  -- would put two competing label systems on one image (§6.3).
  r2_key        text not null unique,

  -- SNIFFED FROM THE FILE HEADER, not from the extension and not from what the
  -- producer claimed. A .png that is actually a JPEG is a real thing generated
  -- output does; recording the claimed type would put a wrong Content-Type on
  -- the object and a wrong intrinsic decode in the app.
  content_type  text not null,

  -- Measured with Pillow at ingest, in pixels, of THIS file.
  -- docs/label-layer.md §1.3: label anchors are normalised against these, and
  -- §1.4: a silent re-crop is otherwise undetectable. They are the record that
  -- makes a later aspect check possible at all.
  width         integer not null,
  height        integer not null,
  bytes         integer not null,

  -- ----------------------------------------------------------- provenance
  -- All NOT NULL, all without a DEFAULT. See the header.
  licence       text not null,
  source_url    text not null,
  author        text not null,

  -- The public-domain plate the art was derived from. A DIFFERENT FACT from
  -- licence, about a DIFFERENT WORK. See the header.
  anchor_book   text not null,

  -- What produced the file. The exact model identifier, not a label:
  -- source_model failed by naming the wrong model, so a bare 'gemini' is in the
  -- ingest's placeholder denylist and cannot be written here.
  generator_model text not null,

  -- sha256 of gemini-work-order.md, first 16 hex — the prompt that specified
  -- these 48 figures. Deliberately a hash of THE ACTUAL FILE, not a version
  -- string somebody types: prompt_version failed because it was a sha over all
  -- prompts, so it moved when an unrelated prompt moved and stayed still when
  -- the planner changed.
  --
  -- What it does NOT cover, said rather than left to be assumed: the per-figure
  -- conversation, any reroll, and the model's own version (that is
  -- generator_model).
  prompt_sha    text not null,

  -- WHICH DETECTOR SPOKE, not whether a check passed. See THE TEXT CHECK.
  text_check    text not null,

  -- The labelled reference: verified to exist and hashed, NOT stored. A hash of
  -- a file we did not keep is still an identifier — it is what lets somebody
  -- later prove the reference they are looking at is the one that was checked
  -- at gate 4 (docs/label-layer.md §3.3).
  labelled_reference_file    text not null,
  labelled_reference_sha256  text not null,

  -- THREE-VALUED, not a boolean (docs/label-layer.md §4.4). A boolean cannot
  -- describe the PD plate labelled only "A head, B thorax, C abdomen": it
  -- arrived labelled AND is unusable, and those are the two facts a triage
  -- queue needs. For this pipeline the value is evidenced by text_check rather
  -- than asserted, which is the difference between this column and `grounded`.
  arrived_labelled text not null,

  -- NULL means NOBODY HAS LOOKED YET, and that is a real state at ingest time.
  -- '{}' means an author checked and found nothing missing. See the header for
  -- why this column is nullable here and not nullable in the figure record.
  syllabus_gap  text[],

  -- The manifest status the row was admitted under. Recorded so a later change
  -- to what counts as approved is detectable, and so a row cannot exist without
  -- naming the gate it came through.
  manifest_status text not null,

  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now(),

  -- ------------------------------------------------------------- constraints

  -- LAYER 2. The closed enum. Membership is the whole mechanism: there is no
  -- share-alike value to enter, so there is no share-alike asset to argue
  -- about at review time.
  constraint concept_assets_licence_enum check (
    licence in (
      'CC0-1.0',
      'CC-BY-4.0',
      'CC-BY-3.0',
      'CC-BY-2.5',
      'PD-US-gov',
      'PD-old-70'
    )
  ),

  -- LAYER 3. The placeholder denylist, case-insensitive, on every free-text
  -- provenance string. licence is covered by the enum above and needs no entry
  -- here; the rest are free text and do.
  --
  -- WHAT FAILS LOUDLY, NAMED EXPLICITLY, because a constraint nobody has seen
  -- fire is a constraint trusted on the strength of having been written:
  --
  --   insert ... (author) values ('unknown')
  --     -> 23514 new row for relation "concept_assets" violates check
  --        constraint "concept_assets_no_placeholders"
  --
  --   insert ... (author) values ('   ')
  --     -> same constraint. btrim() is why: whitespace-only is the placeholder
  --        that survives both NOT NULL and <> ''.
  --
  --   insert ... omitting licence entirely
  --     -> 23502 null value in column "licence" violates not-null constraint
  --
  --   insert ... (licence) values ('CC-BY-SA-4.0')
  --     -> 23514 ... violates check constraint "concept_assets_licence_enum"
  --
  --   insert ... (generator_model) values ('gemini')
  --     -> 23514 ... concept_assets_no_placeholders. A bare model name pins no
  --        version; that is the source_model failure.
  --
  -- Each of these has a matching refusal test in tests/test_asset_ingest.py so
  -- the ingest refuses before the database has to. The database constraint is
  -- the backstop for the path the script does not own: somebody pasting an
  -- INSERT into the Supabase SQL editor.
  constraint concept_assets_no_placeholders check (
    lower(btrim(author))          not in ('', 'unknown', 'tbd', 'n/a', 'na', 'todo', '-', '–', 'null', 'none', '?', 'unclear', 'various', 'see source', 'public domain', 'public domain?', 'anonymous', 'anon', 'uncredited')
    and lower(btrim(source_url))      not in ('', 'unknown', 'tbd', 'n/a', 'na', 'todo', '-', '–', 'null', 'none', '?', 'unclear', 'various', 'see source')
    and lower(btrim(anchor_book))     not in ('', 'unknown', 'tbd', 'n/a', 'na', 'todo', '-', '–', 'null', 'none', '?', 'unclear', 'various', 'see source')
    and lower(btrim(generator_model)) not in ('', 'unknown', 'tbd', 'n/a', 'na', 'todo', '-', '–', 'null', 'none', '?', 'gemini', 'ai', 'llm', 'model', 'generated')
  ),

  -- A URL that is not a URL is the same failure wearing a longer string.
  -- 'see the archive.org page' passes the denylist and cites nothing.
  constraint concept_assets_source_url_is_url check (
    source_url ~ '^https?://[^[:space:]]+$'
  ),

  -- Not a version string somebody typed. 16 lowercase hex, as produced by
  -- ingest_asset.prompt_sha().
  constraint concept_assets_prompt_sha_shape check (
    prompt_sha ~ '^[0-9a-f]{16}$'
  ),
  constraint concept_assets_labelled_sha_shape check (
    labelled_reference_sha256 ~ '^[0-9a-f]{64}$'
  ),

  -- Only the two CLEAN verdicts can reach a row; the two text-found verdicts
  -- are refusals in the ingest and would be a bug if stored.
  constraint concept_assets_text_check_enum check (
    text_check in ('ocr-clean', 'heuristic-clean-ocr-unavailable')
  ),

  constraint concept_assets_arrived_labelled_enum check (
    arrived_labelled in ('unlabelled', 'labelled_usable', 'labelled_unusable')
  ),

  -- Only approved rows are ingested. Recorded AND constrained, so a row cannot
  -- exist that was admitted under some other status.
  constraint concept_assets_manifest_status check (manifest_status = 'approved'),

  -- No element of syllabus_gap may itself be a placeholder. '{unknown}' is not
  -- '{}' and must not be allowed to look like a completed check. (NULL is
  -- permitted and means nobody has looked; see the header.)
  constraint concept_assets_syllabus_gap_clean check (
    syllabus_gap is null or not exists (
      select 1 from unnest(syllabus_gap) g
       where lower(btrim(g)) in ('', 'unknown', 'tbd', 'n/a', 'na', 'todo', '-', 'null', 'none', '?')
    )
  ),

  -- The manifest's double hyphen is legal here. Measured over all 48 rows: 256
  -- single-hyphen runs, 50 double, none longer, none leading or trailing,
  -- lengths 25..71.
  constraint concept_assets_slug_shape check (
    asset_slug ~ '^[a-z0-9]+(-{1,2}[a-z0-9]+)*$'
    and length(asset_slug) between 3 and 120
  ),

  -- Raster only, sniffed. SVG and GIF are refused by the ingest; this is the
  -- backstop.
  constraint concept_assets_content_type_enum check (
    content_type in ('image/png', 'image/jpeg', 'image/webp')
  ),

  -- Dimension floor, ceiling, LANDSCAPE, and a hard byte cap. Justified in
  -- scripts/ingest_asset.py: every asset is BUNDLED into the app binary
  -- (lib/widgets/CLAUDE.md §3, "never fetch at render time"), so an asset's
  -- size is paid by every student on every install.
  --
  -- width > height is not cosmetic: docs/label-layer.md §2.2 pins the label
  -- columns to the ART's edges, so a portrait plate leaves ~177pt of art width
  -- at the 343x236 board and tightens the §2.5 anchor separation from 0.032 to
  -- 0.057 in u. A portrait plate is a different layout problem.
  constraint concept_assets_dimensions_sane check (
    width  between 400 and 8000
    and height between 400 and 8000
    and width > height
    and bytes  between 1024 and 2097152   -- 1 KiB .. 2 MiB
  )
);

-- ------------------------------------------------------------------- indexes
create index if not exists concept_assets_concept_idx
  on public.concept_assets (concept_id) where concept_id is not null;

create index if not exists concept_assets_chapter_idx
  on public.concept_assets (chapter_id) where chapter_id is not null;

-- The backlog read: what still needs a human to check the syllabus gap.
create index if not exists concept_assets_ungapped_idx
  on public.concept_assets (subject, class_level) where syllabus_gap is null;

-- ---------------------------------------------------------------- updated_at
create or replace function public.concept_assets_touch()
returns trigger language plpgsql as $$
begin
  new.updated_at := now();
  return new;
end;
$$;

drop trigger if exists concept_assets_touch_trg on public.concept_assets;
create trigger concept_assets_touch_trg
  before update on public.concept_assets
  for each row execute function public.concept_assets_touch();

-- ------------------------------------------------------------------------ RLS
-- Same posture as concept_diagrams: readable by any signed-in student, written
-- only by the service role that runs the ingest. Note there is no insert or
-- update policy at all — the service role bypasses RLS, and nothing else should
-- ever be writing here.
alter table public.concept_assets enable row level security;

drop policy if exists concept_assets_read on public.concept_assets;
create policy concept_assets_read on public.concept_assets
  for select to authenticated using (true);

commit;

-- --------------------------------------------------------------- verification
-- Run these after applying. The first five MUST raise. If any of them succeeds,
-- this migration did not do its job and the sixth provenance failure becomes
-- the seventh.
--
--   -- 1. missing licence  -> 23502 not-null violation
--   insert into concept_assets
--     (asset_slug, r2_key, content_type, width, height, bytes,
--      source_url, author, anchor_book, generator_model, prompt_sha,
--      text_check, labelled_reference_file, labelled_reference_sha256,
--      arrived_labelled, manifest_status)
--   values ('bio11-ch4-phylum-porifera', 'concept-assets/probe.png', 'image/png',
--           1600, 1000, 200000, 'https://archive.org/details/x', 'Monk Learning',
--           'Parker & Haswell — A Text-Book of Zoology (1897–1928 editions)',
--           'gemini-3-pro-image', '0123456789abcdef',
--           'heuristic-clean-ocr-unavailable', 'x.labelled.png', repeat('a',64),
--           'unlabelled', 'approved');
--
--   -- 2. placeholder author -> 23514 concept_assets_no_placeholders
--   ... as above, with licence 'PD-old-70' and author 'unknown'
--
--   -- 3. share-alike -> 23514 concept_assets_licence_enum
--   ... with licence 'CC-BY-SA-4.0'
--
--   -- 4. bare model name -> 23514 concept_assets_no_placeholders
--   ... with generator_model 'gemini'
--
--   -- 5. portrait plate -> 23514 concept_assets_dimensions_sane
--   ... with width 1000, height 1600
--
-- Then, once rows exist:
--
--   -- how many assets were never really checked for burnt-in text
--   select text_check, count(*) from concept_assets group by 1;
--
--   -- the backlog of figures no subject author has reviewed
--   select count(*) from concept_assets where syllabus_gap is null;
--
--   -- a uniform provenance column is the page_start shape. Some of these WILL
--   -- be uniform within one work order; that is fine, but it should be a fact
--   -- somebody has seen rather than one nobody has looked at.
--   select licence, count(*)         from concept_assets group by 1 order by 2 desc;
--   select generator_model, count(*) from concept_assets group by 1;
--   select prompt_sha, count(*)      from concept_assets group by 1;
--
--   -- there must be no share-alike anywhere, ever
--   select count(*) from concept_assets where licence like '%SA%';   -- 0
--
--   -- every row's object must exist in R2. There is no SQL for that:
--   python3 scripts/ingest_asset.py verify

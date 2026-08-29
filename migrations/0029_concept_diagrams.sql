-- Precomputed board diagrams, one per concept.
--
-- The third tier of diagram resolution, and the fastest. Templates take
-- PARAMETERS; these take the topic and what is being explained about it, which
-- is what lets a diagram be drawn for THIS segment rather than for the shape in
-- general. They are authored once at plan time and replayed instantly forever,
-- so the best diagram is also the cheapest one to serve.
--
-- Resolution order at teach time, fastest first:
--   1. this table          — instant
--   2. a template cue      — instant, ~0.1ms of string building
--   3. live authoring      — 4-10s, run in parallel and raced against the
--                            sentence that introduces it; dropped if it loses
--
-- Only 191 of 1,154 concepts currently match a template cue, so the other 963
-- have no diagram at all today. Class 11 Physics chapter 1 is a clean example:
-- all 8 of its concepts get no cue whatsoever.
--
-- svg is stored rendered rather than as parameters because there is nothing to
-- parameterise — it is authored markup. It has already passed
-- diagram_author.validate() before it lands here, and validation runs again on
-- read, since a row could predate a tightening of the rules.

create table if not exists concept_diagrams (
  id           uuid primary key default gen_random_uuid(),
  concept_id   uuid not null references concepts(id) on delete cascade,
  svg          text not null,
  caption      text,
  -- What produced it, so a bad batch can be found and re-authored by model
  -- rather than by hand.
  source_model text,
  -- The explanation the diagram was drawn FOR. Two diagrams of the same
  -- concept can legitimately differ if they emphasise different things, and
  -- without this there is no way to tell which one a segment wanted.
  drawn_for    text,
  created_at   timestamptz not null default now(),
  -- Retire without deleting, exactly as concepts.active does. A diagram that
  -- turns out wrong should stop being served immediately without losing the
  -- record of what was served before.
  active       boolean not null default true
);

-- The read is always "the live diagram for this concept", so index for it.
create index if not exists idx_concept_diagrams_concept
  on concept_diagrams (concept_id) where active;

alter table concept_diagrams enable row level security;

-- Same posture as the rest of the taxonomy: readable by any signed-in student,
-- written only by the service role that runs the authoring job.
drop policy if exists concept_diagrams_read on concept_diagrams;
create policy concept_diagrams_read on concept_diagrams
  for select to authenticated using (true);

-- Verify:
--   SELECT count(*) FROM concept_diagrams WHERE active;
--   SELECT c.name, length(d.svg) FROM concept_diagrams d
--     JOIN concepts c ON c.id = d.concept_id
--    WHERE d.active ORDER BY c.name;

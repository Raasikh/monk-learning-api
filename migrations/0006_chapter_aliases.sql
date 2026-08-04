begin;

create table if not exists chapter_aliases (
  id            uuid primary key default gen_random_uuid(),
  chapter_id    uuid not null references chapters(id) on delete cascade,
  alias         text not null,
  alias_norm    text not null,           -- lowercase, alnum only, spaces collapsed
  source        text not null,           -- 'pdf_filename' | 'coaching' | 'manual'
  evidence_text text,                    -- quoted first-page proof text
  approved_by   text,                    -- set by human (e.g. 'Nikhil')
  created_at    timestamptz not null default now()
);

create unique index if not exists chapter_aliases_norm_idx
  on chapter_aliases (alias_norm);
create index if not exists chapter_aliases_chapter_idx
  on chapter_aliases (chapter_id);

alter table chapter_aliases enable row level security;
drop policy if exists chapter_aliases_public_read on chapter_aliases;
create policy chapter_aliases_public_read
  on chapter_aliases for select using (true);

commit;

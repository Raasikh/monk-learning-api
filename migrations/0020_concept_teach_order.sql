-- 0020 — teach_order on concepts
--
-- concepts.display_order is NOT a teaching sequence, despite what its comment
-- in 0017 says. It was populated from exam frequency, so Gravitation currently
-- reads: 1 Gravitational Potential Energy, ... 5 Newton's Law of Gravitation.
-- No teacher opens gravitation with potential energy and reaches the inverse
-- square law halfway through — PE is derived FROM that law.
--
-- Learn-with-Drona is moving from subtopic_index to concepts as its unit of
-- instruction, which means the order concepts are offered in becomes the order
-- a student is taught. display_order stays as-is (Progress ranks by it, and
-- frequency ranking is genuinely what Progress wants); teach_order is the
-- separate pedagogical sequence, assigned per chapter.
--
-- NULL means "not yet sequenced" — callers fall back to display_order so a
-- chapter that has not been ordered still renders in a stable order rather
-- than an arbitrary one.

alter table concepts
  add column if not exists teach_order smallint;

comment on column concepts.teach_order is
  'Pedagogical teaching sequence within the chapter, 1..N. NULL = not yet sequenced; fall back to display_order. Distinct from display_order, which ranks by exam frequency.';

-- Ordering reads are always "this chapter, in teaching order".
create index if not exists idx_concepts_chapter_teach_order
  on concepts (chapter_id, teach_order);

-- Within a chapter, a teaching position is unique when assigned. Partial so the
-- unsequenced (NULL) rows don't collide with each other.
create unique index if not exists idx_concepts_chapter_teach_order_unique
  on concepts (chapter_id, teach_order)
  where teach_order is not null;

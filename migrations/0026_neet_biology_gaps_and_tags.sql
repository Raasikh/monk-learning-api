-- Close the NEET gaps a three-way biology and physics/chemistry audit found.
--
-- The earlier six-agent sweep audited the 74 JEE chapters only. Biology — 32
-- chapters, 349 concepts, roughly half the NEET paper — had never been checked
-- at all, and nothing had verified the exam tags against the NEET syllabus.
-- Three more auditors closed that, working from the official NTA/NMC "Updated
-- syllabus for NEET (UG)-2026" notice.
--
-- The result is reassuring: biology needed 4 concepts across 32 chapters, and
-- NO chapter is missing. The three NCERT chapters absent from Class 11
-- (Transport in Plants, Mineral Nutrition, Digestion and Absorption) and the
-- three from Class 12 (Reproduction in Organisms, Strategies for Enhancement
-- in Food Production, Environmental Issues) were each confirmed absent from
-- the CURRENT syllabus too — correctly omitted, not gaps.
--
-- One addition is a deliberate judgement call. The NEET 2026 syllabus names
-- five plant families verbatim (malvaceae, Cruciferae, leguminoceae,
-- compositae, graminae) while the rationalised NCERT retains only Solanaceae,
-- which is what the taxonomy taught. This follows the published SYLLABUS,
-- because that is what NEET examines from — but it means teaching four
-- families the current textbook dropped, and is the one row here to reverse
-- first if that call turns out wrong.

BEGIN;

-- ── teach_order shifts ─────────────────────────────────────────────────────
-- Two-phase, because a unique index on (chapter_id, teach_order) is checked
-- per row: a bare +1 collides the moment one row lands on the next. Park the
-- block above every real value, then bring it back. See 0025.

-- Evolution: make room at position 7
UPDATE concepts SET teach_order = teach_order + 1000
  WHERE chapter_id = '2361816c-f597-5cd6-bff3-596fa5a6a367' AND teach_order >= 7;
UPDATE concepts SET teach_order = teach_order - 999
  WHERE chapter_id = '2361816c-f597-5cd6-bff3-596fa5a6a367' AND teach_order >= 1000;

-- Plant Growth and Development: make room at position 1
UPDATE concepts SET teach_order = teach_order + 1000
  WHERE chapter_id = 'c62f8ffd-c8bd-5381-9384-1ef60fe91c5d' AND teach_order >= 1;
UPDATE concepts SET teach_order = teach_order - 999
  WHERE chapter_id = 'c62f8ffd-c8bd-5381-9384-1ef60fe91c5d' AND teach_order >= 1000;

INSERT INTO concepts (chapter_id, key, name, teach_order, display_order, exams, active)
VALUES
  -- biol11 Morphology of Flowering Plants
  ('ca9c37dd-ac72-50d6-96bf-fb3da5aba16e', 'families-malvaceae-cruciferae-leguminosae-compositae-and-graminae', 'Families Malvaceae, Cruciferae, Leguminosae, Compositae and Graminae', 12, 12, ARRAY['neet'], true),
  -- biol11 Plant Growth and Development
  ('c62f8ffd-c8bd-5381-9384-1ef60fe91c5d', 'seed-germination-and-conditions-for-growth', 'Seed Germination and Conditions for Growth', 1, 11, ARRAY['neet'], true),
  -- biol11 Chemical Coordination and Integration
  ('31720c9d-1ae5-5661-b381-2262ee60b422', 'hypo-and-hyperactivity-disorders-of-the-endocrine-glands', 'Hypo- and Hyperactivity Disorders of the Endocrine Glands', 14, 14, ARRAY['neet'], true),
  -- biol12 Evolution
  ('2361816c-f597-5cd6-bff3-596fa5a6a367', 'types-of-natural-selection-stabilising-directional-and-disruptive', 'Types of Natural Selection: Stabilising, Directional and Disruptive', 7, 12, ARRAY['neet'], true);

-- ── one concept is mis-scoped rather than missing ──────────────────────────
-- Amoebiasis (Entamoeba histolytica) is named explicitly in the NEET 2026
-- syllabus, and the only protozoan concept in the taxonomy is malaria-specific
-- — so protozoan disease had no home. This is a rename, not a new concept:
-- the lesson is generated from the concept NAME, so a name that omits
-- "protozoan" will not teach it.
UPDATE concepts
   SET name = 'Common Infectious Diseases: Bacterial, Viral, Fungal, Protozoan and Helminthic'
 WHERE id = 'f1c98643-dacf-459c-b766-c8dd70c83eed';

-- ── exam tags: JEE-only concepts that NEET also requires ───────────────────
-- Dispersion by a prism, angular dispersion and dispersive power are retained
-- NCERT Ch 9 content and the NEET optics unit lists prisms explicitly. Only
-- the achromatic-combination half leans JEE.
UPDATE concepts SET exams = ARRAY['jee','neet'] WHERE id = 'de696554-6577-48ae-935d-091b012f5a3e';

-- Energy density and momentum of EM waves survive in the rationalised NCERT
-- Ch 8 and are NEET-examinable; only radiation pressure skews JEE.
UPDATE concepts SET exams = ARRAY['jee','neet'] WHERE id = '91b9e72c-8eec-4643-9d65-c675f29a3ca2';

COMMIT;

-- Expect 4 inserted, 3 updated by the tag/rename statements, 2 shifts.
-- Verify:
--   SELECT count(*) FROM concepts WHERE active;   -- 1149 -> 1153

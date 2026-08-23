-- Add the 23 JEE concepts a six-way syllabus audit found missing, fix one exam
-- tag, and move Linear Programming off the scored syllabus without hiding it.
--
-- Six independent auditors, one per subject-and-class, checked all 74 JEE
-- chapters against the official JEE (Advanced) 2026 syllabus PDF and the NTA
-- JEE (Main) 2026 syllabus. 50 of the 74 came back clean.
--
-- The largest gap was Class 11 Complex Numbers. The NCERT chapter is "Complex
-- Numbers AND Quadratic Equations" and only the complex half existed — nature
-- of roots, relations between roots and coefficients, symmetric functions,
-- formation of equations and the common-root condition were all absent, a
-- recurring JEE Main question type with nothing behind it. Three of the
-- concepts below close it.
--
-- Two proposals were REJECTED on checking, which is why this is 23 and not 25.
-- Henry's Law for Class 11 Equilibrium already exists in Class 12 Solutions,
-- and adding it would have recreated exactly the duplicate mastery row that
-- migrations 0022-0024 removed. And the widely-repeated claim that Alcohols,
-- Phenols & Ethers was deleted from JEE Main is wrong — NTA Unit 17 retains it
-- in reduced form and JEE Advanced retains it in full.
--
-- NOTE ON THE FIRST ATTEMPT AT THIS FILE: it generated each row's trailing
-- comma AFTER its trailing `-- comment`, so the comma separating every VALUES
-- row was inside a comment and the statement could not parse. Nothing landed —
-- the shifts below leave a gap in teach_order and no gap was present, which is
-- how the rollback was confirmed. Comments now sit ABOVE their row.
--
-- display_order is set explicitly on every row rather than defaulted. It is
-- NOT NULL on all 1,126 existing rows and /progress sorts a chapter's concepts
-- with `c.get("display_order", 99)`, which returns None for a key holding NULL;
-- comparing None to an int raises. A NULL here would take the endpoint down.

BEGIN;

-- ── teach_order shifts ─────────────────────────────────────────────────────
-- 20 of the 23 concepts append to the end of their chapter, which is right for
-- an advanced topic that builds on everything before it. These three slot
-- mid-sequence instead, because appending would teach them out of order:
-- turbulent flow must precede Bernoulli, symmetric difference belongs beside
-- the other set operations, and L'Hopital's rule belongs with the limits
-- rather than after the derivatives. Run in DESCENDING position so no row
-- lands on one that has not moved yet.

-- Limits and Derivatives: make room at position 8
UPDATE concepts SET teach_order = teach_order + 1
  WHERE chapter_id = 'b5fa886e-012b-5425-9399-a8249254a151' AND teach_order >= 8;

-- Sets: make room at position 6
UPDATE concepts SET teach_order = teach_order + 1
  WHERE chapter_id = 'b4f9bb1a-a366-5e67-ae76-52ffd1dd8a67' AND teach_order >= 6;

-- Mechanical Properties of Fluids: make room at position 5
UPDATE concepts SET teach_order = teach_order + 1
  WHERE chapter_id = '33795397-f8fe-5ef6-ba2d-64549905ecd3' AND teach_order >= 5;

INSERT INTO concepts (chapter_id, key, name, teach_order, display_order, exams, active)
VALUES
  -- phys11 Laws of Motion
  ('50ae6550-951b-599c-b352-1d6e5f84bc3b', 'non-inertial-frames-and-pseudo-forces', 'Non-Inertial Frames and Pseudo Forces', 9, 9, ARRAY['jee','neet'], true),
  -- phys11 Rotational Motion
  ('262da95c-2f3a-56da-905e-003fa8f0e4dc', 'angular-impulse-and-collisions-with-rigid-bodies', 'Angular Impulse and Collisions with Rigid Bodies', 11, 11, ARRAY['jee'], true),
  -- phys11 Mechanical Properties of Fluids
  ('33795397-f8fe-5ef6-ba2d-64549905ecd3', 'turbulent-flow-critical-velocity-and-reynolds-number', 'Turbulent Flow, Critical Velocity and Reynolds Number', 5, 11, ARRAY['jee','neet'], true),
  -- phys11 Thermal Properties of Matter
  ('087ea53b-681c-51a2-92ef-5ea77f6bdf8b', 'blackbody-radiation-and-wien-s-displacement-law', 'Blackbody Radiation and Wien''s Displacement Law', 10, 10, ARRAY['jee','neet'], true),
  -- phys12 Current Electricity
  ('5bd38ee4-dc52-5144-89a3-a51bbb35af15', 'capacitor-charging-and-discharging-in-rc-circuits', 'Capacitor Charging and Discharging in RC Circuits', 12, 12, ARRAY['jee'], true),
  -- phys12 Electromagnetic Induction
  ('b8223a22-15d4-5760-886f-53750c7dc9e8', 'growth-and-decay-of-current-in-an-lr-circuit', 'Growth and Decay of Current in an LR Circuit', 11, 11, ARRAY['jee'], true),
  -- phys12 Ray Optics and Optical Instruments
  ('5c6a37c7-67be-5575-a3cc-456df9937cfa', 'combination-of-mirrors-and-lenses', 'Combination of Mirrors and Lenses', 13, 13, ARRAY['jee'], true),
  -- phys12 Atoms
  ('0365e7bf-d5d9-5b52-afd0-cd2ae522284c', 'moseley-s-law-and-x-ray-spectra', 'Moseley''s Law and X-ray Spectra', 9, 9, ARRAY['jee'], true),
  -- chem11 Chemical Bonding
  ('862ab5f0-4fa8-5e6f-98d5-74fe5b10ab8e', 'metallic-bonding-and-the-electron-sea-model', 'Metallic Bonding and the Electron Sea Model', 14, 14, ARRAY['jee','neet'], true),
  -- chem11 Thermodynamics
  ('a6961d73-9ca9-5716-8e0c-61c69c5e343f', 'enthalpies-of-phase-transition-atomisation-hydration-and-solution', 'Enthalpies of Phase Transition, Atomisation, Hydration and Solution', 13, 13, ARRAY['jee','neet'], true),
  -- chem11 General Organic Chemistry
  ('15bf6c7a-ff09-5741-93b8-e48e8a915273', 'diastereomers-meso-compounds-and-molecules-with-two-stereocentres', 'Diastereomers, Meso Compounds and Molecules with Two Stereocentres', 14, 14, ARRAY['jee','neet'], true),
  -- chem11 Hydrocarbons
  ('388fccf5-9390-50aa-b678-5800a9e4fffa', 'polymerisation-of-alkenes-and-cyclic-polymerisation-of-alkynes', 'Polymerisation of Alkenes and Cyclic Polymerisation of Alkynes', 13, 13, ARRAY['jee','neet'], true),
  -- chem12 Chemical Kinetics
  ('0f327c85-1a68-50d9-a9bd-44fd17ed88b7', 'homogeneous-and-heterogeneous-catalysis', 'Homogeneous and Heterogeneous Catalysis', 12, 12, ARRAY['jee'], true),
  -- chem12 d-and-f-Block Elements
  ('03b28b70-7318-558a-a728-f505fc592e5a', 'ionisation-enthalpy-trends-in-the-transition-series', 'Ionisation Enthalpy Trends in the Transition Series', 14, 14, ARRAY['jee','neet'], true),
  -- chem12 Alcohols, Phenols & Ethers
  ('7f0847a6-736a-5b04-8626-3978781672eb', 'oxidation-and-reduction-of-phenols', 'Oxidation and Reduction of Phenols', 13, 13, ARRAY['jee','neet'], true),
  -- chem12 Aldehydes, Ketones & Carboxylic Acids
  ('62483989-6f22-51ab-8ca1-f687ec124a9d', 'haloform-reaction', 'Haloform Reaction', 15, 15, ARRAY['jee','neet'], true),
  -- math11 Sets
  ('b4f9bb1a-a366-5e67-ae76-52ffd1dd8a67', 'symmetric-difference-of-sets', 'Symmetric Difference of Sets', 6, 10, ARRAY['jee'], true),
  -- math11 Complex Numbers
  ('ea46f354-2c41-542e-bf5c-e990c56d2a1d', 'nature-of-roots-and-the-discriminant', 'Nature of Roots and the Discriminant', 12, 12, ARRAY['jee'], true),
  -- math11 Complex Numbers
  ('ea46f354-2c41-542e-bf5c-e990c56d2a1d', 'relations-between-roots-and-coefficients-and-symmetric-functions-of-roots', 'Relations Between Roots and Coefficients and Symmetric Functions of Roots', 13, 13, ARRAY['jee'], true),
  -- math11 Complex Numbers
  ('ea46f354-2c41-542e-bf5c-e990c56d2a1d', 'formation-of-quadratic-equations-and-condition-for-a-common-root', 'Formation of Quadratic Equations and Condition for a Common Root', 14, 14, ARRAY['jee'], true),
  -- math11 Conic Sections
  ('ce3b1755-7eb0-5e16-9849-e752cca5f723', 'relative-position-of-two-circles-and-common-tangents', 'Relative Position of Two Circles and Common Tangents', 12, 12, ARRAY['jee'], true),
  -- math11 Limits and Derivatives
  ('b5fa886e-012b-5425-9399-a8249254a151', 'l-hopital-s-rule-for-indeterminate-forms', 'L''Hopital''s Rule for Indeterminate Forms', 8, 12, ARRAY['jee'], true),
  -- math12 Continuity and Differentiability
  ('ec4d9f55-c416-51a4-ae90-2d1b2cb685aa', 'continuity-of-composite-functions-and-the-intermediate-value-property', 'Continuity of Composite Functions and the Intermediate Value Property', 13, 13, ARRAY['jee'], true);

-- ── exam tags ──────────────────────────────────────────────────────────────
-- Hormones was the only concept in the entire JEE corpus tagged neet-only,
-- and JEE Main 2026 Unit 19 explicitly retains "Hormones (General
-- introduction)".
UPDATE concepts SET exams = ARRAY['jee','neet']
 WHERE id = '8375293c-3f23-42b7-bea7-da64e23ba454';

-- Linear Programming is on NEITHER exam. The official JEE Advanced 2026
-- syllabus has no LP topic anywhere in Mathematics, NTA's 14 JEE Main
-- Mathematics units contain none either, and NEET has no mathematics at all.
-- It survives only as an NCERT/CBSE board chapter.
--
-- So it is retagged, NOT retired: board students revising should still find
-- it, but it must not move a Monk Score computed against JEE or NEET. Tagging
-- it 'board' does exactly that, and both readers were checked:
--   * the catalogue shows it while no exam is picked and hides it once a
--     student picks JEE or NEET (app/exam_scope.tagged_for_exam);
--   * /progress drops it from the concept list AND from the chapter mastery
--     denominator, so it cannot dilute a score (app/routers/progress.py).
--
-- An EMPTY array would NOT have worked: /progress reads
-- `exam in (c.get("exams") or ["jee","neet"])`, and an empty list is falsy, so
-- it falls back to scoring the concept under BOTH exams — the opposite of the
-- intent.
UPDATE concepts SET exams = ARRAY['board']
 WHERE chapter_id = 'f6a91395-aa95-5203-a5c0-b0cec8191539';  -- Linear Programming, Class 12 Mathematics (8 concepts)

COMMIT;

-- Expect: 23 inserted, 1 + 8 updated by the tag statements, 3 shift statements.
-- Verify:
--   SELECT count(*) FROM concepts WHERE active;                 -- 1126 -> 1149
--   SELECT name, exams FROM concepts WHERE name = 'Hormones and Their Functions';
--   SELECT DISTINCT exams FROM concepts c JOIN chapters ch ON ch.id = c.chapter_id
--    WHERE ch.name = 'Linear Programming';                      -- {board}

-- Add the 23 JEE concepts a six-way syllabus audit found missing, and fix one
-- exam tag.
--
-- Six independent auditors, one per subject-and-class, checked all 74 JEE
-- chapters against the official JEE (Advanced) 2026 syllabus PDF and the NTA
-- JEE (Main) 2026 syllabus. Each was told to report NO gap where a topic was
-- already covered under a different name, and most chapters came back clean:
-- 50 of 74 needed nothing.
--
-- The largest single gap was Class 11 Complex Numbers. The NCERT chapter is
-- "Complex Numbers AND Quadratic Equations" and only the complex half existed
-- — nature of roots, relations between roots and coefficients, symmetric
-- functions, formation of equations and the common-root condition were all
-- absent, which is a recurring JEE Main question type with nothing behind it.
-- Three of the concepts below close it.
--
-- Two proposals were REJECTED on checking, which is why the count is 23 and
-- not 25:
--   * Henry's Law for Class 11 Equilibrium — already present in Class 12
--     Solutions, and adding it would have created exactly the duplicate
--     mastery row that migrations 0022-0024 spent the day removing.
--   * "Alcohols, Phenols & Ethers has been deleted from JEE Main" — a claim
--     several aggregator sites make. It is wrong; NTA Unit 17 retains the
--     chapter in reduced form and JEE Advanced retains it in full.
--
-- display_order is set explicitly on every row, not left to default. It is
-- NOT NULL on all 1,126 existing rows and /progress sorts a chapter's concepts
-- with `c.get("display_order", 99)` — which returns None for a key that exists
-- holding NULL, and comparing None to an int raises. A NULL here would take
-- the endpoint down.
--
-- teach_order: 20 concepts append to the end of their chapter, which is the
-- right place for an advanced topic that builds on everything before it. The
-- other three slot mid-sequence and shift the concepts after them, because
-- appending would have taught them out of order: turbulent flow has to precede
-- Bernoulli, symmetric difference belongs beside the other set operations, and
-- L'Hopital's rule belongs with the limits rather than after the derivatives.
-- Those shifts run first and in descending position so no row lands on one
-- that has not moved yet.

UPDATE concepts SET teach_order = teach_order + 1
  WHERE chapter_id = 'b5fa886e-012b-5425-9399-a8249254a151' AND teach_order >= 8;
UPDATE concepts SET teach_order = teach_order + 1
  WHERE chapter_id = 'b4f9bb1a-a366-5e67-ae76-52ffd1dd8a67' AND teach_order >= 6;
UPDATE concepts SET teach_order = teach_order + 1
  WHERE chapter_id = '33795397-f8fe-5ef6-ba2d-64549905ecd3' AND teach_order >= 5;

INSERT INTO concepts (chapter_id, key, name, teach_order, display_order, exams, active)
VALUES
  ('50ae6550-951b-599c-b352-1d6e5f84bc3b', 'non-inertial-frames-and-pseudo-forces', 'Non-Inertial Frames and Pseudo Forces', 9, 9, ARRAY['jee','neet'], true)  -- phys11 Laws of Motion,
  ('262da95c-2f3a-56da-905e-003fa8f0e4dc', 'angular-impulse-and-collisions-with-rigid-bodies', 'Angular Impulse and Collisions with Rigid Bodies', 11, 11, ARRAY['jee'], true)  -- phys11 Rotational Motion,
  ('33795397-f8fe-5ef6-ba2d-64549905ecd3', 'turbulent-flow-critical-velocity-and-reynolds-number', 'Turbulent Flow, Critical Velocity and Reynolds Number', 5, 11, ARRAY['jee','neet'], true)  -- phys11 Mechanical Properties of Fluids,
  ('087ea53b-681c-51a2-92ef-5ea77f6bdf8b', 'blackbody-radiation-and-wien-s-displacement-law', 'Blackbody Radiation and Wien''s Displacement Law', 10, 10, ARRAY['jee','neet'], true)  -- phys11 Thermal Properties of Matter,
  ('5bd38ee4-dc52-5144-89a3-a51bbb35af15', 'capacitor-charging-and-discharging-in-rc-circuits', 'Capacitor Charging and Discharging in RC Circuits', 12, 12, ARRAY['jee'], true)  -- phys12 Current Electricity,
  ('b8223a22-15d4-5760-886f-53750c7dc9e8', 'growth-and-decay-of-current-in-an-lr-circuit', 'Growth and Decay of Current in an LR Circuit', 11, 11, ARRAY['jee'], true)  -- phys12 Electromagnetic Induction,
  ('5c6a37c7-67be-5575-a3cc-456df9937cfa', 'combination-of-mirrors-and-lenses', 'Combination of Mirrors and Lenses', 13, 13, ARRAY['jee'], true)  -- phys12 Ray Optics and Optical Instruments,
  ('0365e7bf-d5d9-5b52-afd0-cd2ae522284c', 'moseley-s-law-and-x-ray-spectra', 'Moseley''s Law and X-ray Spectra', 9, 9, ARRAY['jee'], true)  -- phys12 Atoms,
  ('862ab5f0-4fa8-5e6f-98d5-74fe5b10ab8e', 'metallic-bonding-and-the-electron-sea-model', 'Metallic Bonding and the Electron Sea Model', 14, 14, ARRAY['jee','neet'], true)  -- chem11 Chemical Bonding,
  ('a6961d73-9ca9-5716-8e0c-61c69c5e343f', 'enthalpies-of-phase-transition-atomisation-hydration-and-solution', 'Enthalpies of Phase Transition, Atomisation, Hydration and Solution', 13, 13, ARRAY['jee','neet'], true)  -- chem11 Thermodynamics,
  ('15bf6c7a-ff09-5741-93b8-e48e8a915273', 'diastereomers-meso-compounds-and-molecules-with-two-stereocentres', 'Diastereomers, Meso Compounds and Molecules with Two Stereocentres', 14, 14, ARRAY['jee','neet'], true)  -- chem11 General Organic Chemistry,
  ('388fccf5-9390-50aa-b678-5800a9e4fffa', 'polymerisation-of-alkenes-and-cyclic-polymerisation-of-alkynes', 'Polymerisation of Alkenes and Cyclic Polymerisation of Alkynes', 13, 13, ARRAY['jee','neet'], true)  -- chem11 Hydrocarbons,
  ('0f327c85-1a68-50d9-a9bd-44fd17ed88b7', 'homogeneous-and-heterogeneous-catalysis', 'Homogeneous and Heterogeneous Catalysis', 12, 12, ARRAY['jee'], true)  -- chem12 Chemical Kinetics,
  ('03b28b70-7318-558a-a728-f505fc592e5a', 'ionisation-enthalpy-trends-in-the-transition-series', 'Ionisation Enthalpy Trends in the Transition Series', 14, 14, ARRAY['jee','neet'], true)  -- chem12 d-and-f-Block Elements,
  ('7f0847a6-736a-5b04-8626-3978781672eb', 'oxidation-and-reduction-of-phenols', 'Oxidation and Reduction of Phenols', 13, 13, ARRAY['jee','neet'], true)  -- chem12 Alcohols, Phenols & Ethers,
  ('62483989-6f22-51ab-8ca1-f687ec124a9d', 'haloform-reaction', 'Haloform Reaction', 15, 15, ARRAY['jee','neet'], true)  -- chem12 Aldehydes, Ketones & Carboxylic Acids,
  ('b4f9bb1a-a366-5e67-ae76-52ffd1dd8a67', 'symmetric-difference-of-sets', 'Symmetric Difference of Sets', 6, 10, ARRAY['jee'], true)  -- math11 Sets,
  ('ea46f354-2c41-542e-bf5c-e990c56d2a1d', 'nature-of-roots-and-the-discriminant', 'Nature of Roots and the Discriminant', 12, 12, ARRAY['jee'], true)  -- math11 Complex Numbers,
  ('ea46f354-2c41-542e-bf5c-e990c56d2a1d', 'relations-between-roots-and-coefficients-and-symmetric-functions-of-roots', 'Relations Between Roots and Coefficients and Symmetric Functions of Roots', 13, 13, ARRAY['jee'], true)  -- math11 Complex Numbers,
  ('ea46f354-2c41-542e-bf5c-e990c56d2a1d', 'formation-of-quadratic-equations-and-condition-for-a-common-root', 'Formation of Quadratic Equations and Condition for a Common Root', 14, 14, ARRAY['jee'], true)  -- math11 Complex Numbers,
  ('ce3b1755-7eb0-5e16-9849-e752cca5f723', 'relative-position-of-two-circles-and-common-tangents', 'Relative Position of Two Circles and Common Tangents', 12, 12, ARRAY['jee'], true)  -- math11 Conic Sections,
  ('b5fa886e-012b-5425-9399-a8249254a151', 'l-hopital-s-rule-for-indeterminate-forms', 'L''Hopital''s Rule for Indeterminate Forms', 8, 12, ARRAY['jee'], true)  -- math11 Limits and Derivatives,
  ('ec4d9f55-c416-51a4-ae90-2d1b2cb685aa', 'continuity-of-composite-functions-and-the-intermediate-value-property', 'Continuity of Composite Functions and the Intermediate Value Property', 13, 13, ARRAY['jee'], true)  -- math12 Continuity and Differentiability;

-- Hormones is the only concept in the whole JEE corpus tagged neet-only, and
-- JEE Main 2026 Unit 19 explicitly retains "Hormones (General introduction)".
UPDATE concepts SET exams = ARRAY['jee','neet']
 WHERE id = '8375293c-3f23-42b7-bea7-da64e23ba454';  -- Biomolecules (Class 12 Chemistry)

-- Expect 23 rows inserted and 1 updated.
-- Verify:
--   SELECT count(*) FROM concepts WHERE active;            -- 1126 -> 1149
--   SELECT name, exams FROM concepts WHERE name = 'Hormones and Their Functions';

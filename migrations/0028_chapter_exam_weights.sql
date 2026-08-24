-- Populate chapter_exam_weights: what each chapter is actually worth.
--
-- The table was created with 0017 and never filled, so /progress fell back to
-- `weights.get(ch["id"], 1.0)` for all 107 chapters. That is not a small
-- inaccuracy. Two things ran on it:
--
--   * The subject score is a weighted mean over chapters. With every weight at
--     1.0, mastering the single logarithms concept in Basic Mathematics moved
--     the Mathematics score exactly as much as mastering all 14 concepts in
--     Complex Numbers.
--   * `headroom = weight x (100 - mastery)` picks the "highest lever"
--     recommendation. Flat weights reduced that to "your weakest chapter",
--     with no notion of what a weakness actually costs in the exam.
--
-- Six researchers, one per subject PER EXAM — NEET and JEE weight physics and
-- chemistry very differently, and a JEE table applied to a NEET student would
-- be actively wrong. Each had to verify the paper structure itself and make
-- its figures sum to the real subject total, which is the check that catches a
-- plausible-looking table that does not add up:
--
--   JEE  physics / chemistry / mathematics   ->  100 each (25 Q x 4 marks)
--   NEET physics / chemistry                 ->  180 each (45 Q x 4 marks)
--   NEET biology                             ->  360     (90 Q x 4 marks)
--
-- All six landed exactly on target. Every row's UUID was then checked against
-- its chapter NAME, not merely that the id exists — that check caught a
-- transcription error where a valid-looking UUID pointed at nothing.
--
-- TWO FINDINGS WORTH KNOWING, both raised by the researchers unprompted:
--
-- 1. Source contamination is rife. PW, SelfStudys and Competishun republish
--    one identical 475-question dataset; vvtcoaching mirrors Vedantu's 5-year
--    table; eSaral and Resonance share a legacy table that still assigns 6.6%
--    to chapters deleted from the syllabus. "Cross-checking three sources"
--    here can easily mean checking one dataset three times. Where a number
--    below rests on fewer independent sources than it appears to, the
--    researcher said so rather than claiming corroboration it did not have.
--
-- 2. "Current Electricity is the highest-weightage physics chapter" is a
--    stale claim that propagates between sites. Testbook, eSaral and
--    Careers360 all say ~10%; the actual 2025 all-shift count says 3.58%. It
--    is set to 5.8 here — above one noisy year, well below the recycled
--    figure — and is the single number most worth revisiting against
--    2023-24 shift data.
--
-- Least-confident figures, recorded so they can be revisited rather than
-- rediscovered: Current Electricity (jee 5.8), Chemical Bonding (jee 5.5),
-- Application of Integrals (jee 3.6), Motion in a Plane (neet 7.0, no source
-- reports it as a standalone chapter), Neural Control and Coordination
-- (neet 7.0, likely too low), Aldehydes/Ketones/Carboxylic Acids (neet 10.3).
--
-- Linear Programming is deliberately 0: it is on neither exam. /progress skips
-- the chapter entirely, so the row is never read — it records the decision.

BEGIN;

-- Idempotent: re-running replaces rather than duplicating. The primary key is
-- (chapter_id, exam).
DELETE FROM chapter_exam_weights;

-- ── JEE CHEMISTRY · 19 chapters · sums to 100.0 ──────────────────
-- JEE Main chemistry. SUM = 100.0 exact.
-- Primary source: a complete census of 475 real questions across 19 shifts of
-- JEE Main 2025 (Jan counts sum to exactly 250 = 10 shifts x 25, April to 225
-- = 9 x 25), reconciled against an independent 5-year percentage table.
-- 8.9 marks redistributed by CONTENT AFFINITY from chapters this product does
-- not carry (Practical Chemistry 2.74, p-Block 15-18 2.11, p-Block cls11 1.89).
INSERT INTO chapter_exam_weights (chapter_id, exam, avg_marks, source_url)
VALUES
  -- cls11 Some Basic Concepts
  ('fa37da68-46a0-562f-9c75-2967215b8893', 'jee', 5.2, 'vedantu.com/pw.live JEE 2025 census (475 questions, 19 shifts) + pw.live 5-year table'),
  -- cls11 Atomic Structure
  ('16bf043d-bc59-5ebb-93ad-7b0fddf484c9', 'jee', 4.0, 'vedantu.com/pw.live JEE 2025 census (475 questions, 19 shifts) + pw.live 5-year table'),
  -- cls11 Classification of Elements
  ('aac04619-0e94-5a09-99bb-abdc2b688290', 'jee', 5.8, 'vedantu.com/pw.live JEE 2025 census (475 questions, 19 shifts) + pw.live 5-year table'),
  -- cls11 Chemical Bonding
  ('862ab5f0-4fa8-5e6f-98d5-74fe5b10ab8e', 'jee', 5.5, 'vedantu.com/pw.live JEE 2025 census (475 questions, 19 shifts) + pw.live 5-year table'),
  -- cls11 Thermodynamics
  ('a6961d73-9ca9-5716-8e0c-61c69c5e343f', 'jee', 6.4, 'vedantu.com/pw.live JEE 2025 census (475 questions, 19 shifts) + pw.live 5-year table'),
  -- cls11 Equilibrium
  ('f111ba16-c07d-5237-b2dd-eab22645f161', 'jee', 6.0, 'vedantu.com/pw.live JEE 2025 census (475 questions, 19 shifts) + pw.live 5-year table'),
  -- cls11 Redox Reactions
  ('c6da3467-e267-576e-9999-a2687ffe9200', 'jee', 1.9, 'vedantu.com/pw.live JEE 2025 census (475 questions, 19 shifts) + pw.live 5-year table'),
  -- cls11 General Organic Chemistry
  ('15bf6c7a-ff09-5741-93b8-e48e8a915273', 'jee', 8.2, 'vedantu.com/pw.live JEE 2025 census (475 questions, 19 shifts) + pw.live 5-year table'),
  -- cls11 Hydrocarbons
  ('388fccf5-9390-50aa-b678-5800a9e4fffa', 'jee', 4.2, 'vedantu.com/pw.live JEE 2025 census (475 questions, 19 shifts) + pw.live 5-year table'),
  -- cls12 Solutions
  ('f95d6af7-2754-5516-8d74-c4455dfc6ea2', 'jee', 5.5, 'vedantu.com/pw.live JEE 2025 census (475 questions, 19 shifts) + pw.live 5-year table'),
  -- cls12 Electrochemistry
  ('cf08cf74-67bb-5439-8375-68b0422c88af', 'jee', 4.7, 'vedantu.com/pw.live JEE 2025 census (475 questions, 19 shifts) + pw.live 5-year table'),
  -- cls12 Chemical Kinetics
  ('0f327c85-1a68-50d9-a9bd-44fd17ed88b7', 'jee', 5.0, 'vedantu.com/pw.live JEE 2025 census (475 questions, 19 shifts) + pw.live 5-year table'),
  -- cls12 d-and-f-Block Elements
  ('03b28b70-7318-558a-a728-f505fc592e5a', 'jee', 6.2, 'vedantu.com/pw.live JEE 2025 census (475 questions, 19 shifts) + pw.live 5-year table'),
  -- cls12 Coordination Compounds
  ('b31d7996-66b8-5dc7-8e3b-95ddc4516a92', 'jee', 8.5, 'vedantu.com/pw.live JEE 2025 census (475 questions, 19 shifts) + pw.live 5-year table'),
  -- cls12 Haloalkanes & Haloarenes
  ('54af5da8-ed02-5dff-90b6-a6c2a9f5928d', 'jee', 3.9, 'vedantu.com/pw.live JEE 2025 census (475 questions, 19 shifts) + pw.live 5-year table'),
  -- cls12 Alcohols, Phenols & Ethers
  ('7f0847a6-736a-5b04-8626-3978781672eb', 'jee', 3.6, 'vedantu.com/pw.live JEE 2025 census (475 questions, 19 shifts) + pw.live 5-year table'),
  -- cls12 Aldehydes, Ketones & Carboxylic Acids
  ('62483989-6f22-51ab-8ca1-f687ec124a9d', 'jee', 6.9, 'vedantu.com/pw.live JEE 2025 census (475 questions, 19 shifts) + pw.live 5-year table'),
  -- cls12 Amines
  ('64cfe65f-4cd9-52be-b436-f18793383afd', 'jee', 4.2, 'vedantu.com/pw.live JEE 2025 census (475 questions, 19 shifts) + pw.live 5-year table'),
  -- cls12 Biomolecules
  ('700ce9b5-8bfc-5c4b-bdb9-5a74738c2af4', 'jee', 4.3, 'vedantu.com/pw.live JEE 2025 census (475 questions, 19 shifts) + pw.live 5-year table');

-- ── JEE MATHEMATICS · 28 chapters · sums to 100.0 ──────────────────
-- JEE Main mathematics. SUM = 100.0 (25 questions x 4 marks).
-- Two 2025 censuses that agree EXACTLY on Coordinate Geometry (73/475),
-- Matrices & Determinants (33/475) and P&C (21/475) -- strong validation --
-- blended with a 5-year table, leaning recent where they diverge.
-- Two chapter-mapping calls drive the two largest numbers: Quadratic Equations
-- has no chapter of its own and its ~3.4 marks fold into Complex Numbers
-- (whose concept list genuinely carries discriminant/nature-of-roots), and
-- Conic Sections carries Circle + Parabola + Ellipse + Hyperbola.
INSERT INTO chapter_exam_weights (chapter_id, exam, avg_marks, source_url)
VALUES
  -- cls11 Basic Mathematics
  ('b0a51c00-0000-4000-8000-000000000001', 'jee', 0.5, 'careers360 14-unit census (475 questions) + pw.live 2025 shift counts'),
  -- cls11 Sets
  ('b4f9bb1a-a366-5e67-ae76-52ffd1dd8a67', 'jee', 2.2, 'careers360 14-unit census (475 questions) + pw.live 2025 shift counts'),
  -- cls11 Relations & Functions
  ('e38cf062-e572-52f4-9099-eaf6ee0f7b27', 'jee', 2.6, 'careers360 14-unit census (475 questions) + pw.live 2025 shift counts'),
  -- cls11 Trigonometry
  ('fab8d5c4-68ad-5772-8888-f5b1cd687633', 'jee', 3.1, 'careers360 14-unit census (475 questions) + pw.live 2025 shift counts'),
  -- cls11 Complex Numbers
  ('ea46f354-2c41-542e-bf5c-e990c56d2a1d', 'jee', 7.4, 'careers360 14-unit census (475 questions) + pw.live 2025 shift counts'),
  -- cls11 Linear Inequalities
  ('7bc767a8-c36f-5f5c-93f5-fb8337ffd7f5', 'jee', 0.6, 'careers360 14-unit census (475 questions) + pw.live 2025 shift counts'),
  -- cls11 Permutations & Combinations
  ('e8c7f4cb-b1a3-5c5e-99d7-4341c4618bb8', 'jee', 4.2, 'careers360 14-unit census (475 questions) + pw.live 2025 shift counts'),
  -- cls11 Binomial Theorem
  ('ad7f3197-f77b-5be6-8581-f5372ffb7797', 'jee', 4.6, 'careers360 14-unit census (475 questions) + pw.live 2025 shift counts'),
  -- cls11 Sequences & Series
  ('7936f031-5b80-5350-ad08-bc78bef84e12', 'jee', 6.0, 'careers360 14-unit census (475 questions) + pw.live 2025 shift counts'),
  -- cls11 Straight Lines
  ('5edf4eb2-af54-5da2-b8fa-bfbb3270e702', 'jee', 3.6, 'careers360 14-unit census (475 questions) + pw.live 2025 shift counts'),
  -- cls11 Conic Sections
  ('ce3b1755-7eb0-5e16-9849-e752cca5f723', 'jee', 10.6, 'careers360 14-unit census (475 questions) + pw.live 2025 shift counts'),
  -- cls11 Introduction to Three Dimensional Geometry
  ('f516713d-c4ae-43ee-a7b3-91b68e709cbf', 'jee', 0.5, 'careers360 14-unit census (475 questions) + pw.live 2025 shift counts'),
  -- cls11 Limits and Derivatives
  ('b5fa886e-012b-5425-9399-a8249254a151', 'jee', 3.5, 'careers360 14-unit census (475 questions) + pw.live 2025 shift counts'),
  -- cls11 Statistics
  ('be419d00-be96-52c5-9704-c4331213c6e9', 'jee', 2.6, 'careers360 14-unit census (475 questions) + pw.live 2025 shift counts'),
  -- cls11 Probability
  ('35830227-5b8e-5d97-a032-a5f775c28b07', 'jee', 1.2, 'careers360 14-unit census (475 questions) + pw.live 2025 shift counts'),
  -- cls12 Relations and Functions
  ('ced56f98-0bb4-5f30-a514-6927db4425ec', 'jee', 2.9, 'careers360 14-unit census (475 questions) + pw.live 2025 shift counts'),
  -- cls12 Inverse Trigonometric Functions
  ('8dcd67fd-ec13-5797-8dc5-4f91150ba056', 'jee', 2.1, 'careers360 14-unit census (475 questions) + pw.live 2025 shift counts'),
  -- cls12 Matrices
  ('7ac5ff35-3931-5f69-b2b2-c0c055a92aa8', 'jee', 3.2, 'careers360 14-unit census (475 questions) + pw.live 2025 shift counts'),
  -- cls12 Determinants
  ('ad2fbc00-f463-506b-aad6-b00c8dc4b32f', 'jee', 3.6, 'careers360 14-unit census (475 questions) + pw.live 2025 shift counts'),
  -- cls12 Continuity and Differentiability
  ('ec4d9f55-c416-51a4-ae90-2d1b2cb685aa', 'jee', 2.7, 'careers360 14-unit census (475 questions) + pw.live 2025 shift counts'),
  -- cls12 Applications of Derivatives
  ('48503325-cfe9-5bfd-8533-bb6f9cc53251', 'jee', 3.5, 'careers360 14-unit census (475 questions) + pw.live 2025 shift counts'),
  -- cls12 Integrals
  ('c663b4f9-59fd-5253-8c06-a1743f126ad9', 'jee', 6.8, 'careers360 14-unit census (475 questions) + pw.live 2025 shift counts'),
  -- cls12 Application of Integrals
  ('4aeaa5f2-e183-530c-abca-da24207c63f9', 'jee', 3.6, 'careers360 14-unit census (475 questions) + pw.live 2025 shift counts'),
  -- cls12 Differential Equations
  ('dd40f933-c8e5-5bd0-9ff8-c14656eeca8e', 'jee', 4.4, 'careers360 14-unit census (475 questions) + pw.live 2025 shift counts'),
  -- cls12 Vector Algebra
  ('e6db6ba6-3d6e-55fc-af55-34eaa2638788', 'jee', 4.8, 'careers360 14-unit census (475 questions) + pw.live 2025 shift counts'),
  -- cls12 Three Dimensional Geometry
  ('a02626b5-2eac-51f6-b406-22f0df7bd955', 'jee', 6.3, 'careers360 14-unit census (475 questions) + pw.live 2025 shift counts'),
  -- cls12 Linear Programming
  ('f6a91395-aa95-5203-a5c0-b0cec8191539', 'jee', 0, 'careers360 14-unit census (475 questions) + pw.live 2025 shift counts'),
  -- cls12 Probability
  ('e0a1f7f1-b810-5176-8dcd-676b98d0bbf3', 'jee', 2.9, 'careers360 14-unit census (475 questions) + pw.live 2025 shift counts');

-- ── JEE PHYSICS · 28 chapters · sums to 100.0 ──────────────────
-- JEE Main physics. SUM = 100.0 (25 questions x 4 marks).
-- Two genuinely independent chapter-level datasets blended ~50/50 (a 5-year
-- percentage table, renormalised from 94.59 to 100, and an all-shift count of
-- 475 questions from 2025), then sanity-checked against three coarser
-- topic-block sources. Block totals all land inside published ranges:
-- Mechanics 32.4, Heat & Thermo 9.1, Osc & Waves 5.2, Electrodynamics 29.1,
-- Optics 10.2, Modern Physics 14.0.
INSERT INTO chapter_exam_weights (chapter_id, exam, avg_marks, source_url)
VALUES
  -- cls11 Units & Measurements
  ('8d7ccfaa-af16-53e4-9f28-823c8ea923d1', 'jee', 5.4, 'pw.live JEE chapter weightage (2025 all-shift counts) + vedantu.com 5-year table'),
  -- cls11 Motion in a Straight Line
  ('563ae2b1-3427-537a-afde-f7fbc193731f', 'jee', 2.3, 'pw.live JEE chapter weightage (2025 all-shift counts) + vedantu.com 5-year table'),
  -- cls11 Motion in a Plane
  ('a5970ed6-3b48-55f9-9b80-8abdd3d4c336', 'jee', 2.6, 'pw.live JEE chapter weightage (2025 all-shift counts) + vedantu.com 5-year table'),
  -- cls11 Laws of Motion
  ('50ae6550-951b-599c-b352-1d6e5f84bc3b', 'jee', 2.5, 'pw.live JEE chapter weightage (2025 all-shift counts) + vedantu.com 5-year table'),
  -- cls11 Work, Energy & Power
  ('a88de5d2-84e4-5489-878a-f17a195e3267', 'jee', 2.8, 'pw.live JEE chapter weightage (2025 all-shift counts) + vedantu.com 5-year table'),
  -- cls11 Rotational Motion
  ('262da95c-2f3a-56da-905e-003fa8f0e4dc', 'jee', 7.2, 'pw.live JEE chapter weightage (2025 all-shift counts) + vedantu.com 5-year table'),
  -- cls11 Gravitation
  ('29b5be47-3b75-550d-9636-ad45a901d4dd', 'jee', 3.6, 'pw.live JEE chapter weightage (2025 all-shift counts) + vedantu.com 5-year table'),
  -- cls11 Mechanical Properties of Solids
  ('39bfe6d1-bd93-5157-a29c-b8ee68c3676b', 'jee', 1.8, 'pw.live JEE chapter weightage (2025 all-shift counts) + vedantu.com 5-year table'),
  -- cls11 Mechanical Properties of Fluids
  ('33795397-f8fe-5ef6-ba2d-64549905ecd3', 'jee', 4.2, 'pw.live JEE chapter weightage (2025 all-shift counts) + vedantu.com 5-year table'),
  -- cls11 Thermal Properties of Matter
  ('087ea53b-681c-51a2-92ef-5ea77f6bdf8b', 'jee', 2.4, 'pw.live JEE chapter weightage (2025 all-shift counts) + vedantu.com 5-year table'),
  -- cls11 Thermodynamics
  ('58c19132-676f-5dfb-b84e-e3a34b34a48e', 'jee', 3.9, 'pw.live JEE chapter weightage (2025 all-shift counts) + vedantu.com 5-year table'),
  -- cls11 Kinetic Theory
  ('8300dbf9-d9f7-505b-82c6-ad8d236eaff1', 'jee', 2.8, 'pw.live JEE chapter weightage (2025 all-shift counts) + vedantu.com 5-year table'),
  -- cls11 Oscillations
  ('c1bc937e-5ff5-5ecb-a67b-89053c386c23', 'jee', 2.8, 'pw.live JEE chapter weightage (2025 all-shift counts) + vedantu.com 5-year table'),
  -- cls11 Waves
  ('7dca7b5a-e77c-530d-bbe8-01a3518dc5d0', 'jee', 2.4, 'pw.live JEE chapter weightage (2025 all-shift counts) + vedantu.com 5-year table'),
  -- cls12 Electric Charges and Fields
  ('cf605dc6-faed-5c33-8107-81114cbfef79', 'jee', 4.6, 'pw.live JEE chapter weightage (2025 all-shift counts) + vedantu.com 5-year table'),
  -- cls12 Electrostatic Potential and Capacitance
  ('32366295-8398-526f-a430-cefdeea6d001', 'jee', 4.5, 'pw.live JEE chapter weightage (2025 all-shift counts) + vedantu.com 5-year table'),
  -- cls12 Current Electricity
  ('5bd38ee4-dc52-5144-89a3-a51bbb35af15', 'jee', 5.8, 'pw.live JEE chapter weightage (2025 all-shift counts) + vedantu.com 5-year table'),
  -- cls12 Moving Charges and Magnetism
  ('86b64ce4-24f5-5296-9cb2-f67b0989eca7', 'jee', 4.1, 'pw.live JEE chapter weightage (2025 all-shift counts) + vedantu.com 5-year table'),
  -- cls12 Magnetism and Matter
  ('cf5d01e5-1a4b-538b-9e72-4d7074b2f61d', 'jee', 1.3, 'pw.live JEE chapter weightage (2025 all-shift counts) + vedantu.com 5-year table'),
  -- cls12 Electromagnetic Induction
  ('b8223a22-15d4-5760-886f-53750c7dc9e8', 'jee', 2.7, 'pw.live JEE chapter weightage (2025 all-shift counts) + vedantu.com 5-year table'),
  -- cls12 Alternating Current
  ('69dbf2ca-bc1d-514e-a033-de1eefec09c9', 'jee', 3.2, 'pw.live JEE chapter weightage (2025 all-shift counts) + vedantu.com 5-year table'),
  -- cls12 Electromagnetic Waves
  ('e8e431d9-8966-55cc-b8f7-1ecc9427839f', 'jee', 2.9, 'pw.live JEE chapter weightage (2025 all-shift counts) + vedantu.com 5-year table'),
  -- cls12 Ray Optics and Optical Instruments
  ('5c6a37c7-67be-5575-a3cc-456df9937cfa', 'jee', 7.0, 'pw.live JEE chapter weightage (2025 all-shift counts) + vedantu.com 5-year table'),
  -- cls12 Wave Optics
  ('87df3af3-42ba-5439-ab4b-217b054ea81c', 'jee', 3.2, 'pw.live JEE chapter weightage (2025 all-shift counts) + vedantu.com 5-year table'),
  -- cls12 Dual Nature of Radiation and Matter
  ('b992c39b-0355-5fc6-bfb2-0ba5cc82411b', 'jee', 4.3, 'pw.live JEE chapter weightage (2025 all-shift counts) + vedantu.com 5-year table'),
  -- cls12 Atoms
  ('0365e7bf-d5d9-5b52-afd0-cd2ae522284c', 'jee', 2.6, 'pw.live JEE chapter weightage (2025 all-shift counts) + vedantu.com 5-year table'),
  -- cls12 Nuclei
  ('bea23d56-36e5-5c51-a69e-34e6cd374f9a', 'jee', 2.4, 'pw.live JEE chapter weightage (2025 all-shift counts) + vedantu.com 5-year table'),
  -- cls12 Semiconductor Electronics
  ('6e22ac90-425b-5336-9d44-81cc39afb062', 'jee', 4.7, 'pw.live JEE chapter weightage (2025 all-shift counts) + vedantu.com 5-year table');

-- ── NEET BIOLOGY · 32 chapters · sums to 360.0 ──────────────────
-- NEET biology. SUM = 360.0 (90 questions x 4 marks).
-- Botany block 181.0 / Zoology block 179.0 -- the paper GUARANTEES 45 questions
-- each, so after normalising four sources to 360 the blocks were rescaled to
-- their true 180 (Botany x0.868, Zoology x1.177). Proportional normalisation
-- alone left Botany at 207 and Zoology at 153, because multi-year PYQ
-- compilations over-sample genetics and predate the strict sectioning.
-- Zoology chapters systematically outweigh comparable Botany ones because the
-- rationalisation dropped 4 Botany-side chapters against only 2 Zoology-side:
-- fewer chapters competing for the same 45 questions.
INSERT INTO chapter_exam_weights (chapter_id, exam, avg_marks, source_url)
VALUES
  -- cls11 The Living World
  ('3087fd40-3dd1-500e-8485-f9f79ec81d76', 'neet', 2.5, 'targetpublications.org PYQ (1,333 questions) + medicneet.com PYQ (1,273 questions)'),
  -- cls11 Biological Classification
  ('8c9c091c-052a-51a1-841e-8304c7fe90ca', 'neet', 8.5, 'targetpublications.org PYQ (1,333 questions) + medicneet.com PYQ (1,273 questions)'),
  -- cls11 Plant Kingdom
  ('1380c5e5-1556-5626-97fa-8237c6cb021b', 'neet', 10.0, 'targetpublications.org PYQ (1,333 questions) + medicneet.com PYQ (1,273 questions)'),
  -- cls11 Animal Kingdom
  ('f6bee128-d309-5443-b6f2-e9914769623d', 'neet', 18.5, 'targetpublications.org PYQ (1,333 questions) + medicneet.com PYQ (1,273 questions)'),
  -- cls11 Morphology of Flowering Plants
  ('ca9c37dd-ac72-50d6-96bf-fb3da5aba16e', 'neet', 10.5, 'targetpublications.org PYQ (1,333 questions) + medicneet.com PYQ (1,273 questions)'),
  -- cls11 Anatomy of Flowering Plants
  ('e3200f90-b1db-5124-b97a-df6f8e7eee91', 'neet', 8.0, 'targetpublications.org PYQ (1,333 questions) + medicneet.com PYQ (1,273 questions)'),
  -- cls11 Structural Organisation in Animals
  ('5ec9dcb0-2679-5515-9422-5ca618283550', 'neet', 10.0, 'targetpublications.org PYQ (1,333 questions) + medicneet.com PYQ (1,273 questions)'),
  -- cls11 Cell: The Unit of Life
  ('b5931f9e-b7ab-55b9-af92-0e04ad407723', 'neet', 12.0, 'targetpublications.org PYQ (1,333 questions) + medicneet.com PYQ (1,273 questions)'),
  -- cls11 Biomolecules
  ('d3197785-4618-5806-8938-86b4e8a0cb52', 'neet', 11.0, 'targetpublications.org PYQ (1,333 questions) + medicneet.com PYQ (1,273 questions)'),
  -- cls11 Cell Cycle and Cell Division
  ('a61d22d0-2c11-5aa6-8d3e-bc077fcc31d0', 'neet', 11.5, 'targetpublications.org PYQ (1,333 questions) + medicneet.com PYQ (1,273 questions)'),
  -- cls11 Photosynthesis in Higher Plants
  ('4d7a31fc-ea68-5983-aab8-47845686daa7', 'neet', 8.0, 'targetpublications.org PYQ (1,333 questions) + medicneet.com PYQ (1,273 questions)'),
  -- cls11 Respiration in Plants
  ('690f3665-0100-518f-bc24-a957e7443bc9', 'neet', 5.0, 'targetpublications.org PYQ (1,333 questions) + medicneet.com PYQ (1,273 questions)'),
  -- cls11 Plant Growth and Development
  ('c62f8ffd-c8bd-5381-9384-1ef60fe91c5d', 'neet', 8.0, 'targetpublications.org PYQ (1,333 questions) + medicneet.com PYQ (1,273 questions)'),
  -- cls11 Breathing and Exchange of Gases
  ('14d01ba4-58de-5ce7-afe1-48af70c88711', 'neet', 9.5, 'targetpublications.org PYQ (1,333 questions) + medicneet.com PYQ (1,273 questions)'),
  -- cls11 Body Fluids and Circulation
  ('9bd0e62f-0407-5e84-8be4-71d2172879a4', 'neet', 12.5, 'targetpublications.org PYQ (1,333 questions) + medicneet.com PYQ (1,273 questions)'),
  -- cls11 Excretory Products and their Elimination
  ('0602318f-a82d-5187-a7fc-c6a3c5988d50', 'neet', 10.0, 'targetpublications.org PYQ (1,333 questions) + medicneet.com PYQ (1,273 questions)'),
  -- cls11 Locomotion and Movement
  ('993ee963-3968-54f6-9313-f019471a0332', 'neet', 10.5, 'targetpublications.org PYQ (1,333 questions) + medicneet.com PYQ (1,273 questions)'),
  -- cls11 Neural Control and Coordination
  ('d202ecdf-13b0-58db-8aff-2c511b68d009', 'neet', 7.0, 'targetpublications.org PYQ (1,333 questions) + medicneet.com PYQ (1,273 questions)'),
  -- cls11 Chemical Coordination and Integration
  ('31720c9d-1ae5-5661-b381-2262ee60b422', 'neet', 13.0, 'targetpublications.org PYQ (1,333 questions) + medicneet.com PYQ (1,273 questions)'),
  -- cls12 Sexual Reproduction in Flowering Plants
  ('7e5cbd62-185d-57d2-b127-b373b830ca64', 'neet', 13.5, 'targetpublications.org PYQ (1,333 questions) + medicneet.com PYQ (1,273 questions)'),
  -- cls12 Human Reproduction
  ('e2b58cc5-d8d6-5741-95ba-bbf41c478e10', 'neet', 16.0, 'targetpublications.org PYQ (1,333 questions) + medicneet.com PYQ (1,273 questions)'),
  -- cls12 Reproductive Health
  ('0a60009a-c9ac-52d9-9fc9-88e363e1252e', 'neet', 14.0, 'targetpublications.org PYQ (1,333 questions) + medicneet.com PYQ (1,273 questions)'),
  -- cls12 Principles of Inheritance and Variation
  ('92bfedfe-30d7-5a7a-8566-d8b7b0c3ac20', 'neet', 17.5, 'targetpublications.org PYQ (1,333 questions) + medicneet.com PYQ (1,273 questions)'),
  -- cls12 Molecular Basis of Inheritance
  ('982f12a9-ff64-56f6-8d68-644ea515e1b6', 'neet', 21.5, 'targetpublications.org PYQ (1,333 questions) + medicneet.com PYQ (1,273 questions)'),
  -- cls12 Evolution
  ('2361816c-f597-5cd6-bff3-596fa5a6a367', 'neet', 13.5, 'targetpublications.org PYQ (1,333 questions) + medicneet.com PYQ (1,273 questions)'),
  -- cls12 Human Health and Disease
  ('e85626cd-3ee3-5e09-8432-f3e57d3b7c41', 'neet', 14.5, 'targetpublications.org PYQ (1,333 questions) + medicneet.com PYQ (1,273 questions)'),
  -- cls12 Microbes in Human Welfare
  ('5556a4d4-7a7b-5223-adeb-a3f4e36deb40', 'neet', 8.0, 'targetpublications.org PYQ (1,333 questions) + medicneet.com PYQ (1,273 questions)'),
  -- cls12 Biotechnology: Principles and Processes
  ('3095e1d4-76f0-5a0a-b5db-8c3331d48a49', 'neet', 18.5, 'targetpublications.org PYQ (1,333 questions) + medicneet.com PYQ (1,273 questions)'),
  -- cls12 Biotechnology and its Applications
  ('9c5510da-004e-5dae-8172-4e57d36233d2', 'neet', 11.5, 'targetpublications.org PYQ (1,333 questions) + medicneet.com PYQ (1,273 questions)'),
  -- cls12 Organisms and Populations
  ('1c4ee0fe-830f-5338-ad2b-50f829127956', 'neet', 9.5, 'targetpublications.org PYQ (1,333 questions) + medicneet.com PYQ (1,273 questions)'),
  -- cls12 Ecosystem
  ('41be551b-11eb-5053-8d5d-fb46b7fbfaa1', 'neet', 6.5, 'targetpublications.org PYQ (1,333 questions) + medicneet.com PYQ (1,273 questions)'),
  -- cls12 Biodiversity and Conservation
  ('389e2cf0-d20d-5555-a09b-b78c24f40968', 'neet', 9.5, 'targetpublications.org PYQ (1,333 questions) + medicneet.com PYQ (1,273 questions)');

-- ── NEET CHEMISTRY · 19 chapters · sums to 180.0 ──────────────────
-- NEET chemistry. SUM = 180.0 exact (45 questions x 4 marks).
-- Built from per-year question counts off the ACTUAL 2024, 2025 and 2026
-- papers plus a 5-year count, not from a syllabus list. 11.6 marks belonging
-- to absent chapters (p-Block ~2.5 Q/yr, Qualitative Analysis ~0.75 Q/yr) were
-- split: half spread proportionally to keep the score calibrated to total exam
-- effort, half directed to the chapters that actually teach the orphaned
-- content so study time still points somewhere useful.
INSERT INTO chapter_exam_weights (chapter_id, exam, avg_marks, source_url)
VALUES
  -- cls11 Some Basic Concepts
  ('fa37da68-46a0-562f-9c75-2967215b8893', 'neet', 8.7, 'vedantu.com NEET 2024/2025/2026 papers + pw.live 5-year counts'),
  -- cls11 Atomic Structure
  ('16bf043d-bc59-5ebb-93ad-7b0fddf484c9', 'neet', 8.1, 'vedantu.com NEET 2024/2025/2026 papers + pw.live 5-year counts'),
  -- cls11 Classification of Elements
  ('aac04619-0e94-5a09-99bb-abdc2b688290', 'neet', 8.6, 'vedantu.com NEET 2024/2025/2026 papers + pw.live 5-year counts'),
  -- cls11 Chemical Bonding
  ('862ab5f0-4fa8-5e6f-98d5-74fe5b10ab8e', 'neet', 12.3, 'vedantu.com NEET 2024/2025/2026 papers + pw.live 5-year counts'),
  -- cls11 Thermodynamics
  ('a6961d73-9ca9-5716-8e0c-61c69c5e343f', 'neet', 9.9, 'vedantu.com NEET 2024/2025/2026 papers + pw.live 5-year counts'),
  -- cls11 Equilibrium
  ('f111ba16-c07d-5237-b2dd-eab22645f161', 'neet', 10.8, 'vedantu.com NEET 2024/2025/2026 papers + pw.live 5-year counts'),
  -- cls11 Redox Reactions
  ('c6da3467-e267-576e-9999-a2687ffe9200', 'neet', 3.5, 'vedantu.com NEET 2024/2025/2026 papers + pw.live 5-year counts'),
  -- cls11 General Organic Chemistry
  ('15bf6c7a-ff09-5741-93b8-e48e8a915273', 'neet', 15.3, 'vedantu.com NEET 2024/2025/2026 papers + pw.live 5-year counts'),
  -- cls11 Hydrocarbons
  ('388fccf5-9390-50aa-b678-5800a9e4fffa', 'neet', 10.8, 'vedantu.com NEET 2024/2025/2026 papers + pw.live 5-year counts'),
  -- cls12 Solutions
  ('f95d6af7-2754-5516-8d74-c4455dfc6ea2', 'neet', 9.5, 'vedantu.com NEET 2024/2025/2026 papers + pw.live 5-year counts'),
  -- cls12 Electrochemistry
  ('cf08cf74-67bb-5439-8375-68b0422c88af', 'neet', 6.6, 'vedantu.com NEET 2024/2025/2026 papers + pw.live 5-year counts'),
  -- cls12 Chemical Kinetics
  ('0f327c85-1a68-50d9-a9bd-44fd17ed88b7', 'neet', 10.8, 'vedantu.com NEET 2024/2025/2026 papers + pw.live 5-year counts'),
  -- cls12 d-and-f-Block Elements
  ('03b28b70-7318-558a-a728-f505fc592e5a', 'neet', 9.6, 'vedantu.com NEET 2024/2025/2026 papers + pw.live 5-year counts'),
  -- cls12 Coordination Compounds
  ('b31d7996-66b8-5dc7-8e3b-95ddc4516a92', 'neet', 15.9, 'vedantu.com NEET 2024/2025/2026 papers + pw.live 5-year counts'),
  -- cls12 Haloalkanes & Haloarenes
  ('54af5da8-ed02-5dff-90b6-a6c2a9f5928d', 'neet', 7.0, 'vedantu.com NEET 2024/2025/2026 papers + pw.live 5-year counts'),
  -- cls12 Alcohols, Phenols & Ethers
  ('7f0847a6-736a-5b04-8626-3978781672eb', 'neet', 6.2, 'vedantu.com NEET 2024/2025/2026 papers + pw.live 5-year counts'),
  -- cls12 Aldehydes, Ketones & Carboxylic Acids
  ('62483989-6f22-51ab-8ca1-f687ec124a9d', 'neet', 10.3, 'vedantu.com NEET 2024/2025/2026 papers + pw.live 5-year counts'),
  -- cls12 Amines
  ('64cfe65f-4cd9-52be-b436-f18793383afd', 'neet', 9.9, 'vedantu.com NEET 2024/2025/2026 papers + pw.live 5-year counts'),
  -- cls12 Biomolecules
  ('700ce9b5-8bfc-5c4b-bdb9-5a74738c2af4', 'neet', 6.2, 'vedantu.com NEET 2024/2025/2026 papers + pw.live 5-year counts');

-- ── NEET PHYSICS · 28 chapters · sums to 180.0 ──────────────────
-- NEET physics. SUM = 180.0 (45 questions x 4 marks).
-- Backbone: two multi-year aggregates (560 and 749 real questions), each
-- renormalised to its own true total -- one source's published percentage
-- column divides by 600 while its counts sum to 749, so its percentages sum to
-- ~125% and only its raw counts were usable. NEET 2025 held to 15% weight
-- because one paper at 4 marks/question is coarse.
-- Class 11 82.5 / Class 12 97.5 matches the observed 46:54 split.
INSERT INTO chapter_exam_weights (chapter_id, exam, avg_marks, source_url)
VALUES
  -- cls11 Units & Measurements
  ('8d7ccfaa-af16-53e4-9f28-823c8ea923d1', 'neet', 7.0, 'iquanta.in 2014-2025 aggregate (560 questions) + targetpublications.org (749 questions)'),
  -- cls11 Motion in a Straight Line
  ('563ae2b1-3427-537a-afde-f7fbc193731f', 'neet', 5.0, 'iquanta.in 2014-2025 aggregate (560 questions) + targetpublications.org (749 questions)'),
  -- cls11 Motion in a Plane
  ('a5970ed6-3b48-55f9-9b80-8abdd3d4c336', 'neet', 7.0, 'iquanta.in 2014-2025 aggregate (560 questions) + targetpublications.org (749 questions)'),
  -- cls11 Laws of Motion
  ('50ae6550-951b-599c-b352-1d6e5f84bc3b', 'neet', 7.5, 'iquanta.in 2014-2025 aggregate (560 questions) + targetpublications.org (749 questions)'),
  -- cls11 Work, Energy & Power
  ('a88de5d2-84e4-5489-878a-f17a195e3267', 'neet', 6.5, 'iquanta.in 2014-2025 aggregate (560 questions) + targetpublications.org (749 questions)'),
  -- cls11 Rotational Motion
  ('262da95c-2f3a-56da-905e-003fa8f0e4dc', 'neet', 9.5, 'iquanta.in 2014-2025 aggregate (560 questions) + targetpublications.org (749 questions)'),
  -- cls11 Gravitation
  ('29b5be47-3b75-550d-9636-ad45a901d4dd', 'neet', 8.0, 'iquanta.in 2014-2025 aggregate (560 questions) + targetpublications.org (749 questions)'),
  -- cls11 Mechanical Properties of Solids
  ('39bfe6d1-bd93-5157-a29c-b8ee68c3676b', 'neet', 2.5, 'iquanta.in 2014-2025 aggregate (560 questions) + targetpublications.org (749 questions)'),
  -- cls11 Mechanical Properties of Fluids
  ('33795397-f8fe-5ef6-ba2d-64549905ecd3', 'neet', 5.0, 'iquanta.in 2014-2025 aggregate (560 questions) + targetpublications.org (749 questions)'),
  -- cls11 Thermal Properties of Matter
  ('087ea53b-681c-51a2-92ef-5ea77f6bdf8b', 'neet', 4.0, 'iquanta.in 2014-2025 aggregate (560 questions) + targetpublications.org (749 questions)'),
  -- cls11 Thermodynamics
  ('58c19132-676f-5dfb-b84e-e3a34b34a48e', 'neet', 5.5, 'iquanta.in 2014-2025 aggregate (560 questions) + targetpublications.org (749 questions)'),
  -- cls11 Kinetic Theory
  ('8300dbf9-d9f7-505b-82c6-ad8d236eaff1', 'neet', 5.0, 'iquanta.in 2014-2025 aggregate (560 questions) + targetpublications.org (749 questions)'),
  -- cls11 Oscillations
  ('c1bc937e-5ff5-5ecb-a67b-89053c386c23', 'neet', 6.0, 'iquanta.in 2014-2025 aggregate (560 questions) + targetpublications.org (749 questions)'),
  -- cls11 Waves
  ('7dca7b5a-e77c-530d-bbe8-01a3518dc5d0', 'neet', 5.0, 'iquanta.in 2014-2025 aggregate (560 questions) + targetpublications.org (749 questions)'),
  -- cls12 Electric Charges and Fields
  ('cf605dc6-faed-5c33-8107-81114cbfef79', 'neet', 5.5, 'iquanta.in 2014-2025 aggregate (560 questions) + targetpublications.org (749 questions)'),
  -- cls12 Electrostatic Potential and Capacitance
  ('32366295-8398-526f-a430-cefdeea6d001', 'neet', 7.5, 'iquanta.in 2014-2025 aggregate (560 questions) + targetpublications.org (749 questions)'),
  -- cls12 Current Electricity
  ('5bd38ee4-dc52-5144-89a3-a51bbb35af15', 'neet', 11.5, 'iquanta.in 2014-2025 aggregate (560 questions) + targetpublications.org (749 questions)'),
  -- cls12 Moving Charges and Magnetism
  ('86b64ce4-24f5-5296-9cb2-f67b0989eca7', 'neet', 9.0, 'iquanta.in 2014-2025 aggregate (560 questions) + targetpublications.org (749 questions)'),
  -- cls12 Magnetism and Matter
  ('cf5d01e5-1a4b-538b-9e72-4d7074b2f61d', 'neet', 2.5, 'iquanta.in 2014-2025 aggregate (560 questions) + targetpublications.org (749 questions)'),
  -- cls12 Electromagnetic Induction
  ('b8223a22-15d4-5760-886f-53750c7dc9e8', 'neet', 5.5, 'iquanta.in 2014-2025 aggregate (560 questions) + targetpublications.org (749 questions)'),
  -- cls12 Alternating Current
  ('69dbf2ca-bc1d-514e-a033-de1eefec09c9', 'neet', 5.5, 'iquanta.in 2014-2025 aggregate (560 questions) + targetpublications.org (749 questions)'),
  -- cls12 Electromagnetic Waves
  ('e8e431d9-8966-55cc-b8f7-1ecc9427839f', 'neet', 6.0, 'iquanta.in 2014-2025 aggregate (560 questions) + targetpublications.org (749 questions)'),
  -- cls12 Ray Optics and Optical Instruments
  ('5c6a37c7-67be-5575-a3cc-456df9937cfa', 'neet', 9.5, 'iquanta.in 2014-2025 aggregate (560 questions) + targetpublications.org (749 questions)'),
  -- cls12 Wave Optics
  ('87df3af3-42ba-5439-ab4b-217b054ea81c', 'neet', 7.0, 'iquanta.in 2014-2025 aggregate (560 questions) + targetpublications.org (749 questions)'),
  -- cls12 Dual Nature of Radiation and Matter
  ('b992c39b-0355-5fc6-bfb2-0ba5cc82411b', 'neet', 7.5, 'iquanta.in 2014-2025 aggregate (560 questions) + targetpublications.org (749 questions)'),
  -- cls12 Atoms
  ('0365e7bf-d5d9-5b52-afd0-cd2ae522284c', 'neet', 4.5, 'iquanta.in 2014-2025 aggregate (560 questions) + targetpublications.org (749 questions)'),
  -- cls12 Nuclei
  ('bea23d56-36e5-5c51-a69e-34e6cd374f9a', 'neet', 4.5, 'iquanta.in 2014-2025 aggregate (560 questions) + targetpublications.org (749 questions)'),
  -- cls12 Semiconductor Electronics
  ('6e22ac90-425b-5336-9d44-81cc39afb062', 'neet', 10.5, 'iquanta.in 2014-2025 aggregate (560 questions) + targetpublications.org (749 questions)');

COMMIT;

-- Expect 154 rows.
-- Verify each subject sums to its paper total:
--
--   SELECT ch.subject, w.exam, round(sum(w.avg_marks), 1) AS total, count(*)
--     FROM chapter_exam_weights w
--     JOIN chapters ch ON ch.id = w.chapter_id
--    GROUP BY ch.subject, w.exam
--    ORDER BY w.exam, ch.subject;
--
-- jee  chemistry 100.0 (19) · jee  mathematics 100.0 (28) · jee  physics 100.0 (28)
-- neet biology   360.0 (32) · neet chemistry   180.0 (19) · neet physics 180.0 (28)

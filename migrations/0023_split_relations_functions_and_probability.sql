-- Split the Class 11 / Class 12 Relations-and-Functions and Probability
-- chapters along the actual NCERT boundary.
--
-- Both pairs had been authored as near-complete duplicates of each other:
-- 9 of the 12 Class 11 Relations & Functions concepts also existed in the
-- Class 12 chapter, and 5 of the 9 Class 11 Probability concepts also existed
-- in Class 12. Each chapter carried the other's content in both directions —
-- Class 11 taught composition and inverse functions two years early, Class 12
-- re-taught domain and range from scratch.
--
-- The boundary, per NCERT:
--
--   Class 11 Ch 2 — cartesian products, relations, domain and range of real
--     functions, standard functions and their graphs, algebra of real
--     functions. The JEE extras first taught alongside that material (even and
--     odd, periodicity, functional equations, counting maps) stay here too.
--   Class 12 Ch 1 — types of relations, equivalence relations and classes,
--     one-one / onto / bijective, composition, inverse.
--
--   Class 11 Ch 16 — random experiments, sample space, events, axiomatic
--     probability, addition theorem, combinatorial probability, odds.
--   Class 12 Ch 13 — conditional probability, independence and the
--     multiplication theorem, total probability, Bayes, random variables,
--     distributions, mean and variance, Bernoulli and binomial.
--
-- Every row retired below is COVERED by a surviving concept in the chapter it
-- belongs to — checked pair by pair, including where one chapter bundles what
-- the other splits ("Composition and Inverse of Functions" is covered by the
-- Class 12 pair "Composition of Functions" + "Inverse of a Function"). No
-- content is lost, which is why this deactivates rather than moves: the
-- correctly-placed copy already exists and already has the better breakdown.
--
-- None of the 16 carries a concept_mastery row or a tagged question, so
-- nothing is orphaned. Reversing any line is an UPDATE.
--
-- Expect Class 12 Relations and Functions to drop from 13 concepts to 5. That
-- looks severe and is correct: NCERT Class 12 Ch 1 genuinely is that short,
-- and the eight retired here are all Class 11 material the chapter should
-- never have re-taught.

-- ── Relations & Functions, Class 11: retire the Class 12 content ────────────
UPDATE concepts SET active = false WHERE id IN (
    '6de03da5-ae84-4528-97ed-9384f247b17c',  -- Types of Relations: Reflexive, Symmetric and Transitive
    '2d59611e-657b-4125-a7e3-452c82f46f54',  -- Types of Functions: One-One, Onto and Bijective
    'c79d2dcf-fcc4-41ca-b2c3-02391d637ffe'   -- Composition and Inverse of Functions
);

-- ── Relations and Functions, Class 12: retire the Class 11 content ─────────
UPDATE concepts SET active = false WHERE id IN (
    'b37c85bb-5b04-484d-a462-4f500cf1e152',  -- Cartesian Product and Representation of Relations
    '428f94cb-0f6a-4eca-8895-c51da39ab0dd',  -- Domain and Range of Real Functions
    '853ad7ca-fb5d-4ea3-8f99-8fdd57970695',  -- Standard Real Functions and Their Graphs
    'a1be56a4-4a60-44a9-a65d-65a6470ada53',  -- Algebra of Functions
    '86fd86cc-18fb-405c-8b61-834aef78f8a3',  -- Even and Odd Functions
    '6402717b-eccb-4b68-a820-e6fb2048b4f6',  -- Periodic Functions
    '353980f3-1019-4107-9a21-6e19f0c99b57',  -- Counting Relations and Functions Between Finite Sets
    '4592523f-30f0-4d31-b3c0-b481b62d56f7'   -- Functional Equations
);

-- ── Probability, Class 11: retire the Class 12 content ─────────────────────
UPDATE concepts SET active = false WHERE id IN (
    '955ccb76-f798-4e35-b375-a256b1da77e3',  -- Conditional Probability, Independence and Bayes' Theorem
    'f971f47b-dff4-4f1e-8a8d-9b2596526467'   -- Random Variables, Probability Distributions and Expectation
);

-- ── Probability, Class 12: retire the Class 11 content ─────────────────────
UPDATE concepts SET active = false WHERE id IN (
    'dc3b5b67-d5c6-44e0-95ac-6d42c9ced779',  -- Sample Space, Events and the Axiomatic Approach
    '8e7acc28-e5c5-46ae-a9a9-4c73698a70fd',  -- Addition Theorem and Probability of Unions
    '2a9c8860-817a-4638-84b0-9f1e1ebaa914'   -- Probability Using Permutations and Combinations
);

-- Expect 16 rows updated in total: 3 + 8 + 2 + 3.
-- Verify (should read 9, 5, 7, 9):
--
--   SELECT ch.name, ch.class_level, count(*) FILTER (WHERE c.active) AS live
--     FROM concepts c
--     JOIN chapters ch ON ch.id = c.chapter_id
--    WHERE ch.name IN ('Relations & Functions', 'Relations and Functions', 'Probability')
--      AND ch.subject = 'mathematics'
--    GROUP BY ch.name, ch.class_level
--    ORDER BY ch.name, ch.class_level;

-- Repoint question -> concept links that still name a retired concept.
--
-- Migrations 0022 and 0023 deactivated 18 misfiled concepts. Both migrations
-- claim no tagged questions were affected. That claim was checked against the
-- WRONG COLUMN: `questions.concept` is a free-text display label ("General",
-- "VSEPR & Lone Pairs") that matches no concept key at all, so it reported
-- zero for everything. The real linkage is the question_concepts join table,
-- and 48 of its rows point at concepts that are now inactive.
--
-- The consequence is silent, which is why it needs fixing rather than
-- watching: progress_scoring.apply_answer_scoring resolves a question's
-- concepts through this table and upserts concept_mastery against whatever it
-- finds. Answering one of those 48 questions still WRITES mastery — to a
-- concept /progress now filters out of both the listing and the denominator.
-- The student earns a score they can never see.
--
-- Every retired concept has a live equivalent in the chapter it belongs to;
-- that was verified pair by pair when 0022 and 0023 were written, and each
-- target below resolves to exactly one active concept. No remapped link
-- collides with a link the question already has, so no row is lost to a
-- unique constraint.

UPDATE question_concepts SET concept_id = '70614864-df5e-44c8-999a-6b5682e310a8'
  WHERE concept_id = 'efc63ba7-66a1-42c1-a587-2c6ccf608e0d';  --  4 link(s): Electromagnetic Spectrum and Properties -> Electromagnetic Spectrum and Application
UPDATE question_concepts SET concept_id = '4a626c32-0b20-4567-aecf-00fca3fcfcd7'
  WHERE concept_id = 'a2a666a3-e211-47e4-8c94-033585e07482';  --  1 link(s): Maxwell's Equations and Displacement Cur -> Displacement Current and Maxwell's Equat
UPDATE question_concepts SET concept_id = 'd6023263-5509-47ac-b58d-5521d5b94e24'
  WHERE concept_id = '428f94cb-0f6a-4eca-8895-c51da39ab0dd';  -- 19 link(s): Domain and Range of Real Functions -> Domain and Range of Real Functions
UPDATE question_concepts SET concept_id = '929795de-e436-43d7-bfaf-47bd35fa9290'
  WHERE concept_id = 'b37c85bb-5b04-484d-a462-4f500cf1e152';  --  4 link(s): Cartesian Product and Representation of  -> Cartesian Product of Sets and Ordered Pa
UPDATE question_concepts SET concept_id = '6283d797-6c6b-4684-b163-deb2993cb142'
  WHERE concept_id = '853ad7ca-fb5d-4ea3-8f99-8fdd57970695';  --  3 link(s): Standard Real Functions and Their Graphs -> Standard Real Functions and Their Graphs
UPDATE question_concepts SET concept_id = '56969b7d-4930-40b2-8153-579ccab5504b'
  WHERE concept_id = '4592523f-30f0-4d31-b3c0-b481b62d56f7';  --  3 link(s): Functional Equations -> Functional Equations
UPDATE question_concepts SET concept_id = '014d6a5f-e81e-4278-a4bb-a3a517f6a592'
  WHERE concept_id = '353980f3-1019-4107-9a21-6e19f0c99b57';  --  1 link(s): Counting Relations and Functions Between -> Number of Relations and Functions Betwee
UPDATE question_concepts SET concept_id = '133843b6-341e-41bf-9a94-a536a6dc3d24'
  WHERE concept_id = '6402717b-eccb-4b68-a820-e6fb2048b4f6';  --  1 link(s): Periodic Functions -> Periodic Functions and Their Periods
UPDATE question_concepts SET concept_id = '33c5fd16-b012-4d43-a014-39f617a38f1f'
  WHERE concept_id = 'a1be56a4-4a60-44a9-a65d-65a6470ada53';  --  0 link(s): Algebra of Functions -> Algebra of Real Functions
UPDATE question_concepts SET concept_id = '123d1d9c-00f3-408c-9792-9c02eba0637c'
  WHERE concept_id = '86fd86cc-18fb-405c-8b61-834aef78f8a3';  --  0 link(s): Even and Odd Functions -> Even and Odd Functions
UPDATE question_concepts SET concept_id = 'a3469cc0-3bcc-44d1-bfa3-0bfcc93aaa2e'
  WHERE concept_id = '6de03da5-ae84-4528-97ed-9384f247b17c';  --  0 link(s): Types of Relations: Reflexive, Symmetric -> Types of Relations: Reflexive, Symmetric
UPDATE question_concepts SET concept_id = '13b89ca8-2dde-4097-b213-d7172ef6ba32'
  WHERE concept_id = '2d59611e-657b-4125-a7e3-452c82f46f54';  --  0 link(s): Types of Functions: One-One, Onto and Bi -> One-One, Onto and Bijective Functions
UPDATE question_concepts SET concept_id = '9fa37b41-bbf4-45c4-8f22-9a5089fbc0d1'
  WHERE concept_id = 'c79d2dcf-fcc4-41ca-b2c3-02391d637ffe';  --  0 link(s): Composition and Inverse of Functions -> Composition of Functions
UPDATE question_concepts SET concept_id = 'e71f2da8-3a60-4a93-a7e3-cf9b81ae9e24'
  WHERE concept_id = '955ccb76-f798-4e35-b375-a256b1da77e3';  --  7 link(s): Conditional Probability, Independence an -> Conditional Probability
UPDATE question_concepts SET concept_id = '44db0521-fafd-44a6-875a-5594660a9276'
  WHERE concept_id = 'f971f47b-dff4-4f1e-8a8d-9b2596526467';  --  5 link(s): Random Variables, Probability Distributi -> Random Variables and Probability Distrib
UPDATE question_concepts SET concept_id = 'e984d6e8-60b7-4ded-94bc-8ec90cb882c0'
  WHERE concept_id = 'dc3b5b67-d5c6-44e0-95ac-6d42c9ced779';  --  0 link(s): Sample Space, Events and the Axiomatic A -> Random Experiments, Sample Space and Eve
UPDATE question_concepts SET concept_id = 'd53319c7-6b63-4318-b8c1-119af589616a'
  WHERE concept_id = '8e7acc28-e5c5-46ae-a9a9-4c73698a70fd';  --  0 link(s): Addition Theorem and Probability of Unio -> Addition Theorem for the Union of Events
UPDATE question_concepts SET concept_id = 'dbe1d6ee-969c-4007-92a6-601b76563a64'
  WHERE concept_id = '2a9c8860-817a-4638-84b0-9f1e1ebaa914';  --  0 link(s): Probability Using Permutations and Combi -> Combinatorial Probability with Dice, Coi

-- Expect 48 rows updated in total.
-- Verify (should return 0):
--
--   SELECT count(*) FROM question_concepts qc
--     JOIN concepts c ON c.id = qc.concept_id
--    WHERE c.active = false;

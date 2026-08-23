-- Retire two Class 12 concepts misfiled into the Class 11 Waves chapter.
--
-- NCERT Class 11 Physics Ch 15 "Waves" is mechanical waves only: transverse
-- and longitudinal waves, the displacement relation, superposition,
-- reflection, standing waves, beats, Doppler. It contains no electromagnetism.
--
-- But the chapter carried these two at teach_order 9 and 10:
--
--     9.  Maxwell's Equations and Displacement Current
--     10. Electromagnetic Spectrum and Properties
--
-- Both duplicate concepts that already exist, correctly, in the Class 12
-- "Electromagnetic Waves" chapter (its teach_order 1 and 5). Because they sat
-- at the END of the sequence, a student who worked the Class 11 Waves chapter
-- through to completion would be taught Maxwell's equations as the closing
-- lesson on a mechanical-waves chapter — two years of prerequisites early.
--
-- Deactivated rather than deleted. The catalogue and the planner both already
-- skip `active = false`, so this removes them from teaching immediately, while
-- one existing concept_mastery row (a single attempt, mastery 0.0) keeps its
-- foreign key instead of being orphaned. Reversing this is an UPDATE, not a
-- restore from backup.

UPDATE concepts
SET active = false
WHERE id IN (
    'a2a666a3-e211-47e4-8c94-033585e07482',  -- Maxwell's Equations and Displacement Current
    'efc63ba7-66a1-42c1-a587-2c6ccf608e0d'   -- Electromagnetic Spectrum and Properties
);

-- Expect 2 rows updated, and the Class 11 Waves chapter left teaching 8.
-- Verify:
--
--   SELECT c.teach_order, c.name, c.active
--     FROM concepts c
--     JOIN chapters ch ON ch.id = c.chapter_id
--    WHERE ch.name = 'Waves' AND ch.class_level = 11
--    ORDER BY c.teach_order;

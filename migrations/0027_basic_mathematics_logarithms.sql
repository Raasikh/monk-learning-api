-- A home for logarithms.
--
-- "Logarithms and their properties" is a named JEE Advanced Algebra topic and
-- appeared nowhere in the 144 Class 11 mathematics concepts — while TWO
-- existing concepts already presuppose it: "Exponential and Logarithmic
-- Inequalities" in Linear Inequalities, and "Standard Trigonometric,
-- Exponential and Logarithmic Limits" in Limits and Derivatives. A student
-- following the teaching order met logarithmic inequalities before ever being
-- taught what a logarithm is.
--
-- The awkwardness is placement, not need: logarithms have no NCERT chapter of
-- their own. The audit suggested filing them under Linear Inequalities as the
-- nearest existing host, which would put "Logarithms" behind a picker entry
-- named "Linear Inequalities" — findable only by accident. Coaching syllabi
-- solve this with a foundations chapter, so this creates one.
--
-- It holds ONE concept, deliberately. Surds, ratio and proportion, polynomial
-- division and the binomial approximation are all absent from the taxonomy
-- too, and all four were considered — but the syllabus audit flagged none of
-- them as required, and inventing content to make a chapter look substantial
-- is the same padding this taxonomy has spent four migrations removing. The
-- chapter exists so the next genuine foundations gap has somewhere to go.
--
-- chapter_order 0 puts it ahead of Sets, which is the whole point: it is a
-- prerequisite for chapters that already reference it. Mathematics is JEE-only
-- (NEET has no mathematics), so the concept is tagged jee.

BEGIN;

-- status is set explicitly rather than left to the column default: all 106
-- existing chapters carry 'ready', and nothing in the API filters on it today,
-- but a new chapter that is the only row with a different value is exactly the
-- kind of thing a batch job or the web repo would silently skip.
INSERT INTO chapters (id, name, subject, class_level, chapter_order, status)
VALUES ('b0a51c00-0000-4000-8000-000000000001', 'Basic Mathematics', 'mathematics', 11, 0, 'ready');

INSERT INTO concepts (id, chapter_id, key, name, teach_order, display_order, exams, active)
VALUES ('10940000-0000-4000-8000-000000000001', 'b0a51c00-0000-4000-8000-000000000001', 'logarithms-definition-properties-and-change-of-base',
        'Logarithms: Definition, Properties and Change of Base',
        1, 1, ARRAY['jee'], true);

COMMIT;

-- Expect 1 chapter and 1 concept inserted.
-- Verify:
--   SELECT count(*) FROM chapters;                  -- 106 -> 107
--   SELECT count(*) FROM concepts WHERE active;     -- 1153 -> 1154
--   SELECT ch.name, c.name FROM concepts c JOIN chapters ch ON ch.id = c.chapter_id
--    WHERE ch.name = 'Basic Mathematics';

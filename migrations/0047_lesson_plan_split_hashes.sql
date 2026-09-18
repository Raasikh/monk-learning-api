-- The split plan hash (09662ab) writes two provenance columns the table
-- never got: plan_sha (what decides regeneration) and board_sha (what a
-- prompt tweak must not void). Shipped without this migration, every plan
-- regeneration failed with PGRST204, left the plan row uninserted, and the
-- session insert then broke its plan_id foreign key — surfacing to the
-- student as "Drona's having trouble reaching the lesson".
alter table lesson_plans add column if not exists plan_sha text;
alter table lesson_plans add column if not exists board_sha text;

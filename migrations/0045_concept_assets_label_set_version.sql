-- 0045 — carry the label set's identity on the asset row.
--
-- NUMBERED 0045, NOT 0042. The directive asked for 0042; that number was taken
-- by 0042_drona_turns_turn_failed.sql, and 0043/0044 are also applied. Reusing
-- it would give two different migrations the same name in a directory whose
-- ordering IS its contract.
--
-- WHY THIS EXISTS
-- ===============
-- A running app holds one resolved record per slug for its whole life. B0
-- invalidates that record when `master_sha256` moves, which is right for art
-- and useless for labels: publishing a label set rewrites
-- concept-assets/<slug>.json and does not touch the master. So on
-- 2026-09-12 the frog heart published, and every already-running client kept
-- drawing the plate with no labels until it was restarted. The board was
-- correct, the bytes were correct, and nothing told the client to look again.
--
-- `label_set_version` is the human-facing counter and `label_set_sha256` is
-- what actually decides staleness: a reviewer who corrects one anchor and
-- republishes at the same version still changes the bytes, and the client must
-- notice. Both are sent because the version is what a person reads in a report
-- and the hash is what the code compares.
--
-- DEFAULT 0, NOT NULL: every one of the 113 existing rows has no published
-- label set, and 0 says exactly that. NULL would mean "unknown", which is a
-- third state nothing needs and every reader would have to handle.
--
-- label_set_sha256 stays NULL-able because "no set published" genuinely has no
-- hash, and a sentinel string would be a value nobody computed.

ALTER TABLE concept_assets
  ADD COLUMN IF NOT EXISTS label_set_version integer NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS label_set_sha256  text;

COMMENT ON COLUMN concept_assets.label_set_version IS
  'Publish counter for concept-assets/<asset_slug>.json. 0 = never published.';
COMMENT ON COLUMN concept_assets.label_set_sha256 IS
  'sha256 of the published label-set JSON. NULL until first publish. The '
  'client compares THIS to decide a cached figure is stale.';

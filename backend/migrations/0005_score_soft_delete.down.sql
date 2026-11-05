-- Rolling back resurrects soft-deleted scores in their owners' libraries and counts them toward the cap.
DROP INDEX IF EXISTS scores_deleted_at_idx;
DROP INDEX IF EXISTS scores_user_live_idx;
ALTER TABLE scores DROP COLUMN IF EXISTS deleted_at;

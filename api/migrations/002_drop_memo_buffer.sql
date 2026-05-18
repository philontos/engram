-- 002_drop_memo_buffer.sql
-- Engram is a thoughts/reflections system, not a notes app.
-- The memo and capture_buffer tracks were originally added to handle
-- "fact-only logs" and "user is still typing" cases. Both are out of scope:
--   - memo: encourages users to log events that pollute the cognitive signal.
--   - capture_buffer: requires multi-message stitching that doesn't match how
--     reflections are typed in practice.
--
-- This migration drops both tables. Existing memo rows are NOT migrated to
-- entries (they were tagged as low-signal by the intent gate by design).
-- If you want to keep historical memo content, export `memos.raw` before
-- running this migration.
--
-- Run:  sqlite3 ./data/cognitive/cognitive.db < migrations/002_drop_memo_buffer.sql

BEGIN;

DROP INDEX IF EXISTS idx_memos_created;
DROP INDEX IF EXISTS idx_buffer_session;
DROP INDEX IF EXISTS idx_buffer_source_flushed;

DROP TABLE IF EXISTS memos;
DROP TABLE IF EXISTS capture_buffer;

COMMIT;

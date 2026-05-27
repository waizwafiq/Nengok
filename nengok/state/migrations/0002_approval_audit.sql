-- 0002_approval_audit.sql
-- Rename approval columns so the audit log uses the public field names
-- the dashboard and the JSON export contract refer to:
--   decided_by -> reviewer
--   decided_at -> created_at
--   notes      -> reason
-- Also add an index on created_at so the cross-cluster approval feed
-- and date-range exports scan in order without a table sort.

ALTER TABLE approvals RENAME COLUMN decided_by TO reviewer;
ALTER TABLE approvals RENAME COLUMN decided_at TO created_at;
ALTER TABLE approvals RENAME COLUMN notes TO reason;

CREATE INDEX IF NOT EXISTS approvals_created_idx ON approvals (created_at);

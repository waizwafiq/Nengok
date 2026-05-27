-- 0003_cycle_history.sql
-- Extend the cycles table so a reviewer can see what each cycle did,
-- not only how much it cost. The new columns let the overview
-- dashboard plot a status histogram next to the spend sparkline and
-- let `nengok export` surface cycle outcomes alongside clusters and
-- approvals.

ALTER TABLE cycles ADD COLUMN status TEXT NOT NULL DEFAULT 'ok';
ALTER TABLE cycles ADD COLUMN clusters_processed INTEGER NOT NULL DEFAULT 0;
ALTER TABLE cycles ADD COLUMN clusters_discovered INTEGER NOT NULL DEFAULT 0;
ALTER TABLE cycles ADD COLUMN error_message TEXT;

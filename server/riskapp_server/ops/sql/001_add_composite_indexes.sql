-- Composite indexes for the hottest query patterns.
-- Safe to run repeatedly.

-- items
CREATE INDEX IF NOT EXISTS ix_items_project_type_deleted_score
    ON items (project_id, type, is_deleted, score);

CREATE INDEX IF NOT EXISTS ix_items_project_type_updated
    ON items (project_id, type, updated_at);

-- actions
CREATE INDEX IF NOT EXISTS ix_actions_project_deleted_updated
    ON actions (project_id, is_deleted, updated_at);

CREATE INDEX IF NOT EXISTS ix_actions_project_item
    ON actions (project_id, item_id);

-- assessments
CREATE INDEX IF NOT EXISTS ix_assessments_item_updated
    ON assessments (item_id, updated_at);

CREATE INDEX IF NOT EXISTS ix_assessments_assessor_updated
    ON assessments (assessor_user_id, updated_at);

-- score_snapshots
CREATE INDEX IF NOT EXISTS ix_score_snapshots_project_kind_captured
    ON score_snapshots (project_id, kind, captured_at);

CREATE INDEX IF NOT EXISTS ix_score_snapshots_batch_score
    ON score_snapshots (batch_id, score);

-- audit_log
CREATE INDEX IF NOT EXISTS ix_audit_log_project_ts
    ON audit_log (project_id, ts);

-- sync_receipts
CREATE INDEX IF NOT EXISTS ix_sync_receipts_project_processed
    ON sync_receipts (project_id, processed_at);
-- Monthly token counter for the external Georgia SNAP API integration.
-- Apply this migration before enabling EXTERNAL_SNAP_API_KEY.

CREATE TABLE IF NOT EXISTS external_snap_api_usage (
    billing_month DATE PRIMARY KEY,
    total_tokens BIGINT NOT NULL DEFAULT 0
);

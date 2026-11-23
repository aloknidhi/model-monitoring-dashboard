-- Migration: Model monitoring tables
-- Run this against the PostgreSQL database before starting the monitoring backend.
-- Example: psql -U ai_user -d personal_ai_brain -f database/migrations/001_model_monitoring.sql

-- Enable pgcrypto for gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TABLE IF NOT EXISTS model_inference_events (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    timestamp       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    model           VARCHAR(128) NOT NULL,
    provider        VARCHAR(64)  NOT NULL,
    prompt_tokens   INTEGER      NOT NULL DEFAULT 0,
    completion_tokens INTEGER   NOT NULL DEFAULT 0,
    total_tokens    INTEGER      NOT NULL DEFAULT 0,
    latency_ms      INTEGER      NOT NULL,
    success         BOOLEAN      NOT NULL DEFAULT TRUE,
    error_message   TEXT,
    user_id         VARCHAR(128),
    session_id      VARCHAR(128),
    request_id      VARCHAR(128)
);

CREATE INDEX IF NOT EXISTS idx_inference_timestamp
    ON model_inference_events(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_inference_model
    ON model_inference_events(model);
CREATE INDEX IF NOT EXISTS idx_inference_success
    ON model_inference_events(success);
CREATE INDEX IF NOT EXISTS idx_inference_provider
    ON model_inference_events(provider);

COMMENT ON TABLE model_inference_events IS 'Records of model inference requests for the monitoring dashboard';

-- Verify
SELECT COUNT(*) AS event_rows FROM model_inference_events;

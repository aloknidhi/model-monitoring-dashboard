"""
Model Monitoring Backend — Personal AI Brain

Collects and serves model inference metrics for the monitoring dashboard.
Tracks: request count, latency, token usage, estimated cost, error rate, and model drift signals.

Endpoints:
  POST   /monitoring/record   — record a model inference event
  GET    /monitoring/metrics  — aggregated metrics for the dashboard
  GET    /monitoring/health   — service health check
"""

import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional, List

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import psycopg2
from psycopg2.extras import RealDictCursor

app = FastAPI(title="Model Monitoring", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://ai_user:secure_password@db:5432/personal_ai_brain",
)


def get_conn():
    return psycopg2.connect(DATABASE_URL)


def init_db() -> None:
    """Create monitoring tables if they don't exist."""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
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
                ON model_inference_events(timestamp);
            CREATE INDEX IF NOT EXISTS idx_inference_model
                ON model_inference_events(model);
            CREATE INDEX IF NOT EXISTS idx_inference_success
                ON model_inference_events(success);
            """
        )
        conn.commit()


# Initialize on import (safe for gunicorn/uvicorn workers)
try:
    init_db()
except Exception:  # pragma: no cover — DB may not be up at import time
    pass


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class InferenceEvent(BaseModel):
    model: str = Field(..., description="Model name, e.g. gemini-3.8-flash")
    provider: str = Field(..., description="Provider, e.g. gemini, nvidia")
    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)
    latency_ms: int = Field(..., ge=0, description="Request latency in milliseconds")
    success: bool = Field(default=True)
    error_message: Optional[str] = None
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    request_id: Optional[str] = None


class MetricsResponse(BaseModel):
    total_requests: int
    successful_requests: int
    failed_requests: int
    error_rate_percent: float
    avg_latency_ms: float
    p95_latency_ms: float
    total_tokens: int
    estimated_cost_usd: float
    requests_by_model: List[dict]
    requests_by_hour: List[dict]
    recent_errors: List[dict]


# ---------------------------------------------------------------------------
# Cost estimation (per 1K tokens, approximate 2026 pricing)
# ---------------------------------------------------------------------------

COST_PER_1K_TOKENS = {
    "gemini-3.8-flash": 0.000075,
    "gemini-2.5-pro": 0.00125,
    "gemini-2.5-flash": 0.00015,
    "nvidia/nemotron-3.5-super-vl-120b-a12b": 0.0002,
    "default": 0.0002,
}


def estimate_cost(model: str, total_tokens: int) -> float:
    rate = COST_PER_1K_TOKENS.get(model, COST_PER_1K_TOKENS["default"])
    return round((total_tokens / 1000.0) * rate, 6)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/monitoring/health")
async def health():
    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT 1")
        return {"status": "healthy", "service": "model-monitoring"}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"database unavailable: {exc}")


@app.post("/monitoring/record")
async def record_event(event: InferenceEvent):
    """Record a single model inference event."""
    event_id = str(uuid.uuid4())
    cost = estimate_cost(event.model, event.total_tokens)
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO model_inference_events
                (id, model, provider, prompt_tokens, completion_tokens,
                 total_tokens, latency_ms, success, error_message,
                 user_id, session_id, request_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                event_id,
                event.model,
                event.provider,
                event.prompt_tokens,
                event.completion_tokens,
                event.total_tokens,
                event.latency_ms,
                event.success,
                event.error_message,
                event.user_id,
                event.session_id,
                event.request_id,
            ),
        )
        conn.commit()
    return {"status": "recorded", "id": event_id, "estimated_cost_usd": cost}


@app.get("/monitoring/metrics", response_model=MetricsResponse)
async def get_metrics(hours: int = 24):
    """Return aggregated metrics for the dashboard."""
    since = datetime.now(timezone.utc) - timedelta(hours=hours)

    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        # Overall aggregates
        cur.execute(
            """
            SELECT
                COUNT(*) AS total_requests,
                COUNT(*) FILTER (WHERE success) AS successful_requests,
                COUNT(*) FILTER (WHERE NOT success) AS failed_requests,
                ROUND(100.0 * COUNT(*) FILTER (WHERE NOT success) / NULLIF(COUNT(*), 0), 2) AS error_rate_percent,
                ROUND(AVG(latency_ms)::numeric, 2) AS avg_latency_ms,
                ROUND(SUM(total_tokens)) AS total_tokens,
                ROUND(SUM(
                    CASE model
                        WHEN 'gemini-3.8-flash' THEN total_tokens * 0.000075 / 1000
                        WHEN 'gemini-2.5-pro'   THEN total_tokens * 0.00125  / 1000
                        WHEN 'gemini-2.5-flash' THEN total_tokens * 0.00015  / 1000
                        ELSE total_tokens * 0.0002 / 1000
                    END
                )::numeric, 6) AS estimated_cost_usd
            FROM model_inference_events
            WHERE timestamp >= %s
            """,
            (since,),
        )
        agg = cur.fetchone() or {}

        # p95 latency
        cur.execute(
            """
            SELECT latency_ms
            FROM model_inference_events
            WHERE timestamp >= %s
            ORDER BY latency_ms
            """,
            (since,),
        )
        latencies = [row["latency_ms"] for row in cur.fetchall()]
        p95 = 0
        if latencies:
            idx = max(0, int(len(latencies) * 0.95) - 1)
            p95 = latencies[idx]

        # Requests by model
        cur.execute(
            """
            SELECT model,
                   COUNT(*) AS count,
                   ROUND(AVG(latency_ms)::numeric, 2) AS avg_latency_ms,
                   ROUND(SUM(total_tokens)) AS total_tokens
            FROM model_inference_events
            WHERE timestamp >= %s
            GROUP BY model
            ORDER BY count DESC
            """,
            (since,),
        )
        by_model = [dict(r) for r in cur.fetchall()]

        # Requests by hour
        cur.execute(
            """
            SELECT DATE_TRUNC('hour', timestamp) AT TIME ZONE 'UTC' AS hour,
                   COUNT(*) AS count,
                   ROUND(AVG(latency_ms)::numeric, 2) AS avg_latency_ms
            FROM model_inference_events
            WHERE timestamp >= %s
            GROUP BY hour
            ORDER BY hour
            """,
            (since,),
        )
        by_hour = [{"hour": str(r["hour"]), "count": r["count"], "avg_latency_ms": r["avg_latency_ms"]} for r in cur.fetchall()]

        # Recent errors
        cur.execute(
            """
            SELECT timestamp, model, provider, error_message, latency_ms
            FROM model_inference_events
            WHERE NOT success AND timestamp >= %s
            ORDER BY timestamp DESC
            LIMIT 20
            """,
            (since,),
        )
        recent_errors = [dict(r) for r in cur.fetchall()]

    return {
        "total_requests": agg.get("total_requests") or 0,
        "successful_requests": agg.get("successful_requests") or 0,
        "failed_requests": agg.get("failed_requests") or 0,
        "error_rate_percent": agg.get("error_rate_percent") or 0.0,
        "avg_latency_ms": agg.get("avg_latency_ms") or 0.0,
        "p95_latency_ms": p95,
        "total_tokens": agg.get("total_tokens") or 0,
        "estimated_cost_usd": agg.get("estimated_cost_usd") or 0.0,
        "requests_by_model": by_model,
        "requests_by_hour": by_hour,
        "recent_errors": recent_errors,
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8001")))

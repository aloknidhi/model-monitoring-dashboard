# Model Monitoring Dashboard

A self-contained model inference monitoring dashboard for LLM-powered applications. Tracks request volume, latency, token usage, estimated cost, and error rate per model/provider.

## What it collects

- Total / successful / failed requests
- Error rate %
- Average and P95 latency
- Total tokens and estimated cost (USD)
- Requests by model (doughnut chart)
- Requests over time (line chart)
- Recent errors table

## Architecture

```
monitoring/
├── backend/           # FastAPI metrics service (port 8001)
│   ├── main.py        # /monitoring/record, /monitoring/metrics, /monitoring/health
│   ├── requirements.txt
│   └── Dockerfile
└── dashboard.html     # Single-file Chart.js dashboard
```

The backend writes inference events to PostgreSQL (`model_inference_events` table) and serves JSON metrics for the dashboard.

## Run locally

```bash
cd monitoring/backend
pip install -r requirements.txt
DATABASE_URL=postgresql://ai_user:secure_password@localhost:5432/personal_ai_brain \
  uvicorn main:app --host 0.0.0.0 --port 8001
```

Open `dashboard.html` in a browser (point it at `http://localhost:8001/monitoring/metrics`) or serve it with any static file server.

## Record an inference event

```bash
curl -X POST http://localhost:8001/monitoring/record \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gemini-3.8-flash",
    "provider": "gemini",
    "prompt_tokens": 120,
    "completion_tokens": 80,
    "total_tokens": 200,
    "latency_ms": 850,
    "success": true,
    "user_id": "user_123"
  }'
```

## Database migration

```sql
-- database/migrations/001_model_monitoring.sql
CREATE TABLE IF NOT EXISTS model_inference_events (...);
```

See `database/migrations/` for the full migration.

## License

MIT — personal project.

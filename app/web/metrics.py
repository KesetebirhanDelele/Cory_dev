# app/web/metrics.py
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from fastapi import APIRouter, Response

# -------------------------------------------------------
#  Prometheus metrics definitions
# -------------------------------------------------------

WEBHOOK_TOTAL = Counter(
    "cory_webhook_total",
    "Total incoming webhook requests",
    ["method", "path"]
)
WEBHOOK_2XX = Counter("cory_webhook_2xx_total", "Webhook 2xx responses")
WEBHOOK_4XX = Counter("cory_webhook_4xx_total", "Webhook 4xx responses")
IDEMPOTENT_HITS = Counter(
    "cory_webhook_idempotent_hits_total",
    "Number of idempotent (duplicate) webhook requests"
)
WEBHOOK_LATENCY = Histogram(
    "cory_webhook_latency_seconds",
    "Webhook processing latency (seconds)",
    buckets=(0.005, 0.01, 0.05, 0.1, 0.3, 0.5, 1.0, 3.0, 5.0)
)

# -------------------------------------------------------
#  FastAPI router for metrics endpoints
# -------------------------------------------------------

router = APIRouter()

@router.get("/metrics")
async def metrics_endpoint():
    """Prometheus scrape endpoint."""
    data = generate_latest()
    return Response(content=data, media_type=CONTENT_TYPE_LATEST)


@router.get("/readyz")
async def readiness_check():
    """
    Simple readiness endpoint that passes only if Temporal & DB reachable.
    For now, stub it to always return 200 OK — can be extended later.
    """
    # TODO: Add DB and Temporal connectivity check later
    return {"status": "ready"}

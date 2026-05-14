"""
Prometheus metrics for AutonomousSDR.

Exposed at GET /metrics — scrape with Prometheus or Grafana Agent.
Grafana Cloud free tier (10 GB logs, 10k metric series/month):
  https://grafana.com/products/cloud/

Counters / histograms defined here are imported by graph.py (nodes)
and main.py (HTTP layer). All increments are wrapped in try/except so
a metrics failure never breaks the pipeline.

# PRODUCTION: Add push gateway for short-lived worker processes:
#   from prometheus_client import push_to_gateway
#   push_to_gateway('pushgateway:9091', job='sdr_worker', registry=REGISTRY)
"""

from prometheus_client import Counter, Histogram, Gauge, CollectorRegistry, CONTENT_TYPE_LATEST, generate_latest

REGISTRY = CollectorRegistry(auto_describe=True)

# ── Pipeline counters ──────────────────────────────────────────────────────────

leads_processed = Counter(
    "sdr_leads_processed_total",
    "Total leads that completed the pipeline",
    ["verdict"],          # Hot | Warm | Cold | unknown
    registry=REGISTRY,
)

pipeline_errors = Counter(
    "sdr_pipeline_errors_total",
    "Non-fatal errors accumulated during pipeline execution",
    ["node"],
    registry=REGISTRY,
)

# ── Latency histograms ────────────────────────────────────────────────────────

node_duration = Histogram(
    "sdr_node_duration_seconds",
    "Time spent in each graph node",
    ["node"],
    buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0],
    registry=REGISTRY,
)

# ── LLM / enrichment call counters ───────────────────────────────────────────

llm_calls = Counter(
    "sdr_llm_calls_total",
    "LLM inference calls",
    ["provider", "agent"],   # provider: ollama|groq|claude  agent: analysis|outreach|research
    registry=REGISTRY,
)

llm_errors = Counter(
    "sdr_llm_errors_total",
    "LLM calls that raised an exception",
    ["provider", "agent"],
    registry=REGISTRY,
)

enrichment_calls = Counter(
    "sdr_enrichment_calls_total",
    "Enrichment API calls",
    ["provider"],   # synthetic|hunter|pdl
    registry=REGISTRY,
)

research_tool_calls = Counter(
    "sdr_research_tool_calls_total",
    "Tool calls made by the ReAct ResearchAgent",
    ["tool"],   # search_web|check_funding|verify_icp
    registry=REGISTRY,
)

# ── Queue / pipeline health ───────────────────────────────────────────────────

pipeline_queue_size = Gauge(
    "sdr_pipeline_queue_size",
    "Number of leads currently in the Redis processing queue",
    registry=REGISTRY,
)

leads_in_flight = Gauge(
    "sdr_leads_in_flight",
    "Leads currently being processed by the worker",
    registry=REGISTRY,
)


def metrics_response() -> tuple[bytes, str]:
    """Return (body, content_type) ready to send as an HTTP response."""
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST

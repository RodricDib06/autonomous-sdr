"""
Structured logging via structlog.

In development (APP_ENV != production):
  - Pretty-printed, coloured output for human reading

In production:
  - JSON lines — one event per line, machine-parseable by Grafana Loki,
    Datadog, CloudWatch, etc.

All stdlib logging (FastAPI, SQLAlchemy, uvicorn, redis) is routed through
structlog's stdlib bridge so every log line gets the same structure.

Usage anywhere in the codebase:
    import structlog
    log = structlog.get_logger(__name__)
    log.info("graph.node.complete", node="enrich", lead_id=lead_id, duration_ms=142)
"""

import logging
import sys
import structlog
from app.config import settings


def configure_logging() -> None:
    _is_prod = settings.APP_ENV == "production"

    shared_processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
    ]

    if _is_prod:
        # JSON — one line per event, Loki/Datadog/CloudWatch compatible
        renderer = structlog.processors.JSONRenderer()
    else:
        # Human-friendly coloured output for local dev
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=shared_processors + [
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processor=renderer,
        foreign_pre_chain=shared_processors,
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)

    # Silence noisy third-party loggers
    for name in ("uvicorn.access", "sqlalchemy.engine", "httpx"):
        logging.getLogger(name).setLevel(logging.WARNING)

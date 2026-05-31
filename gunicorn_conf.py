"""Gunicorn configuration.

Gunicorn is the production process manager; it runs N Uvicorn worker processes,
each running the asyncio event loop. This is the standard FastAPI production
setup (nginx -> gunicorn -> uvicorn workers -> FastAPI).

Worker count rule of thumb: (2 * CPU cores) + 1. Override via the WEB_CONCURRENCY
env var on bigger instances.
"""
import multiprocessing
import os

bind = "0.0.0.0:8000"
workers = int(os.getenv("WEB_CONCURRENCY", (multiprocessing.cpu_count() * 2) + 1))
worker_class = "uvicorn.workers.UvicornWorker"
timeout = 30
graceful_timeout = 30
keepalive = 5
accesslog = "-"   # log to stdout (captured by Docker / journald)
errorlog = "-"
loglevel = "info"

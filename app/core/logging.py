"""Structured (JSON) logging.

Every log line is one JSON object, e.g.
  {"ts": "2026-11-19T08:30:01.123+00:00", "level": "INFO", "logger": "ticketflow.access",
   "msg": "request", "request_id": "3f9c2a1b7d4e", "method": "POST", "path": "/holds",
   "status": 201, "duration_ms": 41.7}
so log platforms (Render, CloudWatch, Datadog, Loki) can filter and aggregate on
fields instead of grepping text. Anything passed via `extra=` becomes a field.
Set LOG_FORMAT=text for human-readable lines in local dev.
"""
from __future__ import annotations

import datetime as dt
import json
import logging

# Attributes every LogRecord has; anything else on a record came from `extra=`.
_STANDARD_ATTRS = set(vars(logging.LogRecord("", 0, "", 0, "", None, None))) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        out = {
            "ts": dt.datetime.fromtimestamp(record.created, tz=dt.timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key, value in vars(record).items():
            if key not in _STANDARD_ATTRS and not key.startswith("_"):
                out[key] = value
        if record.exc_info:
            out["exc"] = self.formatException(record.exc_info)
        return json.dumps(out, default=str)


def configure_logging(fmt: str = "json", level: int = logging.INFO) -> None:
    handler = logging.StreamHandler()
    if fmt == "text":
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    else:
        handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)

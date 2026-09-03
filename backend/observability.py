"""Structured JSON logging with a request-scoped trace_id (v2 roadmap Phase 1c).

Usage: call configure_logging() once at app startup instead of
logging.basicConfig(), and trace_id_var.set(new_trace_id()) at the top of a
request handler. Every log line emitted anywhere during that request —
including inside the agent pipeline — automatically carries the same
trace_id, without needing to touch any individual logger.info(...) call.
"""
import contextvars
import json
import logging
import uuid

trace_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("trace_id", default="-")


def new_trace_id() -> str:
    return uuid.uuid4().hex[:16]


class TraceIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.trace_id = trace_id_var.get()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "trace_id": getattr(record, "trace_id", "-"),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload)


def configure_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    handler.addFilter(TraceIdFilter())

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)

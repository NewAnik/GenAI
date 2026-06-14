"""structlog configuration with per-turn correlation (whatsapp_number / session_id / turn_id)."""
from __future__ import annotations

import logging
import sys
from contextvars import ContextVar

import structlog

_turn_context: ContextVar[dict] = ContextVar("_turn_context", default={})


def configure_logging(level: str = "INFO", json_output: bool | None = None) -> None:
    """Configure structlog + stdlib logging once, at process startup."""
    if json_output is None:
        json_output = level.upper() != "DEBUG"

    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level.upper())

    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        _inject_turn_context,
    ]
    renderer = structlog.processors.JSONRenderer() if json_output else structlog.dev.ConsoleRenderer()

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level.upper())),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def _inject_turn_context(logger, method_name, event_dict):
    event_dict.update(_turn_context.get())
    return event_dict


def bind_turn_context(*, whatsapp_number: str | None = None, session_id: int | None = None,
                       turn_id: str | None = None) -> None:
    """Bind correlation fields so every subsequent log line in this turn carries them."""
    ctx = dict(_turn_context.get())
    if whatsapp_number is not None:
        ctx["whatsapp_number"] = whatsapp_number
    if session_id is not None:
        ctx["session_id"] = session_id
    if turn_id is not None:
        ctx["turn_id"] = turn_id
    _turn_context.set(ctx)


def clear_turn_context() -> None:
    _turn_context.set({})


def get_logger(name: str | None = None):
    return structlog.get_logger(name)

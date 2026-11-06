"""Exception logging that never echoes user data."""

from __future__ import annotations

import logging
import time
import traceback

import psycopg
from flask import g

_MS_PER_S = 1000


def describe_exception(exc: BaseException) -> str:
    """Return type, constraint name and stack frames, never ``str(exc)``.

    Exception messages can echo user input (psycopg's ``Key (email)=(...)``).
    """
    constraint = exc.diag.constraint_name if isinstance(exc, psycopg.Error) else None
    frames = "".join(traceback.format_tb(exc.__traceback__))
    return f"{type(exc).__name__} (constraint={constraint})\n{frames}"


def log_event(logger: logging.Logger, event: str, **fields: int | str) -> None:
    """Log ``event k=v ... ms=<request duration>``.

    Callers pass only integer ids and fixed reason codes: never emails, passwords, tokens or reset codes.
    """
    started = g.get("request_started")
    ms = (time.perf_counter() - started) * _MS_PER_S if started is not None else 0.0
    parts = "".join(f" {k}={v}" for k, v in fields.items())
    logger.info("%s%s ms=%.0f", event, parts, ms)

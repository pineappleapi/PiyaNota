"""Exception logging that never echoes user data."""

from __future__ import annotations

import traceback

import psycopg


def describe_exception(exc: BaseException) -> str:
    """Return type, constraint name and stack frames, never ``str(exc)``.

    Exception messages can echo user input (psycopg's ``Key (email)=(...)``).
    """
    constraint = exc.diag.constraint_name if isinstance(exc, psycopg.Error) else None
    frames = "".join(traceback.format_tb(exc.__traceback__))
    return f"{type(exc).__name__} (constraint={constraint})\n{frames}"

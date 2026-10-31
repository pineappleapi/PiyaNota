"""Process-wide psycopg connection pool and the transaction context manager.

Targets Neon's direct (unpooled) endpoint. max_idle is shorter than Neon's idle cutoff so the pool
recycles connections before the server drops them; check= discards dead ones on checkout.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

_MAX_IDLE_S = 240
_pool: ConnectionPool[psycopg.Connection[dict[str, Any]]] | None = None


def init_pool(url: str, *, max_size: int, prepare_threshold: int | None) -> None:
    """Create the module pool, closing any pool created by an earlier app factory call.

    Args:
        url: PostgreSQL connection URL.
        max_size: Maximum simultaneous connections.
        prepare_threshold: Passed to psycopg; None disables server-side prepared statements.
    """
    global _pool
    previous = _pool
    _pool = ConnectionPool(
        url,
        min_size=0,
        max_size=max_size,
        max_idle=_MAX_IDLE_S,
        open=True,
        check=ConnectionPool.check_connection,
        kwargs={"prepare_threshold": prepare_threshold, "row_factory": dict_row},
    )
    if previous is not None:
        previous.close()


def close_pool() -> None:
    """Close and forget the module pool. Safe to call when no pool exists."""
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


@contextmanager
def transaction() -> Iterator[psycopg.Connection[dict[str, Any]]]:
    """Yield a pooled connection inside one transaction.

    Commits when the block exits normally and rolls back if it raises, so callers never manage
    commit state themselves. Rows come back as dicts.

    Raises:
        RuntimeError: init_pool() has not been called.
    """
    if _pool is None:
        raise RuntimeError("database pool is not initialised; call init_pool() first")
    with _pool.connection() as conn:
        yield conn

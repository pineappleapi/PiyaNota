"""Liveness endpoint so the host can probe the worker container."""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

HEALTH_PATH = "/health"


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - http.server naming
        ok = self.path == HEALTH_PATH
        body = b"ok" if ok else b"not found"
        self.send_response(200 if ok else 404)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002 - silence per-probe access logs
        return


def serve(port: int) -> threading.Thread:
    """Answer ``GET /health`` with ``ok`` on a daemon thread; port 0 picks a free port (see ``.port``)."""
    server = HTTPServer(("0.0.0.0", port), _Handler)
    thread = threading.Thread(target=server.serve_forever, name="piya-worker-health", daemon=True)
    thread.port = server.server_address[1]  # type: ignore[attr-defined] - lets tests find the port
    thread.start()
    return thread

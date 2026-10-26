"""Loopback HTTP management interface. Not a RouterOS API."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from lte_rndis_emu.state import StateError


class ControlServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, device, host: str, port: int):
        self.device = device
        super().__init__((host, port), _Handler)

    @property
    def port(self) -> int:
        return self.server_address[1]


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        return

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/health":
            self._json(200, {"ready": True})
            return
        if path == "/lte":
            self._json(200, self.server.device.snapshot())
            return
        self._json(404, {"error": "not found"})

    def do_POST(self):
        self._write()

    def do_PATCH(self):
        self._write()

    def _write(self):
        path = self.path.split("?", 1)[0]
        if path != "/lte":
            self._json(404, {"error": "not found"})
            return
        length = int(self.headers.get("Content-Length", "0"))
        if length > 65536:
            self._json(413, {"error": "body too large"})
            return
        raw = self.rfile.read(length) if length else b""
        try:
            patch = json.loads(raw.decode("utf-8") or "{}")
            self.server.device.update_lte(patch)
        except StateError as exc:
            self._json(400, {"error": str(exc)})
            return
        except json.JSONDecodeError:
            self._json(400, {"error": "invalid JSON"})
            return
        self._json(200, self.server.device.snapshot())

    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

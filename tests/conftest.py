from __future__ import annotations

import os
import re
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

PAYLOAD = bytes(range(256)) * 2048
SLOW_PAYLOAD = bytes(reversed(range(256))) * 4096
SECOND_PAYLOAD = b"LiteDM-second-download\x00" * 30000


@dataclass
class ServerState:
    attempts: dict[str, int] = field(default_factory=dict)
    ranges: list[tuple[str, int]] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)


class Handler(BaseHTTPRequestHandler):
    server_version = "LiteDMTest/1.0"
    state: ServerState

    def log_message(self, *_args) -> None:
        pass

    def _payload(self, route: str) -> tuple[bytes, float, bool, bool]:
        if route == "/slow.bin":
            return SLOW_PAYLOAD, 0.015, True, True
        if route == "/slow-two.bin":
            return SECOND_PAYLOAD, 0.015, True, True
        if route == "/no-range.bin":
            return SLOW_PAYLOAD, 0.015, False, True
        if route == "/unknown.bin":
            return PAYLOAD, 0.0, True, False
        if route in {"/flaky.bin", "/empty.bin"}:
            data = b"" if route == "/empty.bin" else PAYLOAD
            return data, 0.0, True, True
        return PAYLOAD, 0.0, True, True

    def do_GET(self) -> None:
        route = urlsplit(self.path).path
        with self.state.lock:
            self.state.attempts[route] = self.state.attempts.get(route, 0) + 1
            attempt = self.state.attempts[route]
        if route == "/redirect.bin":
            self.send_response(302)
            self.send_header("Location", "/payload.bin")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if route == "/flaky.bin" and attempt == 1:
            self.send_response(503)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if route == "/missing.bin":
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        data, delay, ranges, include_length = self._payload(route)
        start = 0
        range_header = self.headers.get("Range")
        if range_header and ranges:
            match = re.fullmatch(r"bytes=(\d+)-", range_header)
            if match:
                start = int(match.group(1))
                with self.state.lock:
                    self.state.ranges.append((route, start))
        if start >= len(data) and start:
            self.send_response(416)
            self.send_header("Content-Range", f"bytes */{len(data)}")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        partial = start > 0
        self.send_response(206 if partial else 200)
        if partial:
            self.send_header("Content-Range", f"bytes {start}-{len(data) - 1}/{len(data)}")
        if ranges:
            self.send_header("Accept-Ranges", "bytes")
        if include_length:
            self.send_header("Content-Length", str(len(data) - start))
        content_type = "image/jpeg" if route == "/images" else "application/octet-stream"
        self.send_header("Content-Type", content_type)
        self.end_headers()
        self.close_connection = True
        try:
            for offset in range(start, len(data), 16384):
                self.wfile.write(data[offset : offset + 16384])
                self.wfile.flush()
                if delay:
                    time.sleep(delay)
        except (BrokenPipeError, ConnectionResetError):
            pass


@pytest.fixture(scope="session", autouse=True)
def application():
    app = QApplication.instance() or QApplication([])
    yield app
    app.processEvents()


@pytest.fixture
def http_server():
    state = ServerState()
    Handler.state = state
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    server.base_url = f"http://127.0.0.1:{server.server_port}"
    server.state = state
    yield server
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)

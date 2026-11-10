"""Dependency-free HTTP server for the 3x-ui usage portal."""

from __future__ import annotations

import json
import mimetypes
import os
import time
from collections import defaultdict, deque
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock
from urllib.parse import parse_qs, urlparse

from usage import UsageError, lookup_from_environment


ROOT = Path(__file__).resolve().parent
STATIC_ROOT = ROOT / "static"
MAX_ID_LENGTH = 160


class TTLCache:
    def __init__(self, seconds: int) -> None:
        self.seconds = seconds
        self._items: dict[str, tuple[float, dict]] = {}
        self._lock = Lock()

    def get(self, key: str) -> dict | None:
        now = time.monotonic()
        with self._lock:
            item = self._items.get(key)
            if not item:
                return None
            expires, value = item
            if expires <= now:
                self._items.pop(key, None)
                return None
            return value

    def put(self, key: str, value: dict) -> None:
        with self._lock:
            self._items[key] = (time.monotonic() + self.seconds, value)
            if len(self._items) > 1000:
                now = time.monotonic()
                self._items = {key: item for key, item in self._items.items() if item[0] > now}


class RateLimiter:
    def __init__(self, limit: int) -> None:
        self.limit = limit
        self._requests: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def allow(self, client: str) -> bool:
        now = time.monotonic()
        cutoff = now - 60
        with self._lock:
            entries = self._requests[client]
            while entries and entries[0] < cutoff:
                entries.popleft()
            if len(entries) >= self.limit:
                return False
            entries.append(now)
            return True


CACHE = TTLCache(max(0, int(os.getenv("XUI_CACHE_SECONDS", "15"))))
RATE_LIMITER = RateLimiter(max(1, int(os.getenv("XUI_RATE_LIMIT_PER_MINUTE", "30"))))


class PortalHandler(BaseHTTPRequestHandler):
    server_version = "UsagePortal/1.0"

    def log_message(self, fmt: str, *args: object) -> None:
        # Avoid logging query strings because they contain user identifiers.
        path = urlparse(self.path).path
        print(f'{self.address_string()} - "{self.command} {path}" {args[-2] if len(args) >= 2 else ""}')

    def _security_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; "
            "connect-src 'self'; font-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
        )
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")

    def _send_json(self, status: int, payload: dict, *, cache: str = "no-store") -> None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self._security_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", cache)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _send_file(self, path: Path) -> None:
        try:
            body = path.read_bytes()
        except FileNotFoundError:
            self._send_json(404, {"error": {"code": "not_found", "message": "Page not found."}})
            return
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_response(200)
        self._security_headers()
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Cache-Control", "public, max-age=300" if path.name != "index.html" else "no-cache")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _client_ip(self) -> str:
        # Intentionally do not trust X-Forwarded-For unless the deployment's
        # reverse proxy rewrites the socket address.
        return self.client_address[0]

    def _usage(self, query: str) -> None:
        if not RATE_LIMITER.allow(self._client_ip()):
            self._send_json(
                429,
                {"error": {"code": "rate_limited", "message": "Too many lookups. Please wait a minute."}},
            )
            return
        identifier = parse_qs(query, keep_blank_values=True).get("id", [""])[0].strip()
        if not identifier or len(identifier) > MAX_ID_LENGTH:
            self._send_json(
                400,
                {"error": {"code": "invalid_id", "message": "Enter a valid configuration ID."}},
            )
            return

        cached = CACHE.get(identifier)
        if cached:
            self._send_json(200, {"data": cached}, cache="private, max-age=5")
            return
        try:
            snapshot = lookup_from_environment(identifier).public_dict()
        except UsageError as exc:
            self._send_json(exc.status, {"error": {"code": exc.code, "message": str(exc)}})
            return
        except Exception:
            self._send_json(
                500,
                {"error": {"code": "internal_error", "message": "The lookup could not be completed."}},
            )
            return
        CACHE.put(identifier, snapshot)
        self._send_json(200, {"data": snapshot}, cache="private, max-age=5")

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/health":
            self._send_json(200, {"status": "ok"})
        elif parsed.path == "/api/usage":
            self._usage(parsed.query)
        elif parsed.path in {"/", "/index.html"}:
            self._send_file(STATIC_ROOT / "index.html")
        elif parsed.path.startswith("/static/"):
            relative = parsed.path.removeprefix("/static/")
            candidate = (STATIC_ROOT / relative).resolve()
            if STATIC_ROOT.resolve() not in candidate.parents:
                self._send_json(404, {"error": {"code": "not_found", "message": "Page not found."}})
            else:
                self._send_file(candidate)
        else:
            self._send_json(404, {"error": {"code": "not_found", "message": "Page not found."}})

    def do_HEAD(self) -> None:
        self.do_GET()


def main() -> None:
    host = os.getenv("APP_HOST", "127.0.0.1")
    port = int(os.getenv("APP_PORT", "3000"))
    server = ThreadingHTTPServer((host, port), PortalHandler)
    print(f"3x-ui usage portal listening on http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()


"""Fetch safe traffic fields from the configured 3x-ui client endpoint."""

from __future__ import annotations

import json
import os
import ssl
import time
from dataclasses import asdict, dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen


class UsageError(Exception):
    """A safe error that can be returned to the browser."""

    def __init__(self, message: str, *, code: str = "lookup_failed", status: int = 502):
        super().__init__(message)
        self.code = code
        self.status = status


@dataclass(frozen=True)
class ClientUsage:
    name: str
    usedTraffic: int
    totalGB: int
    remainingTraffic: int | None
    expiryTime: int
    enable: bool
    inboundIds: list[int]
    fetchedAt: int

    def public_dict(self) -> dict[str, Any]:
        return asdict(self)


_MAX_RESPONSE_BYTES = 1_048_576


def _client_url(template: str, name: str) -> str:
    if not name or len(name) > 128 or name in {".", ".."} or any(
        ord(char) < 32 or char in "/\\" for char in name
    ):
        raise UsageError("Enter a valid client name.", code="invalid_name", status=400)
    if template.count("{name}") != 1:
        raise UsageError(
            "XUI_CLIENT_URL_TEMPLATE must contain one {name} placeholder.",
            code="setup_required",
            status=503,
        )
    parsed = urlparse(template.replace("{name}", "sample-name"))
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or "{name}" not in urlparse(template).path
    ):
        raise UsageError(
            "XUI_CLIENT_URL_TEMPLATE must be a complete HTTPS client API URL.",
            code="setup_required",
            status=503,
        )
    return template.replace("{name}", quote(name, safe=""))


def _nonnegative_int(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise UsageError(f"The panel returned an invalid {field} value.")
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise UsageError(f"The panel returned an invalid {field} value.") from exc
    if number < 0:
        raise UsageError(f"The panel returned an invalid {field} value.")
    return number


def _request_client(url: str, token: str, timeout: float) -> dict[str, Any]:
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "3xui-usage-portal/1.0",
        },
        method="GET",
    )
    try:
        with urlopen(request, timeout=timeout, context=ssl.create_default_context()) as response:
            raw = response.read(_MAX_RESPONSE_BYTES + 1)
            if len(raw) > _MAX_RESPONSE_BYTES:
                raise UsageError("The panel returned an unexpectedly large response.")
    except HTTPError as exc:
        if exc.code == 404:
            raise UsageError("No client was found with that name.", code="not_found", status=404) from exc
        if exc.code == 401:
            raise UsageError("The panel rejected XUI_API_TOKEN.", code="panel_auth") from exc
        if exc.code == 403:
            raise UsageError(
                "XUI_API_TOKEN is not permitted to access the client API.",
                code="panel_permission",
            ) from exc
        raise UsageError(f"The panel returned HTTP {exc.code}.") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise UsageError("The 3x-ui panel could not be reached. Please try again shortly.") from exc

    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UsageError("The panel returned invalid JSON.") from exc
    if not isinstance(payload, dict):
        raise UsageError("The panel returned an unsupported client response.")
    return payload


def lookup_client(name: str, *, template: str, api_token: str, timeout: float) -> ClientUsage:
    """Read volume data from /panel/api/clients/get/{name}."""
    url = _client_url(template, name)
    if not api_token:
        raise UsageError("XUI_API_TOKEN is not configured.", code="setup_required", status=503)

    payload = _request_client(url, api_token, timeout)
    if payload.get("success") is False:
        raise UsageError("No client was found with that name.", code="not_found", status=404)
    obj = payload.get("obj")
    if payload.get("success") is not True or not isinstance(obj, dict):
        raise UsageError("The panel returned an unsupported client response.")
    client = obj.get("client")
    if not isinstance(client, dict):
        raise UsageError("The panel returned an unsupported client response.")

    used = _nonnegative_int(obj.get("usedTraffic"), "usedTraffic")
    total = _nonnegative_int(client.get("totalGB"), "totalGB")
    expiry = client.get("expiryTime")
    if isinstance(expiry, bool):
        raise UsageError("The panel returned an invalid expiryTime value.")
    try:
        expiry = int(expiry)
    except (TypeError, ValueError) as exc:
        raise UsageError("The panel returned an invalid expiryTime value.") from exc
    inbound_ids = obj.get("inboundIds")
    if not isinstance(inbound_ids, list) or any(
        isinstance(item, bool) or not isinstance(item, int) for item in inbound_ids
    ):
        raise UsageError("The panel returned invalid inboundIds.")

    return ClientUsage(
        name=name,
        usedTraffic=used,
        totalGB=total,
        remainingTraffic=None if total == 0 else max(0, total - used),
        expiryTime=expiry,
        enable=bool(client.get("enable", True)),
        inboundIds=inbound_ids,
        fetchedAt=int(time.time() * 1000),
    )


def lookup_from_environment(name: str) -> ClientUsage:
    template = os.getenv("XUI_CLIENT_URL_TEMPLATE", "").strip()
    if not template:
        raise UsageError("XUI_CLIENT_URL_TEMPLATE is not configured.", code="setup_required", status=503)
    token = os.getenv("XUI_API_TOKEN", "").strip()
    try:
        timeout = float(os.getenv("XUI_REQUEST_TIMEOUT", "8"))
    except ValueError as exc:
        raise UsageError("XUI_REQUEST_TIMEOUT must be a number.", code="setup_required", status=503) from exc
    if timeout <= 0:
        raise UsageError("XUI_REQUEST_TIMEOUT must be positive.", code="setup_required", status=503)
    return lookup_client(name, template=template, api_token=token, timeout=timeout)

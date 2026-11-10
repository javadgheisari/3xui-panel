"""3x-ui usage lookup adapters and normalization.

The public subscription adapter consumes the same ``?format=info`` view-model
used by 3x-ui's own subscription page. Authenticated adapters support both an
actual VLESS/VMess UUID and a direct per-client lookup by config name/email.
"""

from __future__ import annotations

import json
import os
import re
import ssl
import time
from dataclasses import asdict, dataclass
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urljoin, urlparse, urlunparse
from urllib.request import Request, urlopen


class UsageError(Exception):
    """A safe, user-facing lookup failure."""

    def __init__(self, message: str, *, code: str = "lookup_failed", status: int = 502):
        super().__init__(message)
        self.code = code
        self.status = status


@dataclass(frozen=True)
class UsageSnapshot:
    identifier: str
    used_bytes: int
    upload_bytes: int | None
    download_bytes: int | None
    total_bytes: int
    remaining_bytes: int | None
    unlimited: bool
    enabled: bool
    online: bool | None
    expires_at: int | None
    last_online_at: int | None
    title: str
    fetched_at: int

    def public_dict(self) -> dict[str, Any]:
        return asdict(self)


_SUB_ID_RE = re.compile(r"^[A-Za-z0-9_-]{4,128}$")
_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-8][0-9a-fA-F]{3}-"
    r"[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$"
)
_USERINFO_RE = re.compile(r"(?:^|;)\s*(upload|download|total|expire)\s*=\s*(\d+)", re.I)
_MAX_RESPONSE_BYTES = 1_048_576


def _as_int(value: Any, default: int = 0) -> int:
    if isinstance(value, bool):
        return default
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return default


def _timestamp_ms(value: Any) -> int | None:
    timestamp = _as_int(value)
    if timestamp <= 0:
        return None
    # 3x-ui exposes expiry in seconds in the subscription view-model and
    # milliseconds in panel records.
    return timestamp * 1000 if timestamp < 10_000_000_000 else timestamp


def _safe_title(value: Any) -> str:
    if not isinstance(value, str):
        return "Your plan"
    cleaned = " ".join(value.strip().split())
    return cleaned[:80] or "Your plan"


def _validate_url(url: str, variable_name: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise UsageError(
            f"{variable_name} must be a complete http(s) URL.",
            code="setup_required",
            status=503,
        )
    if parsed.username or parsed.password:
        raise UsageError(
            f"{variable_name} cannot contain URL credentials.",
            code="setup_required",
            status=503,
        )


def _request_json(
    url: str,
    *,
    timeout: float,
    token: str | None = None,
    not_found_message: str = "No active configuration was found for that ID.",
) -> tuple[Any, Mapping[str, str]]:
    headers = {
        "Accept": "application/json",
        "User-Agent": "3xui-usage-portal/1.0",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(url, headers=headers, method="GET")

    try:
        with urlopen(request, timeout=timeout, context=ssl.create_default_context()) as response:
            raw = response.read(_MAX_RESPONSE_BYTES + 1)
            if len(raw) > _MAX_RESPONSE_BYTES:
                raise UsageError("The panel returned an unexpectedly large response.")
            try:
                return json.loads(raw.decode("utf-8")), response.headers
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise UsageError("The panel returned an invalid response.") from exc
    except HTTPError as exc:
        if exc.code == 404:
            raise UsageError(not_found_message, code="not_found", status=404) from exc
        if exc.code == 401:
            raise UsageError(
                "The panel rejected XUI_API_TOKEN. Check that it is an enabled API token from the panel's Security settings.",
                code="panel_auth",
                status=502,
            ) from exc
        if exc.code == 403:
            raise UsageError(
                "XUI_API_TOKEN is not permitted to access this panel endpoint. Use a token with the required API permissions.",
                code="panel_permission",
                status=502,
            ) from exc
        raise UsageError(f"The panel returned HTTP {exc.code}.") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise UsageError("The 3x-ui panel could not be reached. Please try again shortly.") from exc


def _subscription_url(template: str, identifier: str) -> str:
    if "{id}" not in template:
        raise UsageError(
            "XUI_SUBSCRIPTION_URL_TEMPLATE must contain {id}.",
            code="setup_required",
            status=503,
        )
    _validate_url(template.replace("{id}", "sample-id"), "XUI_SUBSCRIPTION_URL_TEMPLATE")
    target = template.replace("{id}", quote(identifier, safe=""))
    parsed = urlparse(target)
    query = parsed.query
    info_query = urlencode({"format": "info"})
    parsed = parsed._replace(query=f"{query}&{info_query}" if query else info_query, fragment="")
    return urlunparse(parsed)


def lookup_subscription(identifier: str, *, template: str, timeout: float) -> UsageSnapshot:
    if not _SUB_ID_RE.fullmatch(identifier):
        raise UsageError(
            "Enter a valid subscription ID (letters, numbers, dashes, or underscores).",
            code="invalid_id",
            status=400,
        )

    data, headers = _request_json(_subscription_url(template, identifier), timeout=timeout)
    if not isinstance(data, dict):
        raise UsageError("The panel returned an unsupported subscription response.")

    # Current 3x-ui returns a bare view-model. Accept an envelope as well for
    # compatibility with proxies that wrap panel responses.
    if isinstance(data.get("obj"), dict):
        data = data["obj"]

    upload = _as_int(data.get("uploadByte"))
    download = _as_int(data.get("downloadByte"))
    total = _as_int(data.get("totalByte"))

    # Older deployments may expose exact values only in subscription-userinfo.
    if upload == download == total == 0:
        userinfo = headers.get("subscription-userinfo", "")
        values = {key.lower(): int(value) for key, value in _USERINFO_RE.findall(userinfo)}
        upload = values.get("upload", 0)
        download = values.get("download", 0)
        total = values.get("total", 0)
        if not data.get("expire") and values.get("expire"):
            data["expire"] = values["expire"]

    used = upload + download
    unlimited = total == 0
    return UsageSnapshot(
        identifier=identifier,
        used_bytes=used,
        upload_bytes=upload,
        download_bytes=download,
        total_bytes=total,
        remaining_bytes=None if unlimited else max(0, total - used),
        unlimited=unlimited,
        enabled=bool(data.get("enabled", True)),
        online=bool(data["isOnline"]) if "isOnline" in data else None,
        expires_at=_timestamp_ms(data.get("expire")),
        last_online_at=_timestamp_ms(data.get("lastOnline")),
        title=_safe_title(data.get("subTitle")),
        fetched_at=int(time.time() * 1000),
    )


def _panel_list_url(panel_url: str) -> str:
    _validate_url(panel_url, "XUI_PANEL_URL")
    return urljoin(panel_url.rstrip("/") + "/", "panel/api/inbounds/list")


def _clients_from_settings(settings: Any) -> list[dict[str, Any]]:
    if isinstance(settings, str):
        try:
            settings = json.loads(settings)
        except json.JSONDecodeError:
            return []
    if not isinstance(settings, dict) or not isinstance(settings.get("clients"), list):
        return []
    return [client for client in settings["clients"] if isinstance(client, dict)]


def lookup_admin_uuid(
    identifier: str,
    *,
    panel_url: str,
    api_token: str,
    timeout: float,
) -> UsageSnapshot:
    if not _UUID_RE.fullmatch(identifier):
        raise UsageError("Enter a valid configuration UUID.", code="invalid_id", status=400)
    if not api_token:
        raise UsageError("XUI_API_TOKEN is not configured.", code="setup_required", status=503)

    payload, _ = _request_json(_panel_list_url(panel_url), timeout=timeout, token=api_token)
    if not isinstance(payload, dict) or payload.get("success") is False:
        raise UsageError("The panel did not accept the inbound list request.")
    inbounds = payload.get("obj")
    if not isinstance(inbounds, list):
        raise UsageError("The panel returned an unsupported inbound list response.")

    matches: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]] = []
    wanted = identifier.lower()
    for inbound in inbounds:
        if not isinstance(inbound, dict):
            continue
        stats = inbound.get("clientStats") or []
        stats_by_email = {
            str(item.get("email", "")).lower(): item
            for item in stats
            if isinstance(item, dict) and item.get("email")
        }
        for client in _clients_from_settings(inbound.get("settings")):
            client_uuid = str(client.get("id") or client.get("uuid") or "").lower()
            if client_uuid == wanted:
                stat = stats_by_email.get(str(client.get("email", "")).lower(), {})
                matches.append((client, stat, inbound))

    if not matches:
        raise UsageError("No configuration was found for that UUID.", code="not_found", status=404)

    # Traffic rows can be repeated on several inbounds for the same client.
    # Selecting the largest observed counter avoids double-counting shared rows.
    def used_for(item: tuple[dict[str, Any], dict[str, Any], dict[str, Any]]) -> int:
        return _as_int(item[1].get("up")) + _as_int(item[1].get("down"))

    client, stat, inbound = max(matches, key=used_for)
    upload = _as_int(stat.get("up"))
    download = _as_int(stat.get("down"))
    total = _as_int(client.get("totalGB") or stat.get("total"))
    used = upload + download
    unlimited = total == 0
    enabled = bool(client.get("enable", True)) and bool(inbound.get("enable", True))
    if "enable" in stat:
        enabled = enabled and bool(stat.get("enable"))

    return UsageSnapshot(
        identifier=identifier,
        used_bytes=used,
        upload_bytes=upload,
        download_bytes=download,
        total_bytes=total,
        remaining_bytes=None if unlimited else max(0, total - used),
        unlimited=unlimited,
        enabled=enabled,
        online=None,
        expires_at=_timestamp_ms(client.get("expiryTime") or stat.get("expiryTime")),
        last_online_at=_timestamp_ms(stat.get("lastOnline")),
        title=_safe_title(inbound.get("remark")),
        fetched_at=int(time.time() * 1000),
    )


def _client_url(template: str, config_name: str) -> str:
    if "{config_name}" not in template:
        raise UsageError(
            "XUI_CLIENT_URL_TEMPLATE must contain {config_name}.",
            code="setup_required",
            status=503,
        )
    _validate_url(template.replace("{config_name}", "sample-name"), "XUI_CLIENT_URL_TEMPLATE")
    return template.replace("{config_name}", quote(config_name, safe=""))


def lookup_client(
    config_name: str,
    *,
    template: str,
    api_token: str,
    timeout: float,
) -> UsageSnapshot:
    """Fetch one client directly from ``/panel/api/clients/get/{email}``."""
    if (
        not config_name
        or len(config_name) > 128
        or config_name in {".", ".."}
        or any(ord(char) < 32 or char in "/\\" for char in config_name)
    ):
        raise UsageError("Enter a valid client name.", code="invalid_id", status=400)
    if not api_token:
        raise UsageError("XUI_API_TOKEN is not configured.", code="setup_required", status=503)

    payload, _ = _request_json(
        _client_url(template, config_name),
        timeout=timeout,
        token=api_token,
        not_found_message=(
            "The panel returned 404 for this client lookup. Check the config name and client API URL."
        ),
    )
    if not isinstance(payload, dict):
        raise UsageError("The panel returned an unsupported client response.")
    if payload.get("success") is False or ("obj" in payload and payload["obj"] is None):
        raise UsageError("No configuration was found for that client name.", code="not_found", status=404)

    data = payload.get("obj", payload)
    if isinstance(data, list):
        data = data[0] if data else None
    if not isinstance(data, dict):
        raise UsageError("The panel returned an unsupported client response.")

    client = data.get("client") if isinstance(data.get("client"), dict) else data
    traffic = data.get("traffic") if isinstance(data.get("traffic"), dict) else data
    upload_value = traffic.get("up", client.get("up"))
    download_value = traffic.get("down", client.get("down"))
    has_directional_traffic = upload_value is not None and download_value is not None
    upload = _as_int(upload_value) if has_directional_traffic else None
    download = _as_int(download_value) if has_directional_traffic else None
    used = (
        upload + download
        if has_directional_traffic
        else _as_int(data.get("usedTraffic", traffic.get("usedTraffic", client.get("usedTraffic"))))
    )
    total = _as_int(client.get("totalGB", client.get("total")))
    unlimited = total == 0
    return UsageSnapshot(
        identifier=config_name,
        used_bytes=used,
        upload_bytes=upload,
        download_bytes=download,
        total_bytes=total,
        remaining_bytes=None if unlimited else max(0, total - used),
        unlimited=unlimited,
        enabled=bool(client.get("enable", True)),
        online=bool(traffic["isOnline"]) if "isOnline" in traffic else None,
        expires_at=_timestamp_ms(client.get("expiryTime") or traffic.get("expiryTime")),
        last_online_at=_timestamp_ms(traffic.get("lastOnline")),
        title=_safe_title(client.get("remark") or client.get("email") or config_name),
        fetched_at=int(time.time() * 1000),
    )


def demo_snapshot(identifier: str) -> UsageSnapshot:
    if identifier not in {"demo", "demo-7b6e-4fd2"}:
        raise UsageError("Use demo-7b6e-4fd2 while demo mode is enabled.", code="not_found", status=404)
    gib = 1024**3
    return UsageSnapshot(
        identifier=identifier,
        used_bytes=int(31.7 * gib),
        upload_bytes=int(4.2 * gib),
        download_bytes=int(27.5 * gib),
        total_bytes=100 * gib,
        remaining_bytes=int(68.3 * gib),
        unlimited=False,
        enabled=True,
        online=True,
        expires_at=int((time.time() + 18 * 86400) * 1000),
        last_online_at=int((time.time() - 90) * 1000),
        title="Freedom 100",
        fetched_at=int(time.time() * 1000),
    )


def lookup_from_environment(identifier: str) -> UsageSnapshot:
    if os.getenv("XUI_DEMO_MODE", "").lower() in {"1", "true", "yes"}:
        return demo_snapshot(identifier)

    mode = os.getenv("XUI_LOOKUP_MODE", "subscription").strip().lower()
    timeout = float(os.getenv("XUI_REQUEST_TIMEOUT", "8"))
    if mode == "subscription":
        template = os.getenv("XUI_SUBSCRIPTION_URL_TEMPLATE", "").strip()
        if not template:
            raise UsageError(
                "The service has not been connected to a 3x-ui subscription server yet.",
                code="setup_required",
                status=503,
            )
        return lookup_subscription(identifier, template=template, timeout=timeout)
    if mode == "admin_uuid":
        return lookup_admin_uuid(
            identifier,
            panel_url=os.getenv("XUI_PANEL_URL", "").strip(),
            api_token=os.getenv("XUI_API_TOKEN", "").strip(),
            timeout=timeout,
        )
    if mode == "client":
        template = os.getenv("XUI_CLIENT_URL_TEMPLATE", "").strip()
        if not template:
            raise UsageError(
                "XUI_CLIENT_URL_TEMPLATE is not configured.",
                code="setup_required",
                status=503,
            )
        return lookup_client(
            identifier,
            template=template,
            api_token=os.getenv("XUI_API_TOKEN", "").strip(),
            timeout=timeout,
        )
    raise UsageError(
        "XUI_LOOKUP_MODE must be subscription, admin_uuid, or client.",
        code="setup_required",
        status=503,
    )


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
        raise UsageError("نام کاربر معتبر وارد کنید.", code="invalid_name", status=400)
    if template.count("{name}") != 1:
        raise UsageError(
            "نشانی API باید یک جای‌نگهدار {name} داشته باشد.",
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
            "نشانی API کاربر باید یک نشانی کامل HTTPS باشد.",
            code="setup_required",
            status=503,
        )
    return template.replace("{name}", quote(name, safe=""))


def _nonnegative_int(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise UsageError(f"مقدار {field} در پاسخ پنل معتبر نیست.")
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise UsageError(f"مقدار {field} در پاسخ پنل معتبر نیست.") from exc
    if number < 0:
        raise UsageError(f"مقدار {field} در پاسخ پنل معتبر نیست.")
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
                raise UsageError("پاسخ پنل بیش از حد بزرگ است.")
    except HTTPError as exc:
        if exc.code == 404:
            raise UsageError("کاربری با این نام پیدا نشد.", code="not_found", status=404) from exc
        if exc.code == 401:
            raise UsageError("توکن API توسط پنل پذیرفته نشد.", code="panel_auth") from exc
        if exc.code == 403:
            raise UsageError(
                "توکن API مجوز دسترسی به اطلاعات کاربران را ندارد.",
                code="panel_permission",
            ) from exc
        raise UsageError(f"پنل خطای HTTP {exc.code} برگرداند.") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise UsageError("ارتباط با پنل برقرار نشد. کمی بعد دوباره تلاش کنید.") from exc

    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UsageError("پاسخ پنل معتبر نیست.") from exc
    if not isinstance(payload, dict):
        raise UsageError("ساختار پاسخ پنل پشتیبانی نمی‌شود.")
    return payload


def lookup_client(name: str, *, template: str, api_token: str, timeout: float) -> ClientUsage:
    """Read volume data from /panel/api/clients/get/{name}."""
    url = _client_url(template, name)
    if not api_token:
        raise UsageError("توکن API تنظیم نشده است.", code="setup_required", status=503)

    payload = _request_client(url, api_token, timeout)
    if payload.get("success") is False:
        raise UsageError("کاربری با این نام پیدا نشد.", code="not_found", status=404)
    obj = payload.get("obj")
    if payload.get("success") is not True or not isinstance(obj, dict):
        raise UsageError("ساختار پاسخ پنل پشتیبانی نمی‌شود.")
    client = obj.get("client")
    if not isinstance(client, dict):
        raise UsageError("ساختار پاسخ پنل پشتیبانی نمی‌شود.")

    used = _nonnegative_int(obj.get("usedTraffic"), "usedTraffic")
    total = _nonnegative_int(client.get("totalGB"), "totalGB")
    expiry = client.get("expiryTime")
    if isinstance(expiry, bool):
        raise UsageError("تاریخ انقضا در پاسخ پنل معتبر نیست.")
    try:
        expiry = int(expiry)
    except (TypeError, ValueError) as exc:
        raise UsageError("تاریخ انقضا در پاسخ پنل معتبر نیست.") from exc
    inbound_ids = obj.get("inboundIds")
    if not isinstance(inbound_ids, list) or any(
        isinstance(item, bool) or not isinstance(item, int) for item in inbound_ids
    ):
        raise UsageError("شناسه ورودی‌ها در پاسخ پنل معتبر نیست.")

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
        raise UsageError("نشانی API کاربر تنظیم نشده است.", code="setup_required", status=503)
    token = os.getenv("XUI_API_TOKEN", "").strip()
    try:
        timeout = float(os.getenv("XUI_REQUEST_TIMEOUT", "8"))
    except ValueError as exc:
        raise UsageError("زمان انتظار درخواست باید عدد باشد.", code="setup_required", status=503) from exc
    if timeout <= 0:
        raise UsageError("زمان انتظار درخواست باید بیشتر از صفر باشد.", code="setup_required", status=503)
    return lookup_client(name, template=template, api_token=token, timeout=timeout)

"""Client for the Pleos Vehicle Data API (Private User flow).

Docs: https://document.pleos.ai/en/api-reference/vehicle-data-api/intro

Pleos does not document rate limits or the access-token lifetime, so the
client re-issues a token whenever the API reports an expired/invalid one and
surfaces HTTP 429 / 5xx as dedicated exceptions for the poller to back off on.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from datetime import date
from typing import Any, Callable

import httpx

log = logging.getLogger(__name__)

# Live status endpoints: key -> path below /v1/vehicles/{vin}
STATUS_ENDPOINTS: dict[str, str] = {
    "batteries": "/batteries",
    "powertrains": "/powertrains",
    "locations": "/locations",
    "driving": "/driving",
    "status": "/status",
    "freezer": "/freezer",
}

# Trip history endpoints (max 7 days per call)
HISTORY_ENDPOINTS: dict[str, str] = {
    "speed": "/speed",
    "status_data": "/status/data",
    "driving_data": "/driving/data",
    "powertrain_data": "/powertrains/data",
}

# Error codes that mean "get a new access token and try again"
AUTH_ERROR_CODES = {"40002", "40003", "40004", "401", "4011"}
# Error codes that mean "this vehicle has no data for this endpoint"
NO_DATA_CODES = {"4045", "4101"}


class PleosError(Exception):
    def __init__(self, http_status: int, code: str, message: str, request_id: str | None = None):
        super().__init__(f"{http_status} [{code}] {message}")
        self.http_status = http_status
        self.code = code
        self.message = message
        self.request_id = request_id


class PleosAuthError(PleosError):
    """Credentials rejected (wrong client id/secret, revoked or expired key)."""


class PleosNoData(PleosError):
    """The vehicle has no data for this endpoint (yet)."""


class PleosTransientError(PleosError):
    """Rate limited, server error or network problem: retry later."""

    def __init__(self, *args, retry_after: float | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.retry_after = retry_after


UsageCallback = Callable[[str, bool, int], None]


def _jwt_expiry(token: str) -> float | None:
    """Return the exp claim if the token happens to be a JWT, else None."""
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return float(json.loads(base64.urlsafe_b64decode(payload))["exp"])
    except Exception:
        return None


class PleosClient:
    def __init__(
        self,
        base_url: str,
        brand: str,
        client_id: str,
        client_secret: str,
        on_request: UsageCallback | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.brand = brand
        self._client_id = client_id
        self._client_secret = client_secret
        self._on_request = on_request or (lambda *_: None)
        self._http = httpx.AsyncClient(base_url=base_url, timeout=30, transport=transport)
        self._token: str | None = None
        self._token_exp: float | None = None
        self._token_lock = asyncio.Lock()

    async def close(self) -> None:
        await self._http.aclose()

    # ---- auth -------------------------------------------------------------

    async def _issue_token(self) -> str:
        try:
            resp = await self._http.post(
                "/v1/auth/personal-token",
                headers={"Brand": self.brand, "Content-Type": "application/json"},
                json={"clientId": self._client_id, "clientSecret": self._client_secret},
            )
        except httpx.HTTPError as exc:
            self._on_request("auth", False, 0)
            raise PleosTransientError(0, "network", str(exc)) from exc
        self._on_request("auth", resp.is_success, resp.status_code)
        if not resp.is_success:
            err = self._parse_error(resp)
            if isinstance(err, PleosTransientError):
                raise err
            raise PleosAuthError(err.http_status, err.code, err.message, err.request_id)
        token = resp.json()["data"]["accessToken"]
        self._token = token
        self._token_exp = _jwt_expiry(token)
        log.info("Issued new Pleos access token")
        return token

    async def _get_token(self) -> str:
        async with self._token_lock:
            # Refresh a minute early when the expiry is known
            if self._token and (self._token_exp is None or self._token_exp - 60 > time.time()):
                return self._token
            return await self._issue_token()

    # ---- requests ---------------------------------------------------------

    @staticmethod
    def _parse_error(resp: httpx.Response) -> PleosError:
        code, message, request_id = str(resp.status_code), resp.reason_phrase, None
        try:
            body = resp.json()
            err = body.get("error") or body.get("meta") or {}
            code = str(err.get("code", code))
            message = err.get("message", message)
            request_id = err.get("requestId")
        except Exception:
            pass
        if resp.status_code == 429 or resp.status_code >= 500:
            retry_after = resp.headers.get("Retry-After")
            return PleosTransientError(
                resp.status_code,
                code,
                message,
                request_id,
                retry_after=float(retry_after) if retry_after and retry_after.isdigit() else None,
            )
        if code in NO_DATA_CODES or resp.status_code in (404, 410):
            return PleosNoData(resp.status_code, code, message, request_id)
        if code in AUTH_ERROR_CODES or resp.status_code == 401:
            return PleosAuthError(resp.status_code, code, message, request_id)
        return PleosError(resp.status_code, code, message, request_id)

    async def _get(self, key: str, path: str, params: dict[str, str] | None = None) -> dict[str, Any]:
        for attempt in (1, 2):
            token = await self._get_token()
            try:
                resp = await self._http.get(
                    path,
                    params=params,
                    headers={"Authorization": f"Bearer {token}", "Brand": self.brand},
                )
            except httpx.HTTPError as exc:
                self._on_request(key, False, 0)
                raise PleosTransientError(0, "network", str(exc)) from exc
            self._on_request(key, resp.is_success, resp.status_code)
            if resp.is_success:
                return resp.json().get("data") or {}
            err = self._parse_error(resp)
            if isinstance(err, PleosAuthError) and attempt == 1:
                log.info("Access token rejected (%s), issuing a new one", err.code)
                if self._token == token:
                    self._token = None
                continue
            raise err
        raise AssertionError("unreachable")

    async def get_vehicles(self) -> list[dict[str, Any]]:
        data = await self._get("vehicles", "/v1/vehicles/consent")
        return data.get("vehicles") or []

    async def get_status(self, vin: str, key: str) -> dict[str, Any]:
        return await self._get(key, f"/v1/vehicles/{vin}{STATUS_ENDPOINTS[key]}")

    async def get_history(self, vin: str, key: str, start: date, end: date, zone_id: str) -> list[dict[str, Any]]:
        params = {"startDate": start.strftime("%Y%m%d"), "endDate": end.strftime("%Y%m%d"), "zoneId": zone_id}
        try:
            data = await self._get(key, f"/v1/vehicles/{vin}{HISTORY_ENDPOINTS[key]}", params)
        except PleosNoData:
            return []
        return data.get("trips") or []

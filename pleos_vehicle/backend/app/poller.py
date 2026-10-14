"""Background polling of the Pleos API.

- Live loop: every poll_interval seconds, each status endpoint per vehicle.
  Endpoints that keep returning "no data" (e.g. the freezer on a car without
  one) are only retried hourly.
- History loop: every history_sync_interval minutes, trips of yesterday and
  today; on first start a 7-day backfill.
- Rate limits are undocumented, so HTTP 429/5xx triggers exponential backoff
  (or the Retry-After header when present) shared by both loops.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from .config import Settings
from .mqtt import MqttPublisher
from .normalize import build_state
from .pleos import (
    HISTORY_ENDPOINTS,
    STATUS_ENDPOINTS,
    PleosAuthError,
    PleosClient,
    PleosError,
    PleosNoData,
    PleosTransientError,
)
from .storage import Storage, utcnow
from .trips import summarize

log = logging.getLogger(__name__)

NO_DATA_RETRY_S = 3600
NO_DATA_STREAK = 3
AUTH_RETRY_S = 900
MAX_BACKOFF_S = 1800
VEHICLE_REFRESH_S = 6 * 3600
BACKFILL_ATTEMPTS = 3


def has_values(obj: Any) -> bool:
    """True when a payload contains at least one non-null value besides its timestamp."""
    if isinstance(obj, dict):
        return any(has_values(v) for k, v in obj.items() if k != "timestamp")
    if isinstance(obj, list):
        return any(has_values(v) for v in obj)
    return obj is not None


@dataclass
class EndpointState:
    no_data_streak: int = 0
    skip_until: float = 0


class Poller:
    def __init__(self, settings: Settings, storage: Storage, client: PleosClient, mqtt: MqttPublisher):
        self.settings = settings
        self.storage = storage
        self.client = client
        self.mqtt = mqtt
        self.vehicles: list[dict[str, Any]] = storage.vehicles()
        self.backoff_until = 0.0
        self.backoff_level = 0
        self.last_error: str | None = None
        self.last_poll: str | None = None
        self.last_history_sync: str | None = None
        self.api_ok: bool | None = None
        self._endpoints: dict[tuple[str, str], EndpointState] = {}
        self._vehicles_fetched_at = 0.0
        self._wake_live = asyncio.Event()
        self._wake_history = asyncio.Event()

    # ---- public -----------------------------------------------------------

    def trigger(self, history: bool = False) -> None:
        (self._wake_history if history else self._wake_live).set()

    def status(self) -> dict[str, Any]:
        now = time.time()
        return {
            "api_ok": self.api_ok,
            "last_error": self.last_error,
            "last_poll": self.last_poll,
            "last_history_sync": self.last_history_sync,
            "backoff_seconds": max(0, round(self.backoff_until - now)),
            "poll_interval": self.settings.poll_interval,
            "history_sync_interval": self.settings.history_sync_interval,
            "calls_today": self.storage.calls_today(),
            "paused_endpoints": [
                {"vin": vin, "endpoint": ep, "retry_in_s": round(s.skip_until - now)}
                for (vin, ep), s in self._endpoints.items()
                if s.skip_until > now
            ],
        }

    async def run(self) -> None:
        await asyncio.gather(self._live_loop(), self._history_loop())

    # ---- helpers ----------------------------------------------------------

    def _zone(self) -> ZoneInfo:
        try:
            return ZoneInfo(self.settings.timezone)
        except Exception:
            return ZoneInfo("UTC")

    async def _sleep(self, seconds: float, event: asyncio.Event) -> None:
        try:
            await asyncio.wait_for(event.wait(), timeout=max(1, seconds))
        except asyncio.TimeoutError:
            pass
        event.clear()

    def _in_backoff(self) -> float:
        return max(0.0, self.backoff_until - time.time())

    def _on_success(self) -> None:
        self.api_ok, self.backoff_level, self.last_error = True, 0, None

    def _on_failure(self, exc: PleosError) -> None:
        self.api_ok = False
        if isinstance(exc, PleosAuthError):
            delay = AUTH_RETRY_S
            self.last_error = f"Credentials rejected ({exc.code}: {exc.message}). Check client_id/client_secret or reissue the key."
        else:
            self.backoff_level += 1
            delay = exc.retry_after if isinstance(exc, PleosTransientError) and exc.retry_after else min(
                self.settings.poll_interval * 2**self.backoff_level, MAX_BACKOFF_S
            )
            kind = "Rate limited" if exc.http_status == 429 else "API unavailable"
            self.last_error = f"{kind} ({exc.http_status} {exc.code}: {exc.message}). Backing off {int(delay)}s."
        self.backoff_until = time.time() + delay
        log.warning(self.last_error)

    async def _refresh_vehicles(self) -> None:
        vehicles = await self.client.get_vehicles()
        for v in vehicles:
            self.storage.upsert_vehicle(v)
        self.vehicles = self.storage.vehicles()
        self._vehicles_fetched_at = time.time()
        log.info("Found %d vehicle(s): %s", len(vehicles), ", ".join(v.get("sellname") or v["vin"] for v in vehicles))

    # ---- live loop --------------------------------------------------------

    async def _live_loop(self) -> None:
        while True:
            wait = self._in_backoff()
            if wait:
                await self._sleep(wait, self._wake_live)
                continue
            try:
                if not self.vehicles or time.time() - self._vehicles_fetched_at > VEHICLE_REFRESH_S:
                    await self._refresh_vehicles()
                for vehicle in self.vehicles:
                    await self.poll_vehicle(vehicle)
                self.last_poll = utcnow()
                self._on_success()
            except PleosError as exc:
                self._on_failure(exc)
                self._publish_all()
            except Exception:
                log.exception("Unexpected error while polling")
            await self._sleep(self.settings.poll_interval, self._wake_live)

    async def poll_vehicle(self, vehicle: dict[str, Any]) -> None:
        vin = vehicle["vin"]
        changed: set[str] = set()
        now = time.time()
        for key in STATUS_ENDPOINTS:
            ep = self._endpoints.setdefault((vin, key), EndpointState())
            if ep.skip_until > now:
                continue
            try:
                payload = await self.client.get_status(vin, key)
            except PleosNoData as exc:
                self._no_data(vin, key, ep, exc.code, exc.message)
                continue
            except (PleosAuthError, PleosTransientError):
                raise
            except PleosError as exc:
                self.storage.save_error(vin, key, exc.code, exc.message)
                continue
            if not has_values(payload):
                self._no_data(vin, key, ep, "empty", "All fields are null for this vehicle")
                continue
            ep.no_data_streak = 0
            if self.storage.save_latest(vin, key, payload):
                changed.add(key)
        self._after_poll(vehicle, changed)

    def _no_data(self, vin: str, key: str, ep: EndpointState, code: str, message: str) -> None:
        ep.no_data_streak += 1
        self.storage.save_error(vin, key, code, message)
        if ep.no_data_streak >= NO_DATA_STREAK:
            ep.skip_until = time.time() + NO_DATA_RETRY_S
            log.info("%s returns no data for %s, retrying hourly", key, vin)

    def vehicle_state(self, vin: str) -> dict[str, Any]:
        latest = self.storage.latest(vin)
        state = build_state({k: v["payload"] for k, v in latest.items()})
        state["api_calls_today"] = self.storage.calls_today()
        state["api_ok"] = self.api_ok
        return state

    def _after_poll(self, vehicle: dict[str, Any], changed: set[str]) -> None:
        vin = vehicle["vin"]
        latest = self.storage.latest(vin)
        state = self.vehicle_state(vin)

        def ts(key: str) -> str:
            payload = (latest.get(key) or {}).get("payload") or {}
            return payload.get("timestamp") or utcnow()

        if "locations" in changed and state.get("latitude") is not None:
            self.storage.add_location(vin, ts("locations"), state)
        if changed & {"batteries", "powertrains"}:
            point_ts = ts("batteries") if "batteries" in changed else ts("powertrains")
            self.storage.add_battery_point(vin, point_ts, state)
        if "batteries" in changed:
            self.storage.track_charging(vin, ts("batteries"), state.get("charging"), state.get("battery_soc"), state.get("charge_status"))
        self.mqtt.update(vehicle, state)

    def _publish_all(self) -> None:
        for vehicle in self.vehicles:
            self.mqtt.update(vehicle, self.vehicle_state(vehicle["vin"]))

    # ---- history loop -----------------------------------------------------

    async def _history_loop(self) -> None:
        await asyncio.sleep(10)  # let the live loop discover vehicles first
        while True:
            wait = self._in_backoff()
            if wait or not self.vehicles:
                await self._sleep(wait or 30, self._wake_history)
                continue
            try:
                for vehicle in self.vehicles:
                    await self.sync_history(vehicle["vin"])
                self.last_history_sync = utcnow()
                self.storage.prune()
            except PleosError as exc:
                self._on_failure(exc)
            except Exception:
                log.exception("Unexpected error while syncing trip history")
            await self._sleep(self.settings.history_sync_interval * 60, self._wake_history)

    async def sync_history(self, vin: str) -> int:
        """Fetch recent trips for one vehicle. Returns the number of trips touched."""
        zone = self._zone()
        today = datetime.now(zone).date()
        backfilled = self.storage.get_meta(f"backfill_v2:{vin}") is not None
        days = self.settings.history_backfill_days if not backfilled else 2
        start: date = today - timedelta(days=max(1, min(days, 7)) - 1)

        touched: set[str] = set()
        failed = False
        for kind in HISTORY_ENDPOINTS:
            try:
                trips = await self._fetch_history(vin, kind, start, today)
            except (PleosAuthError, PleosTransientError):
                raise
            except PleosError as exc:
                failed = True
                log.warning("History %s for %s failed: %s", kind, vin, exc)
                self.storage.save_history_status(vin, kind, f"{start}..{today}", None, exc.code, exc.message)
                continue
            self.storage.save_history_status(vin, kind, f"{start}..{today}", len(trips))
            for trip in trips:
                start_time = trip.get("triggerStartTime")
                if not start_time:
                    continue
                self.storage.save_trip_part(vin, start_time, kind, trip.get("tripLength"), trip)
                touched.add(start_time)

        for start_time in touched:
            length_ms, parts = self.storage.trip_parts(vin, start_time)
            self.storage.set_trip_summary(vin, start_time, summarize(start_time, length_ms, parts))
        if not backfilled:
            # Retry a failed backfill on the next syncs, but give up after a few attempts
            attempts = int(self.storage.get_meta(f"backfill_v2_attempts:{vin}") or 0) + 1
            self.storage.set_meta(f"backfill_v2_attempts:{vin}", str(attempts))
            if not failed or attempts >= BACKFILL_ATTEMPTS:
                self.storage.set_meta(f"backfill_v2:{vin}", datetime.now(timezone.utc).isoformat())
        log.info("Synced %d trip(s) for %s since %s", len(touched), vin, start)
        return len(touched)

    async def _fetch_history(self, vin: str, kind: str, start: date, end: date) -> list[dict[str, Any]]:
        """Fetch a date range; if the API rejects the range, fall back to one request per day."""
        try:
            return await self.client.get_history(vin, kind, start, end, self.settings.timezone)
        except (PleosAuthError, PleosTransientError):
            raise
        except PleosError as exc:
            if start == end:
                raise
            log.info("History %s %s..%s rejected (%s), retrying per day", kind, start, end, exc)
        trips: list[dict[str, Any]] = []
        errors: list[PleosError] = []
        day = start
        while day <= end:
            try:
                trips += await self.client.get_history(vin, kind, day, day, self.settings.timezone)
            except (PleosAuthError, PleosTransientError):
                raise
            except PleosError as exc:
                errors.append(exc)
            day += timedelta(days=1)
        if errors and len(errors) == (end - start).days + 1:
            raise errors[-1]
        return trips

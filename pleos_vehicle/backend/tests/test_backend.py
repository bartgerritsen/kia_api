import asyncio
from datetime import date

import httpx
import pytest

from app import mock
from app.config import Settings
from app.mqtt import MqttPublisher
from app.normalize import build_state, tire_to_bar, to_km
from app.pleos import PleosAuthError, PleosClient, PleosNoData, PleosTransientError
from app.poller import Poller, has_values
from app.storage import Storage
from app.trips import summarize, telemetry


def run(coro):
    return asyncio.run(coro)


# ---- normalize ----------------------------------------------------------------


def test_tire_conversion_matches_docs():
    assert tire_to_bar(36, "bar") == 3.6
    assert tire_to_bar(72, "kpa") == 3.6  # 72 * 5 = 360 kPa
    assert tire_to_bar(52, "psi") == pytest.approx(3.59, abs=0.01)
    assert tire_to_bar(255, "psi") is None


def test_distance_units():
    assert to_km("106", "km") == 106
    assert to_km(10, "miles") == 16.1
    assert to_km("invalid", "km") is None


def test_build_state_phev():
    payloads = {
        "batteries": mock._status("/batteries"),
        "powertrains": mock._status("/powertrains"),
        "status": mock._status("/status"),
        "driving": mock._status("/driving"),
        "locations": mock._status("/locations"),
        "freezer": mock._status("/freezer"),
    }
    s = build_state(payloads)
    assert s["range_ev"] is not None and s["range_phev"] > s["range_ev"]
    assert s["fuel_level"] == 64
    assert s["tire_front_left_bar"] == 3.6
    assert s["warnings"] == ["washFluid"] and s["warning_count"] == 1
    assert "freezer_on" not in s  # null freezer is ignored
    assert s["last_vehicle_update"]


def test_doors_locked_logic():
    s = build_state({"status": {"doors": [{"left": "locked", "right": "open"}], "warnings": []}})
    assert s["doors_open"] is True and s["locked"] is False


def test_has_values():
    assert not has_values({"freezer": {"status": None, "temperature": None}, "timestamp": "x"})
    assert has_values({"charge": {"stateOfCharge": 0}})


# ---- trips --------------------------------------------------------------------


def _trip_parts(minutes=25):
    t = mock.datetime(2026, 10, 1, 8, tzinfo=mock.timezone.utc)
    rng = lambda: mock.random.Random(1)  # noqa: E731
    return {k: mock._trip(t, minutes, k, rng()) for k in ("speed", "powertrain_data", "driving_data", "status_data")}


def test_trip_summary_and_telemetry():
    parts = _trip_parts()
    start = parts["speed"]["triggerStartTime"]
    summary = summarize(start, 25 * 60000, parts)
    assert summary["duration_min"] == 25
    assert summary["distance_km"] > 10
    assert 0 < summary["engine_on_pct"] < 100
    assert summary["end_time"] == "2026-10-01T08:25:00Z"

    frames = telemetry(25 * 60000, parts)
    speed = frames["speed"]
    assert len(speed["t"]) <= 600
    assert len(speed["t"]) == len(speed["series"]["speed"])
    assert frames["status_data"]["series"]["tire_rear_right"][0] == 3.4


# ---- client -------------------------------------------------------------------


def _client(handler, calls=None):
    calls = calls if calls is not None else []
    return PleosClient("https://api.test", "kia", "id", "secret", lambda *a: calls.append(a), httpx.MockTransport(handler))


def test_client_reissues_expired_token():
    tokens = iter(["t1", "t2"])
    seen = []

    def handler(req):
        if req.url.path == "/v1/auth/personal-token":
            return httpx.Response(200, json={"data": {"accessToken": next(tokens)}})
        seen.append(req.headers["Authorization"])
        if req.headers["Authorization"] == "Bearer t1":
            return httpx.Response(400, json={"error": {"code": "40003", "message": "Token expired"}})
        return httpx.Response(200, json={"data": {"charge": {"stateOfCharge": 50}}})

    calls = []
    data = run(_client(handler, calls).get_status("VIN", "batteries"))
    assert data["charge"]["stateOfCharge"] == 50
    assert seen == ["Bearer t1", "Bearer t2"]
    assert [c[0] for c in calls] == ["auth", "batteries", "auth", "batteries"]


def test_client_error_mapping():
    def handler(req):
        if req.url.path == "/v1/auth/personal-token":
            return httpx.Response(200, json={"data": {"accessToken": "t"}})
        if req.url.path.endswith("/freezer"):
            return httpx.Response(404, json={"error": {"code": "4045", "message": "No Data"}})
        return httpx.Response(429, headers={"Retry-After": "120"}, json={"error": {"code": "429", "message": "Too many"}})

    c = _client(handler)
    with pytest.raises(PleosNoData):
        run(c.get_status("VIN", "freezer"))
    with pytest.raises(PleosTransientError) as exc:
        run(c.get_status("VIN", "batteries"))
    assert exc.value.retry_after == 120


def test_client_bad_credentials():
    def handler(req):
        return httpx.Response(404, json={"error": {"code": "40404", "message": "User or key not found"}})

    with pytest.raises(PleosAuthError):
        run(_client(handler).get_vehicles())


def test_history_no_data_is_empty():
    def handler(req):
        if req.url.path == "/v1/auth/personal-token":
            return httpx.Response(200, json={"data": {"accessToken": "t"}})
        return httpx.Response(404, json={"error": {"code": "4045", "message": "No Data"}})

    assert run(_client(handler).get_history("VIN", "speed", date(2026, 10, 1), date(2026, 10, 7), "UTC")) == []


# ---- poller + storage against the mock API ------------------------------------


@pytest.fixture
def poller(tmp_path):
    settings = Settings(client_id="id", client_secret="secret", data_dir=str(tmp_path), mqtt_enabled=False, mock=True)
    storage = Storage(settings.db_path)
    client = PleosClient(settings.api_base, "kia", "id", "secret", storage.record_call, mock.transport())
    return Poller(settings, storage, client, MqttPublisher(settings))


def test_poll_and_history_cycle(poller):
    async def scenario():
        await poller._refresh_vehicles()
        vehicle = poller.vehicles[0]
        for _ in range(3):
            await poller.poll_vehicle(vehicle)
        return await poller.sync_history(vehicle["vin"])

    touched = run(scenario())
    vin = mock.VIN
    state = poller.vehicle_state(vin)
    assert state["battery_soc"] is not None
    assert state["api_calls_today"] > 0
    # Freezer has no data three times in a row -> paused for an hour
    assert any(p["endpoint"] == "freezer" for p in poller.status()["paused_endpoints"])
    assert touched >= 10  # two trips per day over a 7-day backfill
    trips = poller.storage.trips(vin, "2000-01-01")
    assert trips[0]["distance_km"] > 0
    assert poller.storage.get_meta(f"backfill_v2:{vin}")


def test_charging_sessions(tmp_path):
    s = Storage(tmp_path / "t.db")
    s.track_charging("V", "2026-10-01T10:00:00Z", True, 30, "charging")
    s.track_charging("V", "2026-10-01T10:30:00Z", True, 50, "fastCharging")
    s.track_charging("V", "2026-10-01T11:00:00Z", False, 80, "notCharging")
    s.track_charging("V", "2026-10-01T12:00:00Z", False, 80, "notCharging")
    sessions = s.charging_sessions("V", "2000")
    assert len(sessions) == 1
    assert sessions[0]["start_soc"] == 30 and sessions[0]["end_soc"] == 80
    assert sessions[0]["kind"] == "dc" and sessions[0]["open"] == 0


# ---- MQTT discovery -----------------------------------------------------------


class FakeMqtt:
    def __init__(self):
        self.published = {}

    async def publish(self, topic, payload, qos=0, retain=False):
        self.published[topic] = payload


def test_mqtt_discovery_only_announces_known_values(tmp_path):
    import json

    settings = Settings(data_dir=str(tmp_path))
    publisher = MqttPublisher(settings)
    payloads = {k: mock._status(f"/{k}") for k in ("batteries", "powertrains", "status", "driving", "locations", "freezer")}
    state = build_state(payloads)
    vehicle = {"vin": "KNA1", "sellname": "Sorento"}
    publisher.update(vehicle, state)
    fake = FakeMqtt()
    run(publisher._publish(fake, "KNA1"))

    topics = fake.published
    assert "homeassistant/sensor/pleos_kna1/battery_soc/config" in topics
    assert "homeassistant/sensor/pleos_kna1/range_phev/config" in topics
    assert "homeassistant/device_tracker/pleos_kna1/location/config" in topics
    assert not any("freezer" in t for t in topics)  # null freezer -> no entity
    lock = json.loads(topics["homeassistant/binary_sensor/pleos_kna1/locked/config"])
    assert lock["device_class"] == "lock" and "invert" not in lock
    assert "{% elif v %}OFF" in lock["value_template"]  # HA lock: ON means unlocked
    state_payload = json.loads(topics["pleos/KNA1/state"])
    assert state_payload["battery_soc"] == state["battery_soc"]
    assert json.loads(topics["pleos/KNA1/location"])["latitude"] == state["latitude"]


def test_history_falls_back_to_single_days(poller):
    """When the API rejects a multi-day range, each day is requested separately."""
    real_handler = mock.handler
    ranges = []

    def strict(request):
        params = request.url.params
        if "startDate" in params:
            ranges.append((params["startDate"], params["endDate"]))
            if params["startDate"] != params["endDate"]:
                return httpx.Response(400, json={"error": {"code": "4002", "message": "Invalid Request Parameters"}})
        return real_handler(request)

    poller.client._http._transport = httpx.MockTransport(strict)

    async def scenario():
        await poller._refresh_vehicles()
        return await poller.sync_history(mock.VIN)

    touched = run(scenario())
    assert touched >= 10
    assert sum(1 for s, e in ranges if s == e) == 4 * 7  # per-day retry for every endpoint
    status = poller.storage.latest(mock.VIN)["speed"]
    assert status["error_code"] is None and status["payload"]["trips_returned"] >= 10
    assert poller.storage.get_meta(f"backfill_v2:{mock.VIN}")


def test_history_error_is_recorded_and_backfill_retried(poller):
    def broken(request):
        if "startDate" in request.url.params:
            return httpx.Response(400, json={"error": {"code": "4002", "message": "Invalid Request Parameters"}})
        return mock.handler(request)

    poller.client._http._transport = httpx.MockTransport(broken)

    async def scenario():
        await poller._refresh_vehicles()
        await poller.sync_history(mock.VIN)

    run(scenario())
    row = poller.storage.latest(mock.VIN)["driving_data"]
    assert row["error_code"] == "4002" and "Invalid Request Parameters" in row["error_message"]
    assert poller.storage.get_meta(f"backfill_v2:{mock.VIN}") is None  # will retry next sync


def test_forbidden_pauses_all_polling(poller):
    """A 403 must stop the cycle immediately and back off for a long time, not retry every endpoint."""
    import time

    from app.pleos import PleosForbidden

    calls = []

    def blocked(request):
        if request.url.path == "/v1/auth/personal-token":
            return mock.handler(request)
        calls.append(request.url.path)
        if request.url.path == "/v1/vehicles/consent":
            return mock.handler(request)
        return httpx.Response(403, json={"error": {"code": "403", "message": "Forbidden"}})

    poller.client._http._transport = httpx.MockTransport(blocked)

    async def scenario():
        await poller._refresh_vehicles()
        await poller.poll_vehicle(poller.vehicles[0])

    with pytest.raises(PleosForbidden) as exc:
        run(scenario())
    assert sum(1 for c in calls if c != "/v1/vehicles/consent") == 1  # stopped after the first refused call

    poller._on_failure(exc.value)
    assert poller.backoff_until - time.time() >= 890
    assert "Access denied" in poller.last_error and poller.api_ok is False
    assert sum(r["rate_limited"] for r in poller.storage.usage(1)) == 1


def test_forbidden_html_body_is_kept():
    from app.pleos import PleosForbidden

    def handler(req):
        if req.url.path == "/v1/auth/personal-token":
            return httpx.Response(200, json={"data": {"accessToken": "t"}})
        return httpx.Response(403, text="<html><body>Request blocked by WAF</body></html>")

    with pytest.raises(PleosForbidden) as exc:
        run(_client(handler).get_status("VIN", "batteries"))
    assert "Request blocked by WAF" in exc.value.message

"""Simulated Pleos API for local development (PLEOS_MOCK=1).

Simulates a plug-in hybrid that alternates between charging at home and
driving a loop, with response shapes copied from the API documentation.
"""

from __future__ import annotations

import json
import math
import random
import time
from datetime import datetime, timedelta, timezone

import httpx

VIN = "KNAMOCK0000000001"
HOME = (52.0907, 5.1214)
CYCLE_S = 3600  # 40 min charging, 20 min driving


def _envelope(data: dict) -> httpx.Response:
    meta = {"code": 200, "message": "Success", "success": True, "timestamp": _now(), "requestId": "mock"}
    return httpx.Response(200, json={"data": data, "meta": meta})


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _phase() -> tuple[bool, float]:
    """Return (driving, progress 0..1 within the phase)."""
    t = time.time() % CYCLE_S
    if t < CYCLE_S * 2 / 3:
        return False, t / (CYCLE_S * 2 / 3)
    return True, (t - CYCLE_S * 2 / 3) / (CYCLE_S / 3)


def _soc() -> float:
    driving, p = _phase()
    return round(35 + 50 * p, 1) if not driving else round(85 - 50 * p, 1)


def _position() -> tuple[float, float, float]:
    driving, p = _phase()
    if not driving:
        return HOME[0], HOME[1], 0
    angle = 2 * math.pi * p
    return HOME[0] + 0.03 * math.sin(angle), HOME[1] + 0.05 * (1 - math.cos(angle)), 60 + 30 * math.sin(3 * angle)


def _status(path: str) -> dict:
    driving, _ = _phase()
    lat, lon, speed = _position()
    ts = _now()
    if path.endswith("/batteries"):
        return {
            "charge": {
                "plugin": "disconnected" if driving else "connected",
                "status": "notCharging" if driving else "charging",
                "charging": not driving,
                "stateOfCharge": _soc(),
                "batteryCapacity": 13800,
                "targetStateOfCharge": {"standard": 90, "quick": 80},
                "remainTime": 0 if driving else int((90 - _soc()) * 2.5),
            },
            "timestamp": ts,
        }
    if path.endswith("/powertrains"):
        return {
            "engine": {"fuelLevel": 64},
            "batteries": [{"type": "main", "remainRatio": _soc()}],
            "distanceToEmpties": [
                {"type": "EV", "value": str(int(_soc() * 0.62)), "unit": "km"},
                {"type": "PHEV", "value": str(int(_soc() * 0.62) + 540), "unit": "km"},
            ],
            "timestamp": ts,
        }
    if path.endswith("/locations"):
        return {
            "location": {
                "latitude": round(lat, 6), "longitude": round(lon, 6), "altitude": 4, "heading": 90,
                "speed": {"value": round(speed), "unit": "kph"}, "type": 0,
            },
            "timestamp": ts,
        }
    if path.endswith("/driving"):
        on = "on" if driving else "off"
        return {
            "ignition": {"status": on, "ignitionDetails": [{"type": "ign1", "status": on}, {"type": "acc", "status": on}]},
            "sleepMode": "off" if driving else "on",
            "odometer": {"value": round(12850 + (time.time() / 3600) % 1000 * 15, 1), "unit": "km"},
            "transmission": {"parkingPosition": not driving},
            "timestamp": ts,
        }
    if path.endswith("/status"):
        door = "closed" if driving else "locked"
        return {
            "doors": [{"left": door, "right": door}, {"left": door, "right": door}],
            "hood": "closed", "trunk": "closed", "sunroof": "closed",
            "tire": [{"left": 36, "right": 36, "unit": "bar"}, {"left": 35, "right": 34, "unit": "bar"}],
            "warnings": ["washFluid"],
            "climateControl": {"mode": "auto", "status": "on" if driving else "off", "speed": -1, "temperature": {"value": 20.5, "unit": "C"}},
            "windshield": {"defrost": "off"},
            "steeringWheelHeat": "off",
            "seats": [
                {"left": {"heat": "low", "ventilation": "off"}, "right": {"heat": "off", "ventilation": "off"}},
                {"left": {"heat": "off", "ventilation": "off"}, "right": {"heat": "off", "ventilation": "off"}},
            ],
            "outsideTemperature": {"value": 11.5, "unit": "C"},
            "timestamp": ts,
        }
    # Freezer: this car has none, so every field is null
    return {"freezer": {"status": None, "temperature": None}, "timestamp": ts}


def _trip(start: datetime, minutes: int, kind: str, rng: random.Random) -> dict:
    n = minutes * 60
    speed = [max(0, min(130, round(70 + 45 * math.sin(i / 170) + rng.uniform(-4, 4)))) for i in range(n)]
    speed[:20] = [0] * 20
    speed[-20:] = [0] * 20
    trip = {"triggerStartTime": start.strftime("%Y-%m-%dT%H:%M:%S.000Z"), "tripLength": n * 1000}
    if kind == "speed":
        trip["location"] = {"speed": speed, "speedUnit": ["kph"] * n}
        trip["wheel"] = {k: [round(s * 1.01, 2) for s in speed] for k in ("speedFrontLeft", "speedFrontRight", "speedRearLeft", "speedRearRight")}
    elif kind == "powertrain_data":
        rpm = [0 if s < 60 else round(1400 + s * 12) for s in speed]
        trip["engine"] = {"rpm": rpm, "oilTemperature": [round(min(95, 20 + i / 12), 2) for i in range(n)]}
        trip["batteries"] = {"hv": {"voltage": [round(360 - i / n * 12, 1) for i in range(n)]}}
    elif kind == "driving_data":
        odo, dist = [], 12000.0
        for s in speed:
            dist += s / 3600
            odo.append(round(dist, 1))
        trip["odometer"] = {"value": odo}
        trip["ignition"] = {"status": ["on"] * n}
        trip["acceleration"] = {"longitudinal": [round((speed[min(i + 1, n - 1)] - s) / 35.3, 3) for i, s in enumerate(speed)]}
        trip["angularVelocity"] = {"yaw": [round(8 * math.sin(i / 40), 2) for i in range(n)]}
        trip["steeringWheel"] = {"angle": [round(30 * math.sin(i / 40), 1) for i in range(n)], "rotationSpeed": [round(abs(20 * math.cos(i / 40)), 1) for i in range(n)]}
        trip["transmission"] = {"gear": ["p"] * 10 + ["d"] * (n - 20) + ["p"] * 10}
        trip["seatbelt"] = {"driver": ["belted"] * n, "assistance": ["unbelted"] * n}
        trip["isla"] = {"optionUsm": ["assist"] * n, "optionUsm2": ["assist"] * n}
    elif kind == "status_data":
        trip["outsideTemperature"] = {"value": [11.5] * n}
        trip["tire"] = {
            "pressureFrontLeft": [36] * n, "pressureFrontRight": [36] * n,
            "pressureRearLeft": [35] * n, "pressureRearRight": [34] * n, "pressureUnit": ["bar"] * n,
        }
        trip["lamp"] = {"setting": ["autoLightSwOn"] * n}
        trip["warnings"] = {"lowFuelLevel": ["off"] * n}
        trip["doors"] = {k: ["close"] * n for k in ("openDriver", "openAssistance", "openRearLeft", "openRearRight")}
    return trip


def _history(path: str, params: httpx.QueryParams) -> dict:
    kind = {"/speed": "speed", "/status/data": "status_data", "/driving/data": "driving_data", "/powertrains/data": "powertrain_data"}
    key = next(v for k, v in kind.items() if path.endswith(k))
    start = datetime.strptime(params["startDate"], "%Y%m%d").replace(tzinfo=timezone.utc)
    end = datetime.strptime(params["endDate"], "%Y%m%d").replace(tzinfo=timezone.utc)
    trips = []
    day = start
    while day <= end:
        for hour, minutes in ((8, 25), (17, 32)):
            t = day + timedelta(hours=hour, minutes=day.day % 7)
            if t < datetime.now(timezone.utc):
                trips.append(_trip(t, minutes, key, random.Random(f"{t.isoformat()}")))
        day += timedelta(days=1)
    return {"trips": trips}


def handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path == "/v1/auth/personal-token":
        body = json.loads(request.content or b"{}")
        if not body.get("clientId"):
            return httpx.Response(400, json={"error": {"code": "40001", "message": "Invalid Parameters", "details": []}})
        return _envelope({"accessToken": "mock-token"})
    if request.headers.get("Authorization") != "Bearer mock-token":
        return httpx.Response(400, json={"error": {"code": "40004", "message": "Invalid token", "details": []}})
    if path == "/v1/vehicles/consent":
        return _envelope({"vehicles": [{"vin": VIN, "nickname": "Mock Sorento", "name": "MQ4 PHEV", "type": "PE", "sellname": "Sorento Plug-in Hybrid"}]})
    if path.endswith(("/speed", "/status/data", "/driving/data", "/powertrains/data")):
        return _envelope(_history(path, request.url.params))
    return _envelope(_status(path))


def transport() -> httpx.MockTransport:
    return httpx.MockTransport(handler)

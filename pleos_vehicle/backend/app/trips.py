"""Trip summaries and telemetry series from the history endpoints.

Each history endpoint returns trips keyed by triggerStartTime, with signals as
equally spaced arrays covering tripLength milliseconds. Trips from the four
endpoints are merged on (vin, triggerStartTime).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from .normalize import INVALID_RAW, tire_to_bar

MAX_POINTS = 600

# kind -> {signal name -> path inside the trip object}
SIGNALS: dict[str, dict[str, tuple[str, ...]]] = {
    "speed": {
        "speed": ("location", "speed"),
        "wheel_front_left": ("wheel", "speedFrontLeft"),
        "wheel_front_right": ("wheel", "speedFrontRight"),
        "wheel_rear_left": ("wheel", "speedRearLeft"),
        "wheel_rear_right": ("wheel", "speedRearRight"),
    },
    "powertrain_data": {
        "rpm": ("engine", "rpm"),
        "oil_temp": ("engine", "oilTemperature"),
        "hv_voltage": ("batteries", "hv", "voltage"),
    },
    "driving_data": {
        "odometer": ("odometer", "value"),
        "accel_long": ("acceleration", "longitudinal"),
        "yaw": ("angularVelocity", "yaw"),
        "steering_angle": ("steeringWheel", "angle"),
        "steering_speed": ("steeringWheel", "rotationSpeed"),
        "gear": ("transmission", "gear"),
        "ignition": ("ignition", "status"),
        "seatbelt_driver": ("seatbelt", "driver"),
        "seatbelt_passenger": ("seatbelt", "assistance"),
        "isla": ("isla", "optionUsm2"),
    },
    "status_data": {
        "outside_temp": ("outsideTemperature", "value"),
        "lamp": ("lamp", "setting"),
        "low_fuel": ("warnings", "lowFuelLevel"),
        "door_driver": ("doors", "openDriver"),
        "door_passenger": ("doors", "openAssistance"),
        "door_rear_left": ("doors", "openRearLeft"),
        "door_rear_right": ("doors", "openRearRight"),
    },
}


def _dig(obj: Any, path: tuple[str, ...]) -> Any:
    for key in path:
        if not isinstance(obj, dict):
            return None
        obj = obj.get(key)
    return obj


def _numbers(values: list[Any] | None, invalid: Any = None) -> list[float]:
    return [v for v in (values or []) if isinstance(v, (int, float)) and v != invalid]


def parse_start(start_time: str) -> datetime:
    return datetime.fromisoformat(start_time.replace("Z", "+00:00"))


def summarize(start_time: str, length_ms: int | None, parts: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Compute headline figures for one trip from whatever endpoints returned data."""
    start = parse_start(start_time)
    summary: dict[str, Any] = {
        "start_time": start_time,
        "end_time": (start + timedelta(milliseconds=length_ms or 0)).isoformat().replace("+00:00", "Z"),
        "duration_min": round((length_ms or 0) / 60000, 1),
    }

    odo = _numbers(_dig(parts.get("driving_data"), ("odometer", "value")))
    if len(odo) >= 2:
        summary["start_odometer"] = odo[0]
        summary["end_odometer"] = odo[-1]
        summary["distance_km"] = round(max(odo) - min(odo), 1)

    speeds = _numbers(_dig(parts.get("speed"), ("location", "speed")), INVALID_RAW)
    if speeds:
        summary["max_speed"] = max(speeds)
        moving = [v for v in speeds if v > 0]
        summary["avg_moving_speed"] = round(sum(moving) / len(moving), 1) if moving else 0

    rpm = _numbers(_dig(parts.get("powertrain_data"), ("engine", "rpm")))
    if rpm:
        # For a plug-in hybrid this shows how much of the trip ran on the engine
        summary["engine_on_pct"] = round(100 * sum(1 for v in rpm if v > 0) / len(rpm), 1)

    temps = _numbers(_dig(parts.get("status_data"), ("outsideTemperature", "value")))
    if temps:
        summary["outside_temp"] = round(sum(temps) / len(temps), 1)

    summary["kinds"] = sorted(parts)
    return summary


def _downsample(values: list[Any], step: int) -> list[Any]:
    return values[::step] if step > 1 else values


def telemetry(length_ms: int | None, parts: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Build per-endpoint time series (time axis in seconds since trip start)."""
    frames: dict[str, Any] = {}
    for kind, signals in SIGNALS.items():
        trip = parts.get(kind)
        if not trip:
            continue
        series: dict[str, list[Any]] = {}
        for name, path in signals.items():
            values = _dig(trip, path)
            if isinstance(values, list) and values:
                series[name] = values

        if kind == "status_data":
            tire = trip.get("tire") or {}
            units = tire.get("pressureUnit") or []
            for name, key in (
                ("tire_front_left", "pressureFrontLeft"),
                ("tire_front_right", "pressureFrontRight"),
                ("tire_rear_left", "pressureRearLeft"),
                ("tire_rear_right", "pressureRearRight"),
            ):
                raw = tire.get(key) or []
                if raw:
                    series[name] = [
                        tire_to_bar(v, units[i] if i < len(units) else None) for i, v in enumerate(raw)
                    ]
        if kind == "speed":
            for name in list(series):
                series[name] = [None if v == INVALID_RAW else v for v in series[name]]

        if not series:
            continue
        n = max(len(v) for v in series.values())
        interval = (length_ms or 0) / 1000 / n if n else 0
        step = max(1, -(-n // MAX_POINTS))
        frames[kind] = {
            "interval_s": round(interval * step, 3),
            "t": [round(i * interval, 1) for i in range(0, n, step)],
            "series": {name: _downsample(values, step) for name, values in series.items()},
        }
    return frames

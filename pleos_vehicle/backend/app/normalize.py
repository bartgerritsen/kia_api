"""Turn raw Pleos payloads into one flat, unit-normalised vehicle state.

The same state dict feeds the dashboard and the MQTT entities. Distances are
normalised to km, speeds to km/h and tyre pressures to bar. Raw sentinel values
(255 = invalid, "invalid") become None.
"""

from __future__ import annotations

from typing import Any

INVALID_RAW = 255

_DISTANCE_TO_KM = {"km": 1.0, "meter": 0.001, "miles": 1.609344, "mile": 1.609344, "feet": 0.0003048}
_SPEED_TO_KPH = {"kph": 1.0, "mph": 1.609344, "mps": 3.6}


def to_km(value: Any, unit: str | None) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    factor = _DISTANCE_TO_KM.get((unit or "km").lower())
    return round(number * factor, 1) if factor else None


def to_kph(value: Any, unit: str | None) -> float | None:
    if value is None:
        return None
    factor = _SPEED_TO_KPH.get((unit or "kph").lower())
    return round(float(value) * factor, 1) if factor else None


def tire_to_bar(raw: Any, unit: str | None) -> float | None:
    """Convert a raw tyre pressure value using the conversion table from the API docs."""
    if raw is None or raw == INVALID_RAW:
        return None
    unit = (unit or "").lower()
    if unit == "psi":
        return round(raw * 0.0689476, 2)
    if unit == "kpa":
        return round(raw * 5 / 100, 2)
    if unit == "bar":
        return round(raw / 10, 2)
    return None


def _valid(value: Any) -> Any:
    return None if value in ("invalid", "error") else value


def _on(value: Any) -> bool | None:
    value = _valid(value)
    return None if value is None else value == "on"


def build_state(payloads: dict[str, dict[str, Any] | None]) -> dict[str, Any]:
    """Build the normalised state from the latest payload of each status endpoint."""
    s: dict[str, Any] = {}

    battery = (payloads.get("batteries") or {}).get("charge") or {}
    if battery:
        target = battery.get("targetStateOfCharge") or {}
        plugin = _valid(battery.get("plugin"))
        s.update(
            battery_soc=battery.get("stateOfCharge"),
            battery_capacity=battery.get("batteryCapacity"),
            plugged_in=None if plugin is None else plugin == "connected",
            charging=battery.get("charging"),
            charge_status=battery.get("status"),
            charge_remaining_min=battery.get("remainTime"),
            target_soc_ac=target.get("standard"),
            target_soc_dc=target.get("quick"),
        )

    powertrain = payloads.get("powertrains") or {}
    if powertrain:
        s["fuel_level"] = (powertrain.get("engine") or {}).get("fuelLevel")
        for b in powertrain.get("batteries") or []:
            if b.get("type") == "main" and s.get("battery_soc") is None:
                s["battery_soc"] = b.get("remainRatio")
        for dte in powertrain.get("distanceToEmpties") or []:
            dtype = str(dte.get("type") or "").lower()
            if dtype and dtype != "invalid":
                s[f"range_{dtype}"] = to_km(dte.get("value"), dte.get("unit"))

    location = (payloads.get("locations") or {}).get("location") or {}
    if location.get("latitude") is not None and location.get("longitude") is not None:
        speed = location.get("speed") or {}
        s.update(
            latitude=location["latitude"],
            longitude=location["longitude"],
            altitude=location.get("altitude"),
            heading=location.get("heading"),
            speed_kph=to_kph(speed.get("value"), speed.get("unit")),
        )

    driving = payloads.get("driving") or {}
    if driving:
        ignition = driving.get("ignition") or {}
        odometer = driving.get("odometer") or {}
        s.update(
            ignition=_on(ignition.get("status")),
            sleep_mode=_on(driving.get("sleepMode")),
            odometer_km=to_km(odometer.get("value"), odometer.get("unit")),
            parked=(driving.get("transmission") or {}).get("parkingPosition"),
        )
        for detail in ignition.get("ignitionDetails") or []:
            s[f"ignition_{detail.get('type')}"] = _on(detail.get("status"))

    status = payloads.get("status") or {}
    if status:
        doors = status.get("doors") or []
        door_values = {}
        for row, label in zip(doors, ("front", "rear")):
            door_values[f"door_{label}_left"] = _valid(row.get("left"))
            door_values[f"door_{label}_right"] = _valid(row.get("right"))
        s.update(door_values)
        known = [v for v in door_values.values() if v is not None]
        s["doors_open"] = any(v == "open" for v in known) if known else None
        s["locked"] = all(v == "locked" for v in known) if known else None
        for part in ("hood", "trunk", "sunroof"):
            value = _valid(status.get(part))
            s[f"{part}_open"] = None if value is None else value == "open"

        for row, label in zip(status.get("tire") or [], ("front", "rear")):
            s[f"tire_{label}_left_bar"] = tire_to_bar(row.get("left"), row.get("unit"))
            s[f"tire_{label}_right_bar"] = tire_to_bar(row.get("right"), row.get("unit"))

        warnings = status.get("warnings")
        if warnings is not None:
            s["warnings"] = list(warnings)
            s["warning_count"] = len(warnings)

        climate = status.get("climateControl") or {}
        if climate:
            temp = climate.get("temperature") or {}
            s.update(
                climate_on=_on(climate.get("status")),
                climate_mode=_valid(climate.get("mode")),
                climate_fan_speed=climate.get("speed"),
                climate_set_temp=temp.get("value"),
                climate_temp_unit=temp.get("unit"),
            )
        s["defrost_on"] = _on((status.get("windshield") or {}).get("defrost"))
        s["steering_wheel_heat_on"] = _on(status.get("steeringWheelHeat"))
        for row, label in zip(status.get("seats") or [], ("front", "rear")):
            for side in ("left", "right"):
                seat = row.get(side) or {}
                s[f"seat_{label}_{side}_heat"] = seat.get("heat")
                s[f"seat_{label}_{side}_ventilation"] = seat.get("ventilation")
        outside = status.get("outsideTemperature") or {}
        s["outside_temp"] = outside.get("value")
        s["outside_temp_unit"] = outside.get("unit")

    freezer = (payloads.get("freezer") or {}).get("freezer") or {}
    if freezer and _valid(freezer.get("status")) is not None:
        s["freezer_on"] = _on(freezer.get("status"))
        s["freezer_temp"] = freezer.get("temperature")

    timestamps = [p.get("timestamp") for p in payloads.values() if p and p.get("timestamp")]
    s["last_vehicle_update"] = max(timestamps) if timestamps else None
    return s

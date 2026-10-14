"""Publish vehicle state to Home Assistant through MQTT discovery.

One HA device per VIN. All entities read from a single JSON state topic; an
entity's discovery config is only published once its value has been seen, so a
plug-in hybrid doesn't get a useless freezer sensor.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

import aiomqtt
import httpx

from .config import Settings

log = logging.getLogger(__name__)

BASE_TOPIC = "pleos"
AVAILABILITY_TOPIC = f"{BASE_TOPIC}/status"

DIAGNOSTIC = "diagnostic"

# (key, component, name, extra discovery fields)
ENTITIES: list[tuple[str, str, str, dict[str, Any]]] = [
    ("battery_soc", "sensor", "Battery", {"device_class": "battery", "unit_of_measurement": "%", "state_class": "measurement"}),
    ("fuel_level", "sensor", "Fuel level", {"unit_of_measurement": "%", "state_class": "measurement", "icon": "mdi:gas-station"}),
    ("range_ev", "sensor", "Electric range", {"device_class": "distance", "unit_of_measurement": "km", "state_class": "measurement"}),
    ("range_phev", "sensor", "Total range", {"device_class": "distance", "unit_of_measurement": "km", "state_class": "measurement"}),
    ("range_hev", "sensor", "Hybrid range", {"device_class": "distance", "unit_of_measurement": "km", "state_class": "measurement"}),
    ("range_ice", "sensor", "Fuel range", {"device_class": "distance", "unit_of_measurement": "km", "state_class": "measurement"}),
    ("range_fcev", "sensor", "Hydrogen range", {"device_class": "distance", "unit_of_measurement": "km", "state_class": "measurement"}),
    ("odometer_km", "sensor", "Odometer", {"device_class": "distance", "unit_of_measurement": "km", "state_class": "total_increasing"}),
    ("charge_status", "sensor", "Charge status", {"icon": "mdi:ev-station"}),
    ("charge_remaining_min", "sensor", "Charge time remaining", {"device_class": "duration", "unit_of_measurement": "min"}),
    ("target_soc_ac", "sensor", "Charge limit AC", {"unit_of_measurement": "%", "icon": "mdi:battery-charging-80"}),
    ("target_soc_dc", "sensor", "Charge limit DC", {"unit_of_measurement": "%", "icon": "mdi:battery-charging-high"}),
    ("speed_kph", "sensor", "Speed", {"device_class": "speed", "unit_of_measurement": "km/h", "state_class": "measurement"}),
    ("outside_temp", "sensor", "Outside temperature", {"device_class": "temperature", "unit_of_measurement": "°C", "state_class": "measurement"}),
    ("climate_set_temp", "sensor", "Climate set temperature", {"device_class": "temperature", "unit_of_measurement": "°C"}),
    ("tire_front_left_bar", "sensor", "Tyre pressure front left", {"device_class": "pressure", "unit_of_measurement": "bar", "state_class": "measurement"}),
    ("tire_front_right_bar", "sensor", "Tyre pressure front right", {"device_class": "pressure", "unit_of_measurement": "bar", "state_class": "measurement"}),
    ("tire_rear_left_bar", "sensor", "Tyre pressure rear left", {"device_class": "pressure", "unit_of_measurement": "bar", "state_class": "measurement"}),
    ("tire_rear_right_bar", "sensor", "Tyre pressure rear right", {"device_class": "pressure", "unit_of_measurement": "bar", "state_class": "measurement"}),
    ("freezer_temp", "sensor", "Freezer temperature", {"device_class": "temperature", "unit_of_measurement": "°C"}),
    ("warning_count", "sensor", "Warnings", {"icon": "mdi:car-light-alert", "json_attributes_template": "{{ {'warnings': value_json.get('warnings') or []} | tojson }}"}),
    ("last_vehicle_update", "sensor", "Last vehicle update", {"device_class": "timestamp", "entity_category": DIAGNOSTIC}),
    ("api_calls_today", "sensor", "API calls today", {"icon": "mdi:api", "state_class": "total_increasing", "entity_category": DIAGNOSTIC}),
    ("plugged_in", "binary_sensor", "Plugged in", {"device_class": "plug"}),
    ("charging", "binary_sensor", "Charging", {"device_class": "battery_charging"}),
    ("ignition", "binary_sensor", "Ignition", {"device_class": "power"}),
    ("sleep_mode", "binary_sensor", "Sleep mode", {"icon": "mdi:sleep", "entity_category": DIAGNOSTIC}),
    ("parked", "binary_sensor", "In park", {"icon": "mdi:car-brake-parking"}),
    ("locked", "binary_sensor", "Doors locked", {"device_class": "lock", "invert": True}),
    ("doors_open", "binary_sensor", "Doors", {"device_class": "door"}),
    ("hood_open", "binary_sensor", "Hood", {"device_class": "opening"}),
    ("trunk_open", "binary_sensor", "Trunk", {"device_class": "opening"}),
    ("sunroof_open", "binary_sensor", "Sunroof", {"device_class": "window"}),
    ("climate_on", "binary_sensor", "Climate", {"device_class": "running"}),
    ("defrost_on", "binary_sensor", "Defrost", {"icon": "mdi:car-defrost-front"}),
    ("steering_wheel_heat_on", "binary_sensor", "Steering wheel heater", {"icon": "mdi:steering"}),
    ("freezer_on", "binary_sensor", "Freezer", {"device_class": "running"}),
    ("api_ok", "binary_sensor", "Pleos API", {"device_class": "connectivity", "entity_category": DIAGNOSTIC}),
]


def _binary_template(key: str, invert: bool) -> str:
    on, off = ("OFF", "ON") if invert else ("ON", "OFF")
    return (
        f"{{% set v = value_json.get('{key}') %}}"
        f"{{% if v is none %}}None{{% elif v %}}{on}{{% else %}}{off}{{% endif %}}"
    )


async def _supervisor_mqtt() -> dict[str, Any] | None:
    """Ask the Supervisor for the Mosquitto add-on credentials."""
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        return None
    try:
        async with httpx.AsyncClient(timeout=10) as http:
            resp = await http.get("http://supervisor/services/mqtt", headers={"Authorization": f"Bearer {token}"})
        if resp.is_success:
            return resp.json().get("data")
        log.warning("No MQTT service from Supervisor (%s). Is the Mosquitto broker add-on installed?", resp.status_code)
    except httpx.HTTPError as exc:
        log.warning("Could not query Supervisor for MQTT: %s", exc)
    return None


class MqttPublisher:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.prefix = settings.mqtt_discovery_prefix
        self.connected = False
        self.status = "disabled" if not settings.mqtt_enabled else "starting"
        self._vehicles: dict[str, dict[str, Any]] = {}
        self._states: dict[str, dict[str, Any]] = {}
        self._announced: set[tuple[str, str]] = set()
        self._dirty: asyncio.Queue[str] = asyncio.Queue()

    def update(self, vehicle: dict[str, Any], state: dict[str, Any]) -> None:
        vin = vehicle["vin"]
        self._vehicles[vin] = vehicle
        self._states[vin] = state
        self._dirty.put_nowait(vin)

    async def _connection_params(self) -> dict[str, Any] | None:
        s = self.settings
        if s.mqtt_host:
            return {"hostname": s.mqtt_host, "port": s.mqtt_port or 1883, "username": s.mqtt_username, "password": s.mqtt_password}
        service = await _supervisor_mqtt()
        if not service:
            return None
        return {
            "hostname": service["host"],
            "port": int(service.get("port", 1883)),
            "username": service.get("username"),
            "password": service.get("password"),
        }

    async def run(self) -> None:
        if not self.settings.mqtt_enabled:
            return
        delay = 5
        while True:
            params = await self._connection_params()
            if not params:
                self.status = "no broker configured"
                await asyncio.sleep(300)
                continue
            try:
                will = aiomqtt.Will(AVAILABILITY_TOPIC, "offline", qos=1, retain=True)
                async with aiomqtt.Client(**params, identifier="pleos-vehicle-addon", will=will) as client:
                    self.connected, self.status, delay = True, "connected", 5
                    log.info("Connected to MQTT broker %s:%s", params["hostname"], params["port"])
                    await client.publish(AVAILABILITY_TOPIC, "online", qos=1, retain=True)
                    self._announced.clear()
                    for vin in self._states:
                        await self._publish(client, vin)
                    await client.subscribe(f"{self.prefix}/status")
                    await asyncio.gather(self._listen(client), self._drain(client))
            except aiomqtt.MqttError as exc:
                self.connected, self.status = False, f"error: {exc}"
                log.warning("MQTT connection lost (%s), retrying in %ss", exc, delay)
                await asyncio.sleep(delay)
                delay = min(delay * 2, 300)

    async def _listen(self, client: aiomqtt.Client) -> None:
        # Home Assistant restarted: re-send discovery and states
        async for message in client.messages:
            if message.payload in (b"online", "online"):
                self._announced.clear()
                await client.publish(AVAILABILITY_TOPIC, "online", qos=1, retain=True)
                for vin in self._states:
                    await self._publish(client, vin)

    async def _drain(self, client: aiomqtt.Client) -> None:
        while True:
            vin = await self._dirty.get()
            await self._publish(client, vin)

    async def _publish(self, client: aiomqtt.Client, vin: str) -> None:
        state = self._states[vin]
        vehicle = self._vehicles[vin]
        node = f"pleos_{vin.lower()}"
        state_topic = f"{BASE_TOPIC}/{vin}/state"
        device = {
            "identifiers": [node],
            "name": vehicle.get("nickname") or vehicle.get("sellname") or vin,
            "manufacturer": self.settings.brand.capitalize(),
            "model": vehicle.get("sellname") or vehicle.get("name"),
            "serial_number": vin,
        }

        for key, component, name, extra in ENTITIES:
            if (vin, key) in self._announced or state.get(key) is None:
                continue
            extra = dict(extra)
            config: dict[str, Any] = {
                "name": name,
                "unique_id": f"{node}_{key}",
                "state_topic": state_topic,
                "availability_topic": AVAILABILITY_TOPIC,
                "device": device,
            }
            if component == "binary_sensor":
                config["value_template"] = _binary_template(key, extra.pop("invert", False))
            else:
                config["value_template"] = f"{{{{ value_json.get('{key}') }}}}"
            if "json_attributes_template" in extra:
                config["json_attributes_topic"] = state_topic
            config.update(extra)
            await client.publish(f"{self.prefix}/{component}/{node}/{key}/config", json.dumps(config), qos=1, retain=True)
            self._announced.add((vin, key))

        location_topic = f"{BASE_TOPIC}/{vin}/location"
        if (vin, "location") not in self._announced and state.get("latitude") is not None:
            config = {
                "name": "Location",
                "unique_id": f"{node}_location",
                "json_attributes_topic": location_topic,
                "source_type": "gps",
                "availability_topic": AVAILABILITY_TOPIC,
                "device": device,
                "icon": "mdi:car",
            }
            await client.publish(f"{self.prefix}/device_tracker/{node}/location/config", json.dumps(config), qos=1, retain=True)
            self._announced.add((vin, "location"))

        payload = {key: state.get(key) for key, *_ in ENTITIES}
        payload["warnings"] = state.get("warnings") or []
        await client.publish(state_topic, json.dumps(payload), qos=1, retain=True)
        if state.get("latitude") is not None:
            location = {
                "latitude": state["latitude"],
                "longitude": state["longitude"],
                "gps_accuracy": 10,
                "altitude": state.get("altitude"),
                "heading": state.get("heading"),
                "speed": state.get("speed_kph"),
            }
            await client.publish(location_topic, json.dumps(location), qos=1, retain=True)

"""FastAPI entry point: REST API for the dashboard plus the background poller.

Served behind Home Assistant Ingress, so every route is relative and the
frontend calls `api/...` without a leading slash.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import mock
from .config import load_settings
from .mqtt import MqttPublisher
from .pleos import PleosClient
from .poller import Poller
from .storage import Storage, iso_ago
from .trips import telemetry

VERSION = "0.1.1"
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("pleos")

settings = load_settings()
storage = Storage(settings.db_path)
mqtt = MqttPublisher(settings)
client = PleosClient(
    settings.api_base,
    settings.brand,
    settings.client_id,
    settings.client_secret,
    on_request=storage.record_call,
    transport=mock.transport() if settings.mock else None,
)
poller = Poller(settings, storage, client, mqtt)


@asynccontextmanager
async def lifespan(_: FastAPI):
    tasks = []
    if settings.client_id and settings.client_secret or settings.mock:
        if settings.mock:
            log.warning("Running with the simulated Pleos API (mock mode)")
        tasks = [asyncio.create_task(poller.run()), asyncio.create_task(mqtt.run())]
    else:
        poller.last_error = "No client_id/client_secret configured. Set them in the add-on configuration."
        log.error(poller.last_error)
    yield
    for task in tasks:
        task.cancel()
    await client.close()


app = FastAPI(title="Pleos Vehicle", version=VERSION, lifespan=lifespan)


def _vehicle(vin: str) -> dict:
    for v in poller.vehicles:
        if v["vin"] == vin:
            return v
    raise HTTPException(404, "Unknown vehicle")


@app.get("/api/info")
def info():
    return {
        "version": VERSION,
        "brand": settings.brand,
        "language": settings.language,
        "timezone": settings.timezone,
        "mock": settings.mock,
        "mqtt": mqtt.status,
        "map_tile_url": settings.map_tile_url,
        "map_tile_attribution": settings.map_tile_attribution,
        "poller": poller.status(),
    }


@app.get("/api/vehicles")
def vehicles():
    return [{**v, "state": poller.vehicle_state(v["vin"])} for v in poller.vehicles]


@app.get("/api/vehicles/{vin}/state")
def vehicle_state(vin: str):
    vehicle = _vehicle(vin)
    endpoints = {
        key: {k: row.get(k) for k in ("fetched_at", "vehicle_ts", "error_code", "error_message", "error_at")}
        for key, row in storage.latest(vin).items()
    }
    return {"vehicle": vehicle, "state": poller.vehicle_state(vin), "endpoints": endpoints}


@app.get("/api/vehicles/{vin}/raw")
def vehicle_raw(vin: str):
    _vehicle(vin)
    return storage.latest(vin)


@app.get("/api/vehicles/{vin}/locations")
def vehicle_locations(vin: str, hours: float = 24, since: str | None = None, until: str | None = None):
    _vehicle(vin)
    return storage.locations(vin, since or iso_ago(hours=hours), until)


@app.get("/api/vehicles/{vin}/trips")
def vehicle_trips(vin: str, days: int = 30):
    _vehicle(vin)
    return storage.trips(vin, iso_ago(days=days))


@app.get("/api/vehicles/{vin}/trips/{start_time}")
def vehicle_trip(vin: str, start_time: str):
    _vehicle(vin)
    length_ms, parts = storage.trip_parts(vin, start_time)
    if not parts:
        raise HTTPException(404, "Unknown trip")
    summary = next((t for t in storage.trips(vin, start_time) if t.get("start_time") == start_time), {})
    route = storage.locations(vin, start_time[:19] + "Z", summary.get("end_time"))
    return {"summary": summary, "frames": telemetry(length_ms, parts), "route": route}


@app.get("/api/vehicles/{vin}/charging")
def vehicle_charging(vin: str, days: int = 30):
    _vehicle(vin)
    since = iso_ago(days=days)
    return {"sessions": storage.charging_sessions(vin, since), "history": storage.battery_history(vin, since)}


@app.get("/api/usage")
def usage(days: int = 14):
    return {"days": storage.usage(days), "poller": poller.status()}


@app.get("/api/diagnostics")
def diagnostics():
    """Everything needed to debug field mapping: raw payloads, normalised state, errors and usage."""
    body = {
        "info": info(),
        "vehicles": [
            {**v, "raw": storage.latest(v["vin"]), "state": poller.vehicle_state(v["vin"])} for v in poller.vehicles
        ],
        "usage": storage.usage(3),
    }
    return JSONResponse(body, headers={"Content-Disposition": 'attachment; filename="pleos-diagnostics.json"'})


@app.post("/api/refresh")
def refresh():
    poller.trigger()
    return {"ok": True}


@app.post("/api/history/sync")
def history_sync():
    poller.trigger(history=True)
    return {"ok": True}


if STATIC_DIR.exists():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        candidate = (STATIC_DIR / path).resolve()
        if path and candidate.is_file() and STATIC_DIR in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(STATIC_DIR / "index.html")

"""SQLite persistence in the add-on's /data folder (survives restarts and updates)."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS vehicles (
    vin TEXT PRIMARY KEY, nickname TEXT, name TEXT, type TEXT, sellname TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS latest (
    vin TEXT, endpoint TEXT, fetched_at TEXT, vehicle_ts TEXT, payload TEXT,
    error_code TEXT, error_message TEXT, error_at TEXT,
    PRIMARY KEY (vin, endpoint)
);
CREATE TABLE IF NOT EXISTS locations (
    vin TEXT, ts TEXT, lat REAL, lon REAL, altitude REAL, heading REAL, speed_kph REAL,
    PRIMARY KEY (vin, ts)
);
CREATE TABLE IF NOT EXISTS battery_history (
    vin TEXT, ts TEXT, soc REAL, plugged_in INTEGER, charging INTEGER, status TEXT,
    remain_min INTEGER, fuel_level REAL, PRIMARY KEY (vin, ts)
);
CREATE TABLE IF NOT EXISTS charging_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT, vin TEXT, start_ts TEXT, end_ts TEXT,
    start_soc REAL, end_soc REAL, kind TEXT, open INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS trips (
    vin TEXT, start_time TEXT, length_ms INTEGER, summary TEXT, updated_at TEXT,
    PRIMARY KEY (vin, start_time)
);
CREATE TABLE IF NOT EXISTS trip_data (
    vin TEXT, start_time TEXT, kind TEXT, payload TEXT,
    PRIMARY KEY (vin, start_time, kind)
);
CREATE TABLE IF NOT EXISTS api_usage (
    day TEXT, endpoint TEXT, calls INTEGER DEFAULT 0, errors INTEGER DEFAULT 0,
    rate_limited INTEGER DEFAULT 0, PRIMARY KEY (day, endpoint)
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def iso_ago(**delta: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(**delta)).strftime("%Y-%m-%dT%H:%M:%SZ")


class Storage:
    """Thin synchronous wrapper; every query is small, so calls are made inline."""

    def __init__(self, path: Path):
        self._lock = threading.Lock()
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript(SCHEMA)
        self._db.commit()

    def _exec(self, sql: str, params: tuple | dict = ()) -> None:
        with self._lock:
            self._db.execute(sql, params)
            self._db.commit()

    def _all(self, sql: str, params: tuple | dict = ()) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(r) for r in self._db.execute(sql, params).fetchall()]

    def _one(self, sql: str, params: tuple | dict = ()) -> dict[str, Any] | None:
        rows = self._all(sql, params)
        return rows[0] if rows else None

    # ---- meta -------------------------------------------------------------

    def get_meta(self, key: str) -> str | None:
        row = self._one("SELECT value FROM meta WHERE key = ?", (key,))
        return row["value"] if row else None

    def set_meta(self, key: str, value: str) -> None:
        self._exec("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, value))

    # ---- vehicles ---------------------------------------------------------

    def upsert_vehicle(self, v: dict[str, Any]) -> None:
        self._exec(
            "INSERT OR REPLACE INTO vehicles (vin, nickname, name, type, sellname, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (v["vin"], v.get("nickname"), v.get("name"), v.get("type"), v.get("sellname"), utcnow()),
        )

    def vehicles(self) -> list[dict[str, Any]]:
        return self._all("SELECT * FROM vehicles ORDER BY vin")

    # ---- latest status ----------------------------------------------------

    def save_latest(self, vin: str, endpoint: str, payload: dict[str, Any]) -> bool:
        """Store a successful payload. Returns True when the vehicle timestamp is new."""
        prev = self._one("SELECT vehicle_ts FROM latest WHERE vin = ? AND endpoint = ?", (vin, endpoint))
        ts = payload.get("timestamp")
        self._exec(
            "INSERT OR REPLACE INTO latest (vin, endpoint, fetched_at, vehicle_ts, payload, error_code, error_message, error_at) "
            "VALUES (?, ?, ?, ?, ?, NULL, NULL, NULL)",
            (vin, endpoint, utcnow(), ts, json.dumps(payload)),
        )
        return prev is None or prev["vehicle_ts"] != ts

    def save_error(self, vin: str, endpoint: str, code: str, message: str) -> None:
        self._exec(
            "INSERT INTO latest (vin, endpoint, error_code, error_message, error_at) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT (vin, endpoint) DO UPDATE SET error_code = excluded.error_code, "
            "error_message = excluded.error_message, error_at = excluded.error_at",
            (vin, endpoint, code, message, utcnow()),
        )

    def save_history_status(
        self, vin: str, kind: str, date_range: str, trips: int | None, code: str | None = None, message: str | None = None
    ) -> None:
        """Record the outcome of a history request so it shows on the Data & API page."""
        now = utcnow()
        if code is None:
            self._exec(
                "INSERT OR REPLACE INTO latest (vin, endpoint, fetched_at, vehicle_ts, payload, error_code, error_message, error_at) "
                "VALUES (?, ?, ?, NULL, ?, NULL, NULL, NULL)",
                (vin, kind, now, json.dumps({"range": date_range, "trips_returned": trips})),
            )
        else:
            self.save_error(vin, kind, code, f"{message} ({date_range})")

    def latest(self, vin: str) -> dict[str, dict[str, Any]]:
        rows = self._all("SELECT * FROM latest WHERE vin = ?", (vin,))
        out = {}
        for r in rows:
            r["payload"] = json.loads(r["payload"]) if r["payload"] else None
            out[r["endpoint"]] = r
        return out

    # ---- location & battery history --------------------------------------

    def add_location(self, vin: str, ts: str, state: dict[str, Any]) -> None:
        self._exec(
            "INSERT OR IGNORE INTO locations (vin, ts, lat, lon, altitude, heading, speed_kph) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (vin, ts, state["latitude"], state["longitude"], state.get("altitude"), state.get("heading"), state.get("speed_kph")),
        )

    def locations(self, vin: str, since: str, until: str | None = None) -> list[dict[str, Any]]:
        return self._all(
            "SELECT ts, lat, lon, speed_kph, heading FROM locations WHERE vin = ? AND ts >= ? AND ts <= ? ORDER BY ts",
            (vin, since, until or "9999"),
        )

    def add_battery_point(self, vin: str, ts: str, state: dict[str, Any]) -> None:
        self._exec(
            "INSERT OR IGNORE INTO battery_history (vin, ts, soc, plugged_in, charging, status, remain_min, fuel_level) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                vin, ts, state.get("battery_soc"), state.get("plugged_in"), state.get("charging"),
                state.get("charge_status"), state.get("charge_remaining_min"), state.get("fuel_level"),
            ),
        )

    def battery_history(self, vin: str, since: str) -> list[dict[str, Any]]:
        return self._all(
            "SELECT ts, soc, plugged_in, charging, status, fuel_level FROM battery_history WHERE vin = ? AND ts >= ? ORDER BY ts",
            (vin, since),
        )

    # ---- charging sessions -----------------------------------------------

    def track_charging(self, vin: str, ts: str, charging: bool | None, soc: float | None, status: str | None) -> None:
        """Open a session when charging starts, close it when it stops."""
        if charging is None:
            return
        open_session = self._one("SELECT * FROM charging_sessions WHERE vin = ? AND open = 1", (vin,))
        kind = "dc" if status == "fastCharging" else "ac"
        if charging and not open_session:
            self._exec(
                "INSERT INTO charging_sessions (vin, start_ts, end_ts, start_soc, end_soc, kind, open) VALUES (?, ?, ?, ?, ?, ?, 1)",
                (vin, ts, ts, soc, soc, kind),
            )
        elif open_session:
            # A DC phase anywhere in the session marks the whole session as DC
            kind = "dc" if open_session["kind"] == "dc" else kind
            self._exec(
                "UPDATE charging_sessions SET end_ts = ?, end_soc = COALESCE(?, end_soc), kind = ?, open = ? WHERE id = ?",
                (ts, soc, kind, 1 if charging else 0, open_session["id"]),
            )

    def charging_sessions(self, vin: str, since: str) -> list[dict[str, Any]]:
        return self._all(
            "SELECT id, start_ts, end_ts, start_soc, end_soc, kind, open FROM charging_sessions "
            "WHERE vin = ? AND start_ts >= ? ORDER BY start_ts DESC",
            (vin, since),
        )

    # ---- trips ------------------------------------------------------------

    def save_trip_part(self, vin: str, start_time: str, kind: str, length_ms: int | None, trip: dict[str, Any]) -> None:
        with self._lock:
            self._db.execute(
                "INSERT OR REPLACE INTO trip_data (vin, start_time, kind, payload) VALUES (?, ?, ?, ?)",
                (vin, start_time, kind, json.dumps(trip)),
            )
            self._db.execute(
                "INSERT INTO trips (vin, start_time, length_ms, updated_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT (vin, start_time) DO UPDATE SET length_ms = MAX(COALESCE(length_ms, 0), excluded.length_ms), "
                "updated_at = excluded.updated_at",
                (vin, start_time, length_ms, utcnow()),
            )
            self._db.commit()

    def trip_parts(self, vin: str, start_time: str) -> tuple[int | None, dict[str, dict[str, Any]]]:
        trip = self._one("SELECT length_ms FROM trips WHERE vin = ? AND start_time = ?", (vin, start_time))
        rows = self._all("SELECT kind, payload FROM trip_data WHERE vin = ? AND start_time = ?", (vin, start_time))
        return (trip or {}).get("length_ms"), {r["kind"]: json.loads(r["payload"]) for r in rows}

    def set_trip_summary(self, vin: str, start_time: str, summary: dict[str, Any]) -> None:
        self._exec("UPDATE trips SET summary = ? WHERE vin = ? AND start_time = ?", (json.dumps(summary), vin, start_time))

    def trips(self, vin: str, since: str) -> list[dict[str, Any]]:
        rows = self._all(
            "SELECT start_time, length_ms, summary FROM trips WHERE vin = ? AND start_time >= ? ORDER BY start_time DESC",
            (vin, since),
        )
        return [json.loads(r["summary"]) if r["summary"] else {"start_time": r["start_time"]} for r in rows]

    # ---- API usage --------------------------------------------------------

    def record_call(self, endpoint: str, ok: bool, http_status: int) -> None:
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self._exec(
            "INSERT INTO api_usage (day, endpoint, calls, errors, rate_limited) VALUES (?, ?, 1, ?, ?) "
            "ON CONFLICT (day, endpoint) DO UPDATE SET calls = calls + 1, errors = errors + excluded.errors, "
            "rate_limited = rate_limited + excluded.rate_limited",
            (day, endpoint, 0 if ok else 1, 1 if http_status == 429 else 0),
        )

    def usage(self, days: int = 14) -> list[dict[str, Any]]:
        since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
        return self._all("SELECT * FROM api_usage WHERE day >= ? ORDER BY day DESC, endpoint", (since,))

    def calls_today(self) -> int:
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        row = self._one("SELECT COALESCE(SUM(calls), 0) AS n FROM api_usage WHERE day = ?", (day,))
        return int(row["n"]) if row else 0

    def prune(self, keep_days: int = 400) -> None:
        cutoff = iso_ago(days=keep_days)
        for table in ("locations", "battery_history"):
            self._exec(f"DELETE FROM {table} WHERE ts < ?", (cutoff,))

"""Add-on settings.

Inside Home Assistant the Supervisor writes the add-on options to
/data/options.json. For local development the same keys can be supplied as
environment variables (PLEOS_CLIENT_ID, PLEOS_POLL_INTERVAL, ...).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, fields
from pathlib import Path

OPTIONS_FILE = Path("/data/options.json")


@dataclass
class Settings:
    brand: str = "kia"
    client_id: str = ""
    client_secret: str = ""
    poll_interval: int = 60  # seconds between live status polls
    history_sync_interval: int = 30  # minutes between trip history syncs
    history_backfill_days: int = 7  # the API returns at most 7 days per call
    language: str = "en"
    mqtt_enabled: bool = True
    mqtt_discovery_prefix: str = "homeassistant"
    mqtt_host: str | None = None
    mqtt_port: int | None = None
    mqtt_username: str | None = None
    mqtt_password: str | None = None
    api_base: str = "https://api.pleos.ai"
    data_dir: str = "/data"
    timezone: str = "UTC"
    mock: bool = False  # serve simulated vehicle data instead of calling Pleos

    @property
    def db_path(self) -> Path:
        return Path(self.data_dir) / "pleos.db"


def _coerce(value: str, target: type | str):
    kind = target if isinstance(target, str) else target.__name__
    if "bool" in kind:
        return value.lower() in ("1", "true", "yes", "on")
    if "int" in kind:
        return int(value)
    return value


def load_settings() -> Settings:
    settings = Settings()
    if OPTIONS_FILE.exists():
        options = json.loads(OPTIONS_FILE.read_text(encoding="utf-8"))
        for f in fields(Settings):
            if options.get(f.name) not in (None, ""):
                setattr(settings, f.name, options[f.name])
    else:
        settings.data_dir = os.environ.get("PLEOS_DATA_DIR", "./dev-data")

    # Environment variables override options (useful for local development)
    for f in fields(Settings):
        env = os.environ.get(f"PLEOS_{f.name.upper()}")
        if env not in (None, ""):
            setattr(settings, f.name, _coerce(env, f.type))

    settings.timezone = os.environ.get("TZ") or settings.timezone
    Path(settings.data_dir).mkdir(parents=True, exist_ok=True)
    return settings

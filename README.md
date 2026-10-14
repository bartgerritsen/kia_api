# Pleos Vehicle: Home Assistant add-on

Home Assistant add-on repository with one add-on, **Pleos Vehicle**. It shows all data from
the [Pleos Vehicle Data API](https://document.pleos.ai/en/api-reference/vehicle-data-api/intro)
(Kia / Hyundai / Genesis, Europe) in a sidebar panel and as MQTT entities.

User documentation: [pleos_vehicle/DOCS.md](pleos_vehicle/DOCS.md).

## Install

1. Push this repository to GitHub and replace `YOUR_GITHUB_USER` in
   [repository.yaml](repository.yaml) and [pleos_vehicle/config.yaml](pleos_vehicle/config.yaml).
   A private repo needs a URL that includes an access token; a public repo is simpler.
2. In Home Assistant: **Settings → Add-ons → Add-on Store → ⋮ → Repositories**, add the
   repository URL.
3. Install **Pleos Vehicle** (the first build compiles the frontend on your HA host and takes
   a few minutes), fill in the configuration and start it.

To release an update, bump `version` in `pleos_vehicle/config.yaml` and push. HA will
offer the update.

## Layout

```
repository.yaml              HA add-on repository manifest
pleos_vehicle/
  config.yaml, build.yaml    add-on manifest and base images
  Dockerfile, run.sh         multi-stage build: Node builds the UI, Python serves it
  backend/app/
    pleos.py                 API client (token handling, error mapping)
    poller.py                live polling, history sync, backoff
    normalize.py             raw payloads -> unit-normalised state
    trips.py                 trip summaries and telemetry series
    storage.py               SQLite in /data
    mqtt.py                  MQTT discovery publisher
    mock.py                  simulated API for development
    main.py                  FastAPI routes + static UI
  frontend/                  React + Vite + Recharts + Leaflet
```

## Local development

Backend (simulated car, no credentials needed):

```bash
cd pleos_vehicle/backend
python -m venv .venv && .venv/Scripts/pip install -r requirements-dev.txt   # bin/ on Linux/macOS
PLEOS_MOCK=1 PLEOS_MQTT_ENABLED=0 .venv/Scripts/python -m uvicorn app.main:app --port 8099
.venv/Scripts/python -m pytest
```

Against the real API, set `PLEOS_CLIENT_ID`, `PLEOS_CLIENT_SECRET` and `PLEOS_BRAND`
instead of `PLEOS_MOCK`. Any option from `config.yaml` can be set as `PLEOS_<OPTION>`.

Frontend (proxies `/api` to port 8099):

```bash
cd pleos_vehicle/frontend
npm install
npm run dev
```

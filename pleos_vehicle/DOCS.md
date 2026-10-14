# Pleos Vehicle

Shows everything the [Pleos Vehicle Data API](https://document.pleos.ai/en/api-reference/vehicle-data-api/intro)
knows about your Kia, Hyundai or Genesis, as a panel in the Home Assistant sidebar and as
MQTT entities you can use in automations.

## Setup

1. Sign in to [Pleos Playground](https://pleos.ai/playground), open **My Vehicle Data API**
   (account menu, top right), choose your brand's tab and click **Get API Key**.
   Copy the **Client ID** and **Client Secret**.
2. For the MQTT entities: install the **Mosquitto broker** add-on and the **MQTT**
   integration. The add-on finds the broker by itself.
3. In this add-on's **Configuration** tab enter `brand`, `client_id` and `client_secret`,
   then start the add-on. Open **My Car** in the sidebar.

## Options

| Option | Default | Description |
| --- | --- | --- |
| `brand` | `kia` | `kia`, `hyundai` or `genesis`. Pleos issues one key per brand. |
| `client_id` / `client_secret` | | Your My Vehicle API key. |
| `poll_interval` | `60` | Seconds between live status polls (30–3600). |
| `history_sync_interval` | `30` | Minutes between trip history syncs (5–1440). |
| `language` | `en` | Default dashboard language (`en` or `nl`). Each viewer can switch in the top bar. |
| `mqtt_enabled` | `true` | Publish MQTT discovery entities. |
| `mqtt_discovery_prefix` | `homeassistant` | Only change if you changed it in the MQTT integration. |
| `mqtt_host`, `mqtt_port`, `mqtt_username`, `mqtt_password` | | Optional: use an external broker instead of the Mosquitto add-on. |

## Rate limits

Pleos does **not** document any rate limit, daily quota or token lifetime (checked
October 2026: the error code tables contain no 429 or quota error). So the add-on:

- counts every API call per endpoint per day (**Data & API** tab and the
  `API calls today` diagnostic sensor);
- backs off exponentially on HTTP 429 or 5xx, and honours `Retry-After` when sent;
- polls endpoints that keep returning no data (for example the freezer on a car without
  one) only once an hour;
- requests a new access token only when the API reports it as expired or invalid.

At the default 60 s interval one car uses about 5–6 calls a minute, so roughly
7,500–8,700 calls a day, plus about 200 for trip history. If you see 429s on the
Data & API tab, raise `poll_interval`.

Polling never wakes the car: every endpoint returns the last data the car sent
(see "Car data from …" in the top bar). Polling faster than the car reports just
returns the same data again.

## What you get

- **Overview**: battery and fuel level with ranges, charging state and limits, doors and
  locks, tyre pressures, warning lights, climate and seat heating, odometer, location.
- **Map**: current position and the track recorded from live polls (24 h / 7 days).
- **Trips**: every trip from the history endpoints, stored locally so you keep more
  than the API's 7-day window. Each trip has speed, engine rpm, oil temperature,
  HV battery voltage, acceleration, steering, yaw, gear, wheel speeds, tyre pressure
  and outside temperature charts, plus "engine on %" (how much of the trip ran on fuel).
- **Charging**: sessions detected from the live charging status (start/end SoC, AC/DC)
  and a battery/fuel level chart.
- **Data & API**: API health, call counts, per-endpoint freshness and raw responses.

### MQTT entities

One device per vehicle, with sensors for battery, fuel, ranges, odometer, charge status,
charge time remaining, charge limits, speed, outside and climate temperature, four tyre
pressures, warnings (with the list as an attribute) and last update; binary sensors for
plugged in, charging, ignition, in park, doors locked, doors / hood / trunk / sunroof
open, climate, defrost, steering wheel heater and API connectivity; and a
`device_tracker` for the location. An entity is only created once the car has reported
a value for it.

## Limitations

- The API is **read-only**: there are no lock, climate or charge commands.
- Europe only (Pleos restriction).
- Vehicles added to your Kia account after the key was issued are not visible:
  revoke and reissue the key in Pleos Playground.
- Trip routes come from the add-on's own location polls, so trips from before the
  add-on was running have charts but no map.
- Charging sessions are only detected while the add-on is running.
- Trip ("basic") data may appear up to 24 hours late.

## Data

Everything is stored in SQLite at `/data/pleos.db` inside the add-on and is kept
across updates. Location and battery history older than 400 days is pruned.

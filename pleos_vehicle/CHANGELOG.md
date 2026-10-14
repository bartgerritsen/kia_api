# Changelog

## 0.1.2

- HTTP 403 from Pleos now pauses all polling (15 min, doubling up to 6 h) instead of retrying every endpoint each minute, and is shown as an error. 403s are counted with 429s on the Data & API page.

## 0.1.1

- Map: tile.openstreetmap.org blocked tiles because the Ingress panel sends no Referer; tiles now send the page origin. Optional `map_tile_url` / `map_tile_attribution` options for another tile server. Dark mode darkens the map.
- Trip history: a rejected 7-day request is retried one day at a time, failures are shown on the Data & API page, and a failed backfill is retried (also re-runs the backfill once after updating).
- Overview hides values the car doesn't report instead of showing "–", and shows the range card even when the fuel level is missing.
- New "Download diagnostics" button on the Data & API page.

## 0.1.0

- First release: overview, map, trips with telemetry charts, charging log, API usage page.
- MQTT discovery sensors, binary sensors and device tracker.
- English and Dutch UI.

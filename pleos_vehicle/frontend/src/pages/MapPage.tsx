import { useState } from "react";
import { api, type VehicleState } from "../api";
import { MapView } from "../components/MapView";
import { useI18n } from "../i18n";
import { fmtAgo, fmtDateTime, fmtNum, usePolling } from "../util";

export function MapPage({ vin, state }: { vin: string; state: VehicleState }) {
  const { t, lang } = useI18n();
  const [hours, setHours] = useState(24);
  const { data: points } = usePolling(() => api.locations(vin, hours), [vin, hours], 60000);

  const position: [number, number] | null =
    state.latitude !== undefined && state.latitude !== null ? [state.latitude, state.longitude!] : null;
  const track = (points ?? []).map((p) => [p.lat, p.lon] as [number, number]);
  const last = points?.[points.length - 1];

  return (
    <div className="stack">
      <div className="card">
        <div className="row" style={{ marginBottom: 12 }}>
          <h2 style={{ margin: 0 }}>{t("map.track")}</h2>
          <div className="seg">
            <button className={hours === 24 ? "active" : ""} onClick={() => setHours(24)}>
              {t("map.last24h")}
            </button>
            <button className={hours === 168 ? "active" : ""} onClick={() => setHours(168)}>
              {t("map.last7d")}
            </button>
          </div>
          <span className="spacer" />
          <span className="small muted">
            {fmtNum(points?.length ?? 0, lang)} {t("map.points")}
          </span>
        </div>
        {position || track.length ? (
          <MapView position={position} track={track} label={fmtDateTime(last?.ts, lang)} />
        ) : (
          <p className="muted">{t("map.noLocation")}</p>
        )}
      </div>
      {position && (
        <div className="card">
          <dl className="kv">
            <dt>{t("ov.location")}</dt>
            <dd>
              {fmtNum(position[0], lang, 5)}, {fmtNum(position[1], lang, 5)}
            </dd>
            <dt>{t("ov.speed")}</dt>
            <dd>{fmtNum(state.speed_kph, lang)} km/h</dd>
            <dt>{t("common.updated")}</dt>
            <dd>{fmtAgo(last?.ts ?? state.last_vehicle_update, lang)}</dd>
          </dl>
          <p className="small" style={{ marginBottom: 0 }}>
            <a
              href={`https://www.openstreetmap.org/?mlat=${position[0]}&mlon=${position[1]}#map=16/${position[0]}/${position[1]}`}
              target="_blank"
              rel="noreferrer"
            >
              {t("map.openOsm")} ↗
            </a>
          </p>
        </div>
      )}
    </div>
  );
}

import { useMemo, useState } from "react";
import { api, type Frame, type TripSummary } from "../api";
import { SERIES_COLORS, TimeChart, type Series } from "../components/Chart";
import { MapView } from "../components/MapView";
import { useI18n } from "../i18n";
import { fmtDate, fmtDateTime, fmtDuration, fmtNum, fmtTime, usePolling } from "../util";

const PERIODS = [7, 30, 90, 365];

export function Trips({ vin, onOpen }: { vin: string; onOpen: (start: string) => void }) {
  const { t, lang } = useI18n();
  const [days, setDays] = useState(30);
  const [syncing, setSyncing] = useState(false);
  const { data: trips, reload } = usePolling(() => api.trips(vin, days), [vin, days], 120000);

  const totals = useMemo(() => {
    const list = trips ?? [];
    const km = list.reduce((sum, tr) => sum + (tr.distance_km ?? 0), 0);
    const minutes = list.reduce((sum, tr) => sum + (tr.duration_min ?? 0), 0);
    const withEngine = list.filter((tr) => tr.engine_on_pct !== undefined && tr.duration_min);
    const engineMin = withEngine.reduce((sum, tr) => sum + ((tr.engine_on_pct ?? 0) / 100) * (tr.duration_min ?? 0), 0);
    const engineBase = withEngine.reduce((sum, tr) => sum + (tr.duration_min ?? 0), 0);
    return { count: list.length, km, minutes, enginePct: engineBase ? (100 * engineMin) / engineBase : null };
  }, [trips]);

  const sync = async () => {
    setSyncing(true);
    await api.syncHistory();
    window.setTimeout(() => {
      reload();
      setSyncing(false);
    }, 8000);
  };

  return (
    <div className="stack">
      <div className="row">
        <span className="muted">{t("trips.period")}</span>
        <div className="seg">
          {PERIODS.map((d) => (
            <button key={d} className={d === days ? "active" : ""} onClick={() => setDays(d)}>
              {d} {t("common.days")}
            </button>
          ))}
        </div>
        <span className="spacer" />
        <button className="btn" onClick={sync} disabled={syncing}>
          {syncing ? t("common.loading") : t("trips.sync")}
        </button>
      </div>

      <div className="card">
        <div className="stat-row">
          <div className="stat">
            <div className="label">{t("trips.count")}</div>
            <div className="value">{fmtNum(totals.count, lang)}</div>
          </div>
          <div className="stat">
            <div className="label">{t("trips.distance")}</div>
            <div className="value">{fmtNum(totals.km, lang)} km</div>
          </div>
          <div className="stat">
            <div className="label">{t("trips.duration")}</div>
            <div className="value">{fmtDuration(totals.minutes)}</div>
          </div>
          {totals.enginePct !== null && (
            <div className="stat" title={t("trips.engineShareNote")}>
              <div className="label">{t("trips.engine")}</div>
              <div className="value">{fmtNum(totals.enginePct, lang)}%</div>
            </div>
          )}
        </div>
      </div>

      <div className="card">
        {!trips ? (
          <p className="muted">{t("common.loading")}</p>
        ) : trips.length === 0 ? (
          <p className="muted">{t("trips.none")}</p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>{t("trips.date")}</th>
                  <th>{t("trips.time")}</th>
                  <th className="num">{t("trips.duration")}</th>
                  <th className="num">{t("trips.distance")}</th>
                  <th className="num">{t("trips.avgSpeed")}</th>
                  <th className="num">{t("trips.maxSpeed")}</th>
                  <th className="num" title={t("trips.engineShareNote")}>
                    {t("trips.engine")}
                  </th>
                  <th className="num">{t("trips.temp")}</th>
                </tr>
              </thead>
              <tbody>
                {trips.map((tr) => (
                  <tr key={tr.start_time} className="clickable" onClick={() => onOpen(tr.start_time)}>
                    <td>{fmtDate(tr.start_time, lang)}</td>
                    <td>
                      {fmtTime(tr.start_time, lang)}–{fmtTime(tr.end_time, lang)}
                    </td>
                    <td className="num">{fmtDuration(tr.duration_min)}</td>
                    <td className="num">{fmtNum(tr.distance_km, lang, 1)} km</td>
                    <td className="num">{fmtNum(tr.avg_moving_speed, lang)} km/h</td>
                    <td className="num">{fmtNum(tr.max_speed, lang)} km/h</td>
                    <td className="num">{tr.engine_on_pct !== undefined ? `${fmtNum(tr.engine_on_pct, lang)}%` : "–"}</td>
                    <td className="num">{tr.outside_temp !== undefined ? `${fmtNum(tr.outside_temp, lang, 1)} °C` : "–"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

// ---- trip detail ----------------------------------------------------------------

const GEAR_INDEX: Record<string, number> = { p: 0, r: 1, n: 2, d: 3 };
const GEAR_LABEL = ["P", "R", "N", "D"];

function rows(frame: Frame, keys: string[], map?: (v: number | string | null) => number | null) {
  return frame.t.map((x, i) => {
    const row: Record<string, number | null> = { x };
    for (const k of keys) {
      const v = frame.series[k]?.[i] ?? null;
      row[k] = map ? map(v) : typeof v === "number" ? v : null;
    }
    return row;
  });
}

export function TripDetail({ vin, start, onBack }: { vin: string; start: string; onBack: () => void }) {
  const { t, lang } = useI18n();
  const { data, error } = usePolling(() => api.trip(vin, start), [vin, start], 0);

  const fmtX = (s: number) => {
    const m = Math.floor(s / 60);
    return `${m}:${Math.floor(s % 60)
      .toString()
      .padStart(2, "0")}`;
  };
  const xLabel = t("trips.timeAxis");

  if (error) return <div className="banner error">{error}</div>;
  if (!data) return <p className="muted">{t("common.loading")}</p>;

  const { summary: s, frames, route } = data;
  const charts: JSX.Element[] = [];
  const chart = (title: string, frame: Frame | undefined, series: Series[], unit: string, opts: Partial<Parameters<typeof TimeChart>[0]> = {}) => {
    if (!frame) return;
    const keys = series.map((x) => x.key).filter((k) => frame.series[k]);
    if (!keys.length) return;
    charts.push(
      <TimeChart
        key={title}
        title={title}
        subtitle={xLabel}
        data={rows(frame, keys)}
        series={series.filter((x) => keys.includes(x.key))}
        unit={unit}
        xFormat={fmtX}
        yFormat={(y) => fmtNum(y, lang, 1)}
        {...opts}
      />,
    );
  };

  chart(t("trips.speed"), frames.speed, [{ key: "speed", label: t("trips.speed"), color: SERIES_COLORS[0] }], "km/h");
  chart(t("trips.rpm"), frames.powertrain_data, [{ key: "rpm", label: t("trips.rpm"), color: SERIES_COLORS[0] }], "rpm", {
    yFormat: (y) => fmtNum(y, lang),
  });
  chart(t("trips.oilTemp"), frames.powertrain_data, [{ key: "oil_temp", label: t("trips.oilTemp"), color: SERIES_COLORS[0] }], "°C");
  chart(t("trips.hvVoltage"), frames.powertrain_data, [{ key: "hv_voltage", label: t("trips.hvVoltage"), color: SERIES_COLORS[0] }], "V");
  chart(t("trips.accel"), frames.driving_data, [{ key: "accel_long", label: t("trips.accel"), color: SERIES_COLORS[0] }], "g", {
    yFormat: (y) => fmtNum(y, lang, 2),
  });
  chart(t("trips.steering"), frames.driving_data, [{ key: "steering_angle", label: t("trips.steering"), color: SERIES_COLORS[0] }], "°");
  chart(t("trips.yaw"), frames.driving_data, [{ key: "yaw", label: t("trips.yaw"), color: SERIES_COLORS[0] }], "°/s");

  if (frames.driving_data?.series.gear) {
    charts.push(
      <TimeChart
        key="gear"
        title={t("trips.gear")}
        subtitle={xLabel}
        data={rows(frames.driving_data, ["gear"], (v) => (typeof v === "string" && v in GEAR_INDEX ? GEAR_INDEX[v] : null))}
        series={[{ key: "gear", label: t("trips.gear"), color: SERIES_COLORS[0] }]}
        xFormat={fmtX}
        yFormat={(y) => GEAR_LABEL[y] ?? ""}
        yTicks={[0, 1, 2, 3]}
        yDomain={[0, 3]}
        step
        height={160}
      />,
    );
  }

  chart(
    t("trips.wheelSpeed"),
    frames.speed,
    [
      { key: "wheel_front_left", label: t("ov.frontLeft"), color: SERIES_COLORS[0] },
      { key: "wheel_front_right", label: t("ov.frontRight"), color: SERIES_COLORS[1] },
      { key: "wheel_rear_left", label: t("ov.rearLeft"), color: SERIES_COLORS[2] },
      { key: "wheel_rear_right", label: t("ov.rearRight"), color: SERIES_COLORS[3] },
    ],
    "km/h",
  );
  chart(
    t("trips.tyres"),
    frames.status_data,
    [
      { key: "tire_front_left", label: t("ov.frontLeft"), color: SERIES_COLORS[0] },
      { key: "tire_front_right", label: t("ov.frontRight"), color: SERIES_COLORS[1] },
      { key: "tire_rear_left", label: t("ov.rearLeft"), color: SERIES_COLORS[2] },
      { key: "tire_rear_right", label: t("ov.rearRight"), color: SERIES_COLORS[3] },
    ],
    "bar",
    { yFormat: (y) => fmtNum(y, lang, 2) },
  );
  chart(t("trips.outsideTemp"), frames.status_data, [{ key: "outside_temp", label: t("trips.outsideTemp"), color: SERIES_COLORS[0] }], "°C");

  const track = route.map((p) => [p.lat, p.lon] as [number, number]);

  return (
    <div className="stack">
      <div className="row">
        <button className="btn" onClick={onBack}>
          ← {t("common.back")}
        </button>
        <h2 style={{ margin: 0 }}>{fmtDateTime(s.start_time, lang, { dateStyle: "full", timeStyle: "short" })}</h2>
      </div>
      <div className="card">
        <TripStats s={s} />
      </div>
      <div className="card">
        <h2>{t("trips.route")}</h2>
        {track.length > 1 ? <MapView track={track} position={track[track.length - 1]} /> : <p className="muted small">{t("trips.noRoute")}</p>}
      </div>
      <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(min(380px, 100%), 1fr))" }}>
        {charts}
      </div>
    </div>
  );
}

function TripStats({ s }: { s: TripSummary }) {
  const { t, lang } = useI18n();
  const items: [string, string][] = [
    [t("trips.duration"), fmtDuration(s.duration_min)],
    [t("trips.distance"), `${fmtNum(s.distance_km, lang, 1)} km`],
    [t("trips.avgSpeed"), `${fmtNum(s.avg_moving_speed, lang)} km/h`],
    [t("trips.maxSpeed"), `${fmtNum(s.max_speed, lang)} km/h`],
  ];
  if (s.engine_on_pct !== undefined) items.push([t("trips.engine"), `${fmtNum(s.engine_on_pct, lang)}%`]);
  if (s.outside_temp !== undefined) items.push([t("trips.temp"), `${fmtNum(s.outside_temp, lang, 1)} °C`]);
  if (s.end_odometer !== undefined) items.push([t("ov.odometer"), `${fmtNum(s.end_odometer, lang)} km`]);
  return (
    <div className="stat-row">
      {items.map(([label, value]) => (
        <div className="stat" key={label}>
          <div className="label">{label}</div>
          <div className="value">{value}</div>
        </div>
      ))}
    </div>
  );
}

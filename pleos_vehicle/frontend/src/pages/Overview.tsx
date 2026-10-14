import type { EndpointInfo, Vehicle, VehicleState } from "../api";
import { StatusLine } from "../components/Icons";
import { MapView } from "../components/MapView";
import { useI18n, type T } from "../i18n";
import { fmtAgo, fmtDuration, fmtNum } from "../util";

interface Props {
  vehicle: Vehicle;
  state: VehicleState;
  endpoints: Record<string, EndpointInfo>;
  onNavigate: (path: string) => void;
}

const has = (v: unknown): boolean => v !== null && v !== undefined;

function onOff(t: T, v: boolean | null | undefined) {
  return v === null || v === undefined ? "–" : v ? t("common.on") : t("common.off");
}

function Meter({ value, target }: { value?: number | null; target?: number | null }) {
  return (
    <div className="meter" role="presentation">
      <span style={{ width: `${Math.max(0, Math.min(100, value ?? 0))}%` }} />
      {has(target) && <i style={{ left: `calc(${target}% - 1px)` }} />}
    </div>
  );
}

function door(t: T, v?: string | null) {
  if (!v) return "–";
  return v === "locked" ? t("common.locked") : v === "open" ? t("common.open") : t("common.closed");
}

export function Overview({ vehicle, state: s, endpoints, onNavigate }: Props) {
  const { t, lang } = useI18n();
  const n = (v: number | null | undefined, d = 0) => fmtNum(v, lang, d);
  const isElectrified = has(s.battery_soc);
  const hasFuel = has(s.fuel_level);
  const warnings = s.warnings ?? [];
  const seatLabels: [string, string][] = [
    ["front_left", t("ov.frontLeft")],
    ["front_right", t("ov.frontRight")],
    ["rear_left", t("ov.rearLeft")],
    ["rear_right", t("ov.rearRight")],
  ];
  const activeSeats = seatLabels.flatMap(([key, label]) => {
    const parts = [];
    const heat = s[`seat_${key}_heat`];
    const vent = s[`seat_${key}_ventilation`];
    if (heat && heat !== "off") parts.push(`${t("ov.seatHeat")} ${heat}`);
    if (vent && vent !== "off") parts.push(`${t("ov.seatVent")} ${vent}`);
    return parts.length ? [`${label}: ${parts.join(", ")}`] : [];
  });

  const position: [number, number] | null = has(s.latitude) ? [s.latitude!, s.longitude!] : null;
  const locationTs = endpoints.locations?.vehicle_ts;

  return (
    <div className="stack">
      <div className="grid hero">
        {isElectrified && (
          <div className="card">
            <h2>{t("ov.battery")}</h2>
            <div className="hero-value">
              {n(s.battery_soc)}
              <small>%</small>
            </div>
            <Meter value={s.battery_soc} target={s.charging ? s.target_soc_ac : null} />
            <dl className="kv">
              {has(s.range_ev) && (
                <>
                  <dt>{t("ov.evRange")}</dt>
                  <dd>{n(s.range_ev)} km</dd>
                </>
              )}
            </dl>
          </div>
        )}

        {hasFuel && (
          <div className="card">
            <h2>{t("ov.fuel")}</h2>
            <div className="hero-value">
              {n(s.fuel_level)}
              <small>%</small>
            </div>
            <Meter value={s.fuel_level} />
            <dl className="kv">
              {has(s.range_phev) && (
                <>
                  <dt>{t("ov.totalRange")}</dt>
                  <dd>{n(s.range_phev)} km</dd>
                </>
              )}
              {has(s.range_ice) && (
                <>
                  <dt>{t("ov.fuelRange")}</dt>
                  <dd>{n(s.range_ice)} km</dd>
                </>
              )}
              {has(s.range_hev) && (
                <>
                  <dt>{t("ov.totalRange")}</dt>
                  <dd>{n(s.range_hev)} km</dd>
                </>
              )}
            </dl>
          </div>
        )}

        {isElectrified && (
          <div className="card">
            <h2>{t("ov.charging")}</h2>
            <div className="stack" style={{ gap: 8 }}>
              <span className={`pill ${s.charging ? "good" : ""}`}>
                <span className="dot" />
                {s.charge_status ? t(`status.${s.charge_status}`) : t("common.unknown")}
              </span>
              <dl className="kv">
                <dt>{t("ov.plug")}</dt>
                <dd>{has(s.plugged_in) ? (s.plugged_in ? t("ov.plugged") : t("ov.unplugged")) : "–"}</dd>
                {s.charging && (
                  <>
                    <dt>{t("ov.timeLeft")}</dt>
                    <dd>{fmtDuration(s.charge_remaining_min)}</dd>
                  </>
                )}
                <dt>{t("ov.limitAc")}</dt>
                <dd>{n(s.target_soc_ac)}%</dd>
                <dt>{t("ov.limitDc")}</dt>
                <dd>{n(s.target_soc_dc)}%</dd>
              </dl>
            </div>
          </div>
        )}
      </div>

      <div className="grid">
        <div className="card">
          <h2>{t("ov.security")}</h2>
          <StatusLine level={s.locked ? "good" : has(s.locked) ? "warning" : "neutral"}>
            {s.locked ? t("ov.allLocked") : has(s.locked) ? t("ov.notLocked") : t("common.unknown")}
          </StatusLine>
          {s.doors_open && <StatusLine level="warning">{t("ov.doorsOpen")}</StatusLine>}
          <dl className="kv" style={{ marginTop: 10 }}>
            <dt>{t("ov.frontLeft")}</dt>
            <dd>{door(t, s.door_front_left)}</dd>
            <dt>{t("ov.frontRight")}</dt>
            <dd>{door(t, s.door_front_right)}</dd>
            <dt>{t("ov.rearLeft")}</dt>
            <dd>{door(t, s.door_rear_left)}</dd>
            <dt>{t("ov.rearRight")}</dt>
            <dd>{door(t, s.door_rear_right)}</dd>
            {(["hood", "trunk", "sunroof"] as const).map((part) =>
              has(s[`${part}_open`]) ? (
                <KV key={part} label={t(`ov.${part}`)} value={s[`${part}_open`] ? t("common.open") : t("common.closed")} />
              ) : null,
            )}
          </dl>
        </div>

        <div className="card">
          <h2>{t("ov.tyres")}</h2>
          <div className="car">
            <div className="cell">
              {t("ov.frontLeft")}
              <div className="v">{n(s.tire_front_left_bar, 1)} bar</div>
            </div>
            <div className="body">{vehicle.sellname}</div>
            <div className="cell right">
              {t("ov.frontRight")}
              <div className="v">{n(s.tire_front_right_bar, 1)} bar</div>
            </div>
            <div className="cell">
              {t("ov.rearLeft")}
              <div className="v">{n(s.tire_rear_left_bar, 1)} bar</div>
            </div>
            <div className="cell right">
              {t("ov.rearRight")}
              <div className="v">{n(s.tire_rear_right_bar, 1)} bar</div>
            </div>
          </div>
        </div>

        <div className="card">
          <h2>{t("ov.warnings")}</h2>
          {warnings.length === 0 ? (
            <StatusLine level={has(s.warning_count) ? "good" : "neutral"}>
              {has(s.warning_count) ? t("ov.noWarnings") : t("common.noData")}
            </StatusLine>
          ) : (
            warnings.map((w) => (
              <StatusLine key={w} level="warning">
                {t(`warn.${w}`)}
              </StatusLine>
            ))
          )}
        </div>

        <div className="card">
          <h2>{t("ov.driving")}</h2>
          <dl className="kv">
            <dt>{t("ov.odometer")}</dt>
            <dd>{n(s.odometer_km)} km</dd>
            <dt>{t("ov.ignition")}</dt>
            <dd>{onOff(t, s.ignition)}</dd>
            <dt>{t("ov.parked")}</dt>
            <dd>{has(s.parked) ? (s.parked ? t("common.yes") : t("common.no")) : "–"}</dd>
            <dt>{t("ov.sleep")}</dt>
            <dd>{onOff(t, s.sleep_mode)}</dd>
            <dt>{t("ov.speed")}</dt>
            <dd>{n(s.speed_kph)} km/h</dd>
            <dt>{t("ov.outside")}</dt>
            <dd>{n(s.outside_temp, 1)} °{s.outside_temp_unit ?? "C"}</dd>
          </dl>
        </div>

        <div className="card">
          <h2>{t("ov.climate")}</h2>
          <dl className="kv">
            <dt>{t("ov.climate")}</dt>
            <dd>
              {onOff(t, s.climate_on)}
              {s.climate_mode && s.climate_on ? ` (${s.climate_mode})` : ""}
            </dd>
            <dt>{t("ov.setTemp")}</dt>
            <dd>{n(s.climate_set_temp, 1)} °{s.climate_temp_unit ?? "C"}</dd>
            <dt>{t("ov.fan")}</dt>
            <dd>{s.climate_fan_speed === -1 ? t("ov.fanAuto") : n(s.climate_fan_speed)}</dd>
            <dt>{t("ov.defrost")}</dt>
            <dd>{onOff(t, s.defrost_on)}</dd>
            <dt>{t("ov.wheelHeat")}</dt>
            <dd>{onOff(t, s.steering_wheel_heat_on)}</dd>
          </dl>
          {activeSeats.length > 0 && (
            <p className="small muted" style={{ marginBottom: 0 }}>
              {t("ov.seats")}: {activeSeats.join(" · ")}
            </p>
          )}
        </div>

        {has(s.freezer_on) && (
          <div className="card">
            <h2>{t("ov.freezer")}</h2>
            <dl className="kv">
              <dt>{t("ov.freezer")}</dt>
              <dd>{onOff(t, s.freezer_on)}</dd>
              <dt>°C</dt>
              <dd>{n(s.freezer_temp, 1)}</dd>
            </dl>
          </div>
        )}

        <div className="card span-2">
          <div className="row" style={{ marginBottom: 8 }}>
            <h2 style={{ margin: 0 }}>{t("ov.location")}</h2>
            <span className="spacer" />
            <span className="small muted">{fmtAgo(locationTs, lang)}</span>
            <button className="btn" onClick={() => onNavigate("map")}>
              {t("nav.map")} →
            </button>
          </div>
          {position ? <MapView position={position} small /> : <p className="muted">{t("map.noLocation")}</p>}
        </div>
      </div>
    </div>
  );
}

function KV({ label, value }: { label: string; value: string }) {
  return (
    <>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </>
  );
}

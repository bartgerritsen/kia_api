import type { ReactNode } from "react";
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
  return v ? t("common.on") : t("common.off");
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
  return v === "locked" ? t("common.locked") : v === "open" ? t("common.open") : t("common.closed");
}

/** A label/value row that is left out entirely when the car doesn't report the value. */
function KV({ label, value, show }: { label: string; value: ReactNode; show: unknown }) {
  if (!has(show)) return null;
  return (
    <>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </>
  );
}

export function Overview({ vehicle, state: s, endpoints, onNavigate }: Props) {
  const { t, lang } = useI18n();
  const n = (v: number | null | undefined, d = 0) => fmtNum(v, lang, d);
  const isElectrified = has(s.battery_soc);
  const fuelRanges: [string, string][] = [
    ["range_phev", t("ov.totalRange")],
    ["range_hev", t("ov.totalRange")],
    ["range_ice", t("ov.fuelRange")],
  ];
  const presentFuelRanges = fuelRanges.filter(([key]) => has(s[key]));
  const showFuel = has(s.fuel_level) || presentFuelRanges.length > 0;
  const tyres = ["front_left", "front_right", "rear_left", "rear_right"].map((k) => s[`tire_${k}_bar`]);
  const doors = ["front_left", "front_right", "rear_left", "rear_right"].map((k) => s[`door_${k}`]);
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
  const tempUnit = (u?: string) => `°${u ?? "C"}`;

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
              <KV show={s.range_ev} label={t("ov.evRange")} value={`${n(s.range_ev)} km`} />
            </dl>
          </div>
        )}

        {showFuel && (
          <div className="card">
            <h2>{t("ov.fuel")}</h2>
            {has(s.fuel_level) ? (
              <>
                <div className="hero-value">
                  {n(s.fuel_level)}
                  <small>%</small>
                </div>
                <Meter value={s.fuel_level} />
              </>
            ) : (
              <div className="hero-value" style={{ marginBottom: 12 }}>
                {n(s[presentFuelRanges[0][0]])}
                <small>km</small>
              </div>
            )}
            <dl className="kv">
              {presentFuelRanges.map(([key, label]) => (
                <KV key={key} show={s[key]} label={label} value={`${n(s[key])} km`} />
              ))}
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
                <KV show={s.plugged_in} label={t("ov.plug")} value={s.plugged_in ? t("ov.plugged") : t("ov.unplugged")} />
                {s.charging && <KV show={s.charge_remaining_min} label={t("ov.timeLeft")} value={fmtDuration(s.charge_remaining_min)} />}
                <KV show={s.target_soc_ac} label={t("ov.limitAc")} value={`${n(s.target_soc_ac)}%`} />
                <KV show={s.target_soc_dc} label={t("ov.limitDc")} value={`${n(s.target_soc_dc)}%`} />
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
            {seatLabels.map(([key, label], i) => (
              <KV key={key} show={doors[i]} label={label} value={door(t, doors[i])} />
            ))}
            {(["hood", "trunk", "sunroof"] as const).map((part) => (
              <KV key={part} show={s[`${part}_open`]} label={t(`ov.${part}`)} value={s[`${part}_open`] ? t("common.open") : t("common.closed")} />
            ))}
          </dl>
        </div>

        {tyres.some(has) && (
          <div className="card">
            <h2>{t("ov.tyres")}</h2>
            <div className="car">
              {[0, 1].map((i) => (
                <div key={i} className={`cell${i % 2 ? " right" : ""}`} style={{ gridRow: 1, gridColumn: i ? 3 : 1 }}>
                  {seatLabels[i][1]}
                  <div className="v">{has(tyres[i]) ? `${n(tyres[i], 1)} bar` : "–"}</div>
                </div>
              ))}
              <div className="body">{vehicle.sellname}</div>
              {[2, 3].map((i) => (
                <div key={i} className={`cell${i % 2 ? " right" : ""}`} style={{ gridRow: 2, gridColumn: i === 3 ? 3 : 1 }}>
                  {seatLabels[i][1]}
                  <div className="v">{has(tyres[i]) ? `${n(tyres[i], 1)} bar` : "–"}</div>
                </div>
              ))}
            </div>
          </div>
        )}

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
            <KV show={s.odometer_km} label={t("ov.odometer")} value={`${n(s.odometer_km)} km`} />
            <KV show={s.ignition} label={t("ov.ignition")} value={onOff(t, s.ignition)} />
            <KV show={s.parked} label={t("ov.parked")} value={s.parked ? t("common.yes") : t("common.no")} />
            <KV show={s.sleep_mode} label={t("ov.sleep")} value={onOff(t, s.sleep_mode)} />
            <KV show={s.speed_kph} label={t("ov.speed")} value={`${n(s.speed_kph)} km/h`} />
            <KV show={s.outside_temp} label={t("ov.outside")} value={`${n(s.outside_temp, 1)} ${tempUnit(s.outside_temp_unit)}`} />
          </dl>
        </div>

        {(has(s.climate_on) || has(s.defrost_on) || has(s.steering_wheel_heat_on)) && (
          <div className="card">
            <h2>{t("ov.climate")}</h2>
            <dl className="kv">
              <KV
                show={s.climate_on}
                label={t("ov.climate")}
                value={`${onOff(t, s.climate_on)}${s.climate_mode && s.climate_on ? ` (${s.climate_mode})` : ""}`}
              />
              <KV show={s.climate_set_temp} label={t("ov.setTemp")} value={`${n(s.climate_set_temp, 1)} ${tempUnit(s.climate_temp_unit)}`} />
              {s.climate_on && (
                <KV show={s.climate_fan_speed} label={t("ov.fan")} value={s.climate_fan_speed === -1 ? t("ov.fanAuto") : n(s.climate_fan_speed)} />
              )}
              <KV show={s.defrost_on} label={t("ov.defrost")} value={onOff(t, s.defrost_on)} />
              <KV show={s.steering_wheel_heat_on} label={t("ov.wheelHeat")} value={onOff(t, s.steering_wheel_heat_on)} />
            </dl>
            {activeSeats.length > 0 && (
              <p className="small muted" style={{ marginBottom: 0 }}>
                {t("ov.seats")}: {activeSeats.join(" · ")}
              </p>
            )}
          </div>
        )}

        {has(s.freezer_on) && (
          <div className="card">
            <h2>{t("ov.freezer")}</h2>
            <dl className="kv">
              <KV show={s.freezer_on} label={t("ov.freezer")} value={onOff(t, s.freezer_on)} />
              <KV show={s.freezer_temp} label="°C" value={n(s.freezer_temp, 1)} />
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

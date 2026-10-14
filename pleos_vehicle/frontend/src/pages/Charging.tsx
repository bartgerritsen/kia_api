import { useState } from "react";
import { api } from "../api";
import { SERIES_COLORS, TimeChart } from "../components/Chart";
import { useI18n } from "../i18n";
import { fmtDateTime, fmtDuration, fmtNum, usePolling } from "../util";

const PERIODS = [7, 30, 90];

export function Charging({ vin }: { vin: string }) {
  const { t, lang } = useI18n();
  const [days, setDays] = useState(7);
  const { data } = usePolling(() => api.charging(vin, days), [vin, days], 60000);

  const history = (data?.history ?? []).map((p) => ({
    x: new Date(p.ts).getTime(),
    soc: p.soc,
    fuel: p.fuel_level,
  }));
  const hasFuel = history.some((p) => p.fuel !== null);
  const fmtX = (x: number) =>
    new Date(x).toLocaleString(lang === "nl" ? "nl-NL" : "en-GB", days > 7 ? { day: "numeric", month: "short" } : { weekday: "short", hour: "2-digit", minute: "2-digit" });

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
      </div>

      {history.length > 1 && (
        <TimeChart
          title={t("chg.socHistory")}
          data={history}
          series={[
            { key: "soc", label: t("chg.soc"), color: SERIES_COLORS[0] },
            ...(hasFuel ? [{ key: "fuel", label: t("chg.fuel"), color: SERIES_COLORS[1] }] : []),
          ]}
          unit="%"
          xFormat={fmtX}
          yFormat={(y) => fmtNum(y, lang)}
          yDomain={[0, 100]}
          yTicks={[0, 25, 50, 75, 100]}
          height={260}
        />
      )}

      <div className="card">
        <h2>{t("chg.sessions")}</h2>
        {!data ? (
          <p className="muted">{t("common.loading")}</p>
        ) : data.sessions.length === 0 ? (
          <p className="muted">{t("chg.none")}</p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>{t("chg.start")}</th>
                  <th>{t("chg.end")}</th>
                  <th className="num">{t("chg.duration")}</th>
                  <th className="num">{t("chg.from")}</th>
                  <th className="num">{t("chg.to")}</th>
                  <th className="num">{t("chg.added")}</th>
                  <th>{t("chg.type")}</th>
                </tr>
              </thead>
              <tbody>
                {data.sessions.map((s) => {
                  const minutes = (new Date(s.end_ts).getTime() - new Date(s.start_ts).getTime()) / 60000;
                  const added = s.end_soc !== null && s.start_soc !== null ? s.end_soc - s.start_soc : null;
                  return (
                    <tr key={s.id}>
                      <td>{fmtDateTime(s.start_ts, lang)}</td>
                      <td>{s.open ? <span className="pill good"><span className="dot" />{t("chg.ongoing")}</span> : fmtDateTime(s.end_ts, lang)}</td>
                      <td className="num">{fmtDuration(minutes)}</td>
                      <td className="num">{fmtNum(s.start_soc, lang)}%</td>
                      <td className="num">{fmtNum(s.end_soc, lang)}%</td>
                      <td className="num">{added !== null ? `+${fmtNum(added, lang)}%` : "–"}</td>
                      <td>{s.kind.toUpperCase()}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

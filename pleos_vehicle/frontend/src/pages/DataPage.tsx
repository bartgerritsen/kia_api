import { useMemo, useState } from "react";
import { api, type EndpointInfo, type Info } from "../api";
import { StatusLine } from "../components/Icons";
import { useI18n } from "../i18n";
import { fmtAgo, fmtDateTime, fmtNum, usePolling } from "../util";

export function DataPage({ vin, info, endpoints }: { vin: string | null; info: Info | null; endpoints: Record<string, EndpointInfo> }) {
  const { t, lang } = useI18n();
  const { data: usage } = usePolling(() => api.usage(), [], 30000);
  const { data: raw } = usePolling(() => (vin ? api.raw(vin) : Promise.resolve({} as Awaited<ReturnType<typeof api.raw>>)), [vin], 60000);
  const [rawKey, setRawKey] = useState("batteries");
  const p = usage?.poller ?? info?.poller;

  const perDay = useMemo(() => {
    const map = new Map<string, { calls: number; errors: number; rate_limited: number }>();
    for (const r of usage?.days ?? []) {
      const d = map.get(r.day) ?? { calls: 0, errors: 0, rate_limited: 0 };
      d.calls += r.calls;
      d.errors += r.errors;
      d.rate_limited += r.rate_limited;
      map.set(r.day, d);
    }
    return [...map.entries()];
  }, [usage]);

  const today = new Date().toISOString().slice(0, 10);
  const todayRows = (usage?.days ?? []).filter((r) => r.day === today);

  return (
    <div className="stack">
      <div className="banner">{t("data.rateNote")}</div>

      <div className="grid">
        <div className="card">
          <h2>{t("data.api")}</h2>
          <StatusLine level={p?.api_ok ? "good" : p?.api_ok === false ? "critical" : "neutral"}>
            {p?.api_ok ? t("data.ok") : p?.api_ok === false ? t("data.error") : t("data.waiting")}
          </StatusLine>
          {p?.last_error && <p className="small">{p.last_error}</p>}
          <dl className="kv">
            <dt>{t("data.callsToday")}</dt>
            <dd>{fmtNum(p?.calls_today, lang)}</dd>
            <dt>{t("data.interval")}</dt>
            <dd>{p?.poll_interval}s</dd>
            <dt>{t("data.lastPoll")}</dt>
            <dd>{fmtAgo(p?.last_poll, lang)}</dd>
            <dt>{t("data.lastSync")}</dt>
            <dd>{fmtAgo(p?.last_history_sync, lang)}</dd>
            {!!p?.backoff_seconds && (
              <>
                <dt>{t("data.backoff")}</dt>
                <dd>{p.backoff_seconds}s</dd>
              </>
            )}
            <dt>{t("data.mqtt")}</dt>
            <dd>{info?.mqtt}</dd>
            <dt>{t("data.version")}</dt>
            <dd>{info?.version}</dd>
          </dl>
          {!!p?.paused_endpoints.length && (
            <p className="small muted" style={{ marginBottom: 0 }}>
              {t("data.paused")}: {p.paused_endpoints.map((e) => e.endpoint).join(", ")}
            </p>
          )}
        </div>

        <div className="card">
          <h2>{t("data.endpoints")}</h2>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>{t("data.endpoint")}</th>
                  <th>{t("data.vehicleTs")}</th>
                  <th>{t("data.lastError")}</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(endpoints).map(([key, e]) => (
                  <tr key={key}>
                    <td>{key}</td>
                    <td>{fmtAgo(e.vehicle_ts, lang)}</td>
                    <td className="small">{e.error_code ? `${e.error_code} · ${fmtAgo(e.error_at, lang)}` : "–"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <div className="grid">
        <div className="card">
          <h2>{t("data.usage")}</h2>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>{t("data.day")}</th>
                  <th className="num">{t("data.calls")}</th>
                  <th className="num">{t("data.errors")}</th>
                  <th className="num">{t("data.rateLimited")}</th>
                </tr>
              </thead>
              <tbody>
                {perDay.map(([day, d]) => (
                  <tr key={day}>
                    <td>{day}</td>
                    <td className="num">{fmtNum(d.calls, lang)}</td>
                    <td className="num">{fmtNum(d.errors, lang)}</td>
                    <td className="num">{fmtNum(d.rate_limited, lang)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
        <div className="card">
          <h2>
            {t("data.calls")} · {today}
          </h2>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>{t("data.endpoint")}</th>
                  <th className="num">{t("data.calls")}</th>
                  <th className="num">{t("data.errors")}</th>
                </tr>
              </thead>
              <tbody>
                {todayRows.map((r) => (
                  <tr key={r.endpoint}>
                    <td>{r.endpoint}</td>
                    <td className="num">{fmtNum(r.calls, lang)}</td>
                    <td className="num">{fmtNum(r.errors, lang)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <div className="card">
        <div className="row" style={{ marginBottom: 8 }}>
          <h2 style={{ margin: 0 }}>{t("data.raw")}</h2>
          <select value={rawKey} onChange={(e) => setRawKey(e.target.value)}>
            {Object.keys(raw ?? {}).map((k) => (
              <option key={k}>{k}</option>
            ))}
          </select>
          <span className="small muted">
            {t("data.fetched")}: {fmtDateTime(raw?.[rawKey]?.fetched_at, lang)}
          </span>
        </div>
        <pre className="json">{JSON.stringify(raw?.[rawKey]?.payload ?? raw?.[rawKey] ?? null, null, 2)}</pre>
      </div>
    </div>
  );
}

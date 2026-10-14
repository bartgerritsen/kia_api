import { useEffect, useState } from "react";
import { api, type Info, type Vehicle } from "./api";
import { DEFAULT_TILES, TileContext } from "./components/MapView";
import { I18nProvider, useI18n, type Lang } from "./i18n";
import { Charging } from "./pages/Charging";
import { DataPage } from "./pages/DataPage";
import { MapPage } from "./pages/MapPage";
import { Overview } from "./pages/Overview";
import { TripDetail, Trips } from "./pages/Trips";
import { fmtAgo, readStored, useHashRoute, usePolling, writeStored } from "./util";

const TABS = ["overview", "map", "trips", "charging", "data"] as const;

export default function App() {
  const [lang, setLang] = useState<Lang>((readStored("pleos.lang") as Lang) || "en");
  const { data: info } = usePolling(() => api.info(), [], 30000);

  // The add-on option sets the default language until the viewer picks one
  useEffect(() => {
    if (info && !readStored("pleos.lang")) setLang(info.language);
  }, [info]);

  const tiles = info?.map_tile_url
    ? { url: info.map_tile_url, attribution: info.map_tile_attribution ?? "" }
    : DEFAULT_TILES;

  const changeLang = (l: Lang) => {
    setLang(l);
    writeStored("pleos.lang", l);
  };

  return (
    <I18nProvider lang={lang}>
      <TileContext.Provider value={tiles}>
        <Shell info={info} lang={lang} setLang={changeLang} />
      </TileContext.Provider>
    </I18nProvider>
  );
}

function Shell({ info, lang, setLang }: { info: Info | null; lang: Lang; setLang: (l: Lang) => void }) {
  const { t } = useI18n();
  const [route, navigate] = useHashRoute();
  const tab = (TABS as readonly string[]).includes(route[0]) ? route[0] : "overview";
  const { data: vehicles, error } = usePolling(() => api.vehicles(), [], 60000);
  const [vin, setVin] = useState<string | null>(readStored("pleos.vin"));
  const [refreshing, setRefreshing] = useState(false);

  const vehicle: Vehicle | undefined = vehicles?.find((v) => v.vin === vin) ?? vehicles?.[0];
  const activeVin = vehicle?.vin ?? null;
  const { data: detail, reload } = usePolling(
    () => (activeVin ? api.state(activeVin) : Promise.resolve(null)),
    [activeVin],
    20000,
  );

  const refresh = async () => {
    setRefreshing(true);
    await api.refresh();
    window.setTimeout(() => {
      reload();
      setRefreshing(false);
    }, 6000);
  };

  const state = detail?.state ?? vehicle?.state ?? {};
  const title = vehicle ? vehicle.nickname || vehicle.sellname || vehicle.vin : t("common.loading");

  return (
    <div className="app">
      <header className="topbar">
        <h1>
          {title}
          {vehicle && (
            <span className="sub">
              {vehicle.sellname} · {t("common.updated")} {fmtAgo(state.last_vehicle_update, lang)}
            </span>
          )}
        </h1>
        {vehicles && vehicles.length > 1 && (
          <select
            value={activeVin ?? ""}
            onChange={(e) => {
              setVin(e.target.value);
              writeStored("pleos.vin", e.target.value);
            }}
          >
            {vehicles.map((v) => (
              <option key={v.vin} value={v.vin}>
                {v.nickname || v.sellname || v.vin}
              </option>
            ))}
          </select>
        )}
        <div className="seg" aria-label="Language">
          {(["en", "nl"] as Lang[]).map((l) => (
            <button key={l} className={l === lang ? "active" : ""} onClick={() => setLang(l)}>
              {l.toUpperCase()}
            </button>
          ))}
        </div>
        <button className="btn" onClick={refresh} disabled={refreshing || !activeVin}>
          {refreshing ? t("common.loading") : t("common.refresh")}
        </button>
      </header>

      <nav className="tabs">
        {TABS.map((key) => (
          <button key={key} className={tab === key ? "active" : ""} onClick={() => navigate(key)}>
            {t(`nav.${key}`)}
          </button>
        ))}
      </nav>

      {info?.mock && <div className="banner">{t("common.mockBanner")}</div>}
      {info?.poller.last_error && tab !== "data" && <div className="banner error">{info.poller.last_error}</div>}
      {error && <div className="banner error">{error}</div>}

      {tab === "data" ? (
        <DataPage vin={activeVin} info={info} endpoints={detail?.endpoints ?? {}} />
      ) : !vehicle || !activeVin ? (
        <p className="muted">{vehicles ? t("common.noVehicles") : t("common.loading")}</p>
      ) : tab === "map" ? (
        <MapPage vin={activeVin} state={state} />
      ) : tab === "trips" && route[1] ? (
        <TripDetail vin={activeVin} start={route[1]} onBack={() => navigate("trips")} />
      ) : tab === "trips" ? (
        <Trips vin={activeVin} onOpen={(start) => navigate(`trips/${encodeURIComponent(start)}`)} />
      ) : tab === "charging" ? (
        <Charging vin={activeVin} />
      ) : (
        <Overview vehicle={vehicle} state={state} endpoints={detail?.endpoints ?? {}} onNavigate={navigate} />
      )}
    </div>
  );
}

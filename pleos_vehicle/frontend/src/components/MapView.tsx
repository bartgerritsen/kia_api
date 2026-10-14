import { createContext, useContext, useEffect, useState } from "react";
import { CircleMarker, MapContainer, Polyline, TileLayer, Tooltip, useMap } from "react-leaflet";
import type { LatLngExpression, LatLngBoundsExpression } from "leaflet";
import "leaflet/dist/leaflet.css";

export interface TileConfig {
  url: string;
  attribution: string;
}

export const DEFAULT_TILES: TileConfig = {
  url: "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
  attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
};

/** Tile source; the add-on option map_tile_url overrides the OpenStreetMap default. */
export const TileContext = createContext<TileConfig>(DEFAULT_TILES);

interface Props {
  position?: [number, number] | null;
  track?: [number, number][];
  label?: string;
  small?: boolean;
}

function FitBounds({ points }: { points: [number, number][] }) {
  const map = useMap();
  const key = points.length ? `${points[0]}-${points[points.length - 1]}-${points.length}` : "";
  useEffect(() => {
    if (points.length > 1) map.fitBounds(points as LatLngBoundsExpression, { padding: [24, 24], maxZoom: 16 });
    else if (points.length === 1) map.setView(points[0] as LatLngExpression, 15);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  return null;
}

function usePrefersDark(): boolean {
  const query = "(prefers-color-scheme: dark)";
  const [dark, setDark] = useState(() => window.matchMedia?.(query).matches ?? false);
  useEffect(() => {
    const mql = window.matchMedia?.(query);
    if (!mql) return;
    const onChange = () => setDark(mql.matches);
    mql.addEventListener("change", onChange);
    return () => mql.removeEventListener("change", onChange);
  }, []);
  return dark;
}

/**
 * Map with the car's position and an optional track. Circle markers avoid the need for icon assets.
 *
 * tile.openstreetmap.org blocks tile requests without a Referer, and the Home Assistant
 * Ingress page suppresses it, so each tile explicitly sends the page origin as Referer.
 */
export function MapView({ position, track = [], label, small }: Props) {
  const tiles = useContext(TileContext);
  const dark = usePrefersDark();
  const points = track.length ? track : position ? [position] : [];
  const center: [number, number] = position ?? points[0] ?? [52.1, 5.1];
  const classes = ["map", small ? "small" : "", dark ? "dark-tiles" : ""].filter(Boolean).join(" ");
  return (
    <MapContainer center={center} zoom={14} className={classes} scrollWheelZoom={!small}>
      <TileLayer
        key={tiles.url}
        url={tiles.url}
        attribution={tiles.attribution}
        referrerPolicy="strict-origin-when-cross-origin"
        maxZoom={19}
      />
      {track.length > 1 && <Polyline positions={track} pathOptions={{ color: "#2a78d6", weight: 3, opacity: 0.85 }} />}
      {position && (
        <CircleMarker center={position} radius={9} pathOptions={{ color: "#fcfcfb", weight: 3, fillColor: "#eb6834", fillOpacity: 1 }}>
          {label && <Tooltip>{label}</Tooltip>}
        </CircleMarker>
      )}
      <FitBounds points={points} />
    </MapContainer>
  );
}

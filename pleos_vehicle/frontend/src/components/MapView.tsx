import { useEffect } from "react";
import { CircleMarker, MapContainer, Polyline, TileLayer, Tooltip, useMap } from "react-leaflet";
import type { LatLngExpression, LatLngBoundsExpression } from "leaflet";
import "leaflet/dist/leaflet.css";

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

/** OpenStreetMap view with the car's position and an optional track. Uses circle markers so no icon assets are needed. */
export function MapView({ position, track = [], label, small }: Props) {
  const points = track.length ? track : position ? [position] : [];
  const center: [number, number] = position ?? points[0] ?? [52.1, 5.1];
  return (
    <MapContainer center={center} zoom={14} className={small ? "map small" : "map"} scrollWheelZoom={!small}>
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
        url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
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

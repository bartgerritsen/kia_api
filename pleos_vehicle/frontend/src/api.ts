// Relative URLs (no leading slash) so requests stay under the Ingress path.
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(`api/${path}`, init);
  if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`);
  return resp.json() as Promise<T>;
}

export type VehicleState = Record<string, any> & {
  battery_soc?: number | null;
  fuel_level?: number | null;
  latitude?: number;
  longitude?: number;
  warnings?: string[];
  last_vehicle_update?: string | null;
};

export interface Vehicle {
  vin: string;
  nickname?: string;
  name?: string;
  type?: string;
  sellname?: string;
  state: VehicleState;
}

export interface EndpointInfo {
  fetched_at?: string | null;
  vehicle_ts?: string | null;
  error_code?: string | null;
  error_message?: string | null;
  error_at?: string | null;
}

export interface PollerStatus {
  api_ok: boolean | null;
  last_error: string | null;
  last_poll: string | null;
  last_history_sync: string | null;
  backoff_seconds: number;
  poll_interval: number;
  history_sync_interval: number;
  calls_today: number;
  paused_endpoints: { vin: string; endpoint: string; retry_in_s: number }[];
}

export interface Info {
  version: string;
  brand: string;
  language: "en" | "nl";
  timezone: string;
  mock: boolean;
  mqtt: string;
  map_tile_url?: string | null;
  map_tile_attribution?: string | null;
  poller: PollerStatus;
}

export interface LocationPoint {
  ts: string;
  lat: number;
  lon: number;
  speed_kph?: number | null;
  heading?: number | null;
}

export interface TripSummary {
  start_time: string;
  end_time?: string;
  duration_min?: number;
  distance_km?: number;
  start_odometer?: number;
  end_odometer?: number;
  max_speed?: number;
  avg_moving_speed?: number;
  engine_on_pct?: number;
  outside_temp?: number;
  kinds?: string[];
}

export interface Frame {
  interval_s: number;
  t: number[];
  series: Record<string, (number | string | null)[]>;
}

export interface TripDetail {
  summary: TripSummary;
  frames: Record<string, Frame>;
  route: LocationPoint[];
}

export interface ChargingSession {
  id: number;
  start_ts: string;
  end_ts: string;
  start_soc: number | null;
  end_soc: number | null;
  kind: "ac" | "dc";
  open: number;
}

export interface BatteryPoint {
  ts: string;
  soc: number | null;
  fuel_level: number | null;
  charging: number | null;
  plugged_in: number | null;
  status: string | null;
}

export interface UsageRow {
  day: string;
  endpoint: string;
  calls: number;
  errors: number;
  rate_limited: number;
}

const enc = encodeURIComponent;

export const api = {
  info: () => request<Info>("info"),
  vehicles: () => request<Vehicle[]>("vehicles"),
  state: (vin: string) =>
    request<{ vehicle: Vehicle; state: VehicleState; endpoints: Record<string, EndpointInfo> }>(`vehicles/${enc(vin)}/state`),
  raw: (vin: string) => request<Record<string, EndpointInfo & { payload: unknown }>>(`vehicles/${enc(vin)}/raw`),
  locations: (vin: string, hours: number) => request<LocationPoint[]>(`vehicles/${enc(vin)}/locations?hours=${hours}`),
  trips: (vin: string, days: number) => request<TripSummary[]>(`vehicles/${enc(vin)}/trips?days=${days}`),
  trip: (vin: string, start: string) => request<TripDetail>(`vehicles/${enc(vin)}/trips/${enc(start)}`),
  charging: (vin: string, days: number) =>
    request<{ sessions: ChargingSession[]; history: BatteryPoint[] }>(`vehicles/${enc(vin)}/charging?days=${days}`),
  usage: () => request<{ days: UsageRow[]; poller: PollerStatus }>("usage"),
  refresh: () => request<{ ok: boolean }>("refresh", { method: "POST" }),
  syncHistory: () => request<{ ok: boolean }>("history/sync", { method: "POST" }),
};

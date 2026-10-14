import { useCallback, useEffect, useRef, useState } from "react";
import type { Lang } from "./i18n";

const locale = (lang: Lang) => (lang === "nl" ? "nl-NL" : "en-GB");

export function fmtNum(value: number | null | undefined, lang: Lang, digits = 0): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "–";
  return value.toLocaleString(locale(lang), { maximumFractionDigits: digits, minimumFractionDigits: digits });
}

export function fmtDateTime(iso: string | null | undefined, lang: Lang, opts?: Intl.DateTimeFormatOptions): string {
  if (!iso) return "–";
  return new Date(iso).toLocaleString(locale(lang), opts ?? { dateStyle: "medium", timeStyle: "short" });
}

export function fmtTime(iso: string | null | undefined, lang: Lang): string {
  return fmtDateTime(iso, lang, { hour: "2-digit", minute: "2-digit" });
}

export function fmtDate(iso: string | null | undefined, lang: Lang): string {
  return fmtDateTime(iso, lang, { weekday: "short", day: "numeric", month: "short" });
}

export function fmtDuration(minutes: number | null | undefined): string {
  if (minutes === null || minutes === undefined) return "–";
  const h = Math.floor(minutes / 60);
  const m = Math.round(minutes % 60);
  return h ? `${h}h ${m.toString().padStart(2, "0")}m` : `${m} min`;
}

export function fmtAgo(iso: string | null | undefined, lang: Lang): string {
  if (!iso) return "–";
  const seconds = (Date.now() - new Date(iso).getTime()) / 1000;
  const rtf = new Intl.RelativeTimeFormat(locale(lang), { numeric: "auto" });
  if (Math.abs(seconds) < 60) return rtf.format(-Math.round(seconds), "second");
  if (Math.abs(seconds) < 3600) return rtf.format(-Math.round(seconds / 60), "minute");
  if (Math.abs(seconds) < 86400) return rtf.format(-Math.round(seconds / 3600), "hour");
  return rtf.format(-Math.round(seconds / 86400), "day");
}

/** Fetch on mount and every `intervalMs`; `reload` refetches immediately. */
export function usePolling<T>(fetcher: () => Promise<T>, deps: unknown[], intervalMs = 30000) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  const reload = useCallback(async () => {
    try {
      setData(await fetcherRef.current());
      setError(null);
    } catch (e) {
      setError(String(e));
    }
  }, []);

  useEffect(() => {
    setData(null);
    reload();
    if (!intervalMs) return;
    const id = window.setInterval(reload, intervalMs);
    return () => window.clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return { data, error, reload };
}

/** Minimal hash router: "#/trips/2026-10-01T08:00:00.000Z" -> ["trips", "2026-10-01T08:00:00.000Z"] */
export function useHashRoute(): [string[], (path: string) => void] {
  const parse = () =>
    window.location.hash
      .replace(/^#\/?/, "")
      .split("/")
      .filter(Boolean)
      .map(decodeURIComponent);
  const [route, setRoute] = useState<string[]>(parse);
  useEffect(() => {
    const onChange = () => setRoute(parse());
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  const navigate = (path: string) => {
    window.location.hash = `#/${path}`;
  };
  return [route, navigate];
}

export function readStored(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

export function writeStored(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // Storage can be unavailable (private mode); preferences then last for the session only
  }
}

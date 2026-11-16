/**
 * Data adapter.
 *
 * Two modes, one shape:
 *   bundled  — the committed snapshot (works offline, deterministic, CI-safe)
 *   live     — data.gov.in CPCB resource, requires VITE_DATA_GOV_KEY
 *
 * Live failures never break the dashboard: we fall back to the snapshot and
 * surface a warning, because a stale reading is more useful than a blank screen.
 */
import snapshot from './air-quality.json';
import { aqiFromPm25, computeAqi } from '../lib/aqi.js';

export const DEFAULT_RESOURCE_ID = '3b01bcb8-0b14-4abf-b6f2-c1bfd384ba69'; // CPCB real-time AQI
const FETCH_TIMEOUT_MS = 6000;

export function getSnapshot() {
  return snapshot;
}

/** Build the dashboard payload from the committed snapshot. */
export function bundledPayload() {
  return { ...snapshot, mode: 'bundled', warning: null };
}

/**
 * data.gov.in returns one row per (station, pollutant). Fold those rows into
 * station records with a computed AQI. Pure + exported so it can be tested
 * without touching the network.
 *
 * Example record: { city: 'Chennai', station: 'Adyar', pollutant_id: 'PM2.5',
 *                   pollutant_avg: '48', last_update: '16-11-2026 09:00:00' }
 */
export function normaliseGovInRecords(records = []) {
  const byStation = new Map();

  for (const record of records) {
    const city = record.city ?? record.city_name ?? 'Unknown';
    const stationName = record.station ?? record.station_name ?? record.location ?? 'Unknown station';
    const key = `${city}::${stationName}`;
    const entry = byStation.get(key) ?? {
      id: key.toLowerCase().replace(/[^a-z0-9]+/g, '-'),
      name: `${stationName}, ${city}`,
      cityId: city.toLowerCase().replace(/[^a-z0-9]+/g, '-'),
      cityName: city,
      zone: stationName,
      readings: {},
      lastUpdated: record.last_update ?? null,
    };

    const pollutant = String(record.pollutant_id ?? '').toUpperCase().replace('PM2.5', 'PM25');
    const value = Number.parseFloat(record.pollutant_avg);
    if (Number.isFinite(value) && pollutant) entry.readings[pollutant] = value;
    byStation.set(key, entry);
  }

  return [...byStation.values()].map((station) => {
    const { aqi, dominant, indices } = computeAqi({
      pm25: station.readings.PM25 ?? 0,
      pm10: station.readings.PM10 ?? 0,
      no2: station.readings.NO2 ?? 0,
    });
    return {
      id: station.id,
      name: station.name,
      cityId: station.cityId,
      cityName: station.cityName,
      zone: station.zone,
      aqi,
      pm25: station.readings.PM25 ?? null,
      dominant,
      indices,
      lastUpdated: station.lastUpdated,
    };
  });
}

/**
 * Fetch live readings. Throws on missing key / network error so the caller can
 * decide what to do; `loadDashboard` turns that into a graceful fallback.
 */
export async function fetchLiveReadings({ apiKey, resourceId = DEFAULT_RESOURCE_ID, city = null, fetchImpl = fetch } = {}) {
  if (!apiKey) throw new Error('VITE_DATA_GOV_KEY is not set');

  const url = new URL(`https://api.data.gov.in/resource/${resourceId}`);
  url.searchParams.set('api-key', apiKey);
  url.searchParams.set('format', 'json');
  url.searchParams.set('limit', '500');
  if (city) url.searchParams.set('filters[city]', city);

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);
  try {
    const response = await fetchImpl(url.toString(), { signal: controller.signal, headers: { accept: 'application/json' } });
    if (!response.ok) throw new Error(`data.gov.in responded ${response.status}`);
    const payload = await response.json();
    const stations = normaliseGovInRecords(payload.records ?? payload.data ?? []);
    if (stations.length === 0) throw new Error('data.gov.in returned no station rows');
    return stations;
  } finally {
    clearTimeout(timer);
  }
}

/**
 * Merge live station readings into the snapshot: today's city AQI becomes the
 * mean of its live stations, history stays as published (and is labelled so).
 */
export function mergeLive(snapshotPayload, stations) {
  const byCity = new Map();
  for (const station of stations) {
    if (!Number.isFinite(station.aqi) || station.aqi <= 0) continue;
    const list = byCity.get(station.cityId) ?? [];
    list.push(station);
    byCity.set(station.cityId, list);
  }

  const cities = snapshotPayload.cities.map((city) => {
    const live = byCity.get(city.id);
    if (!live?.length) return city;
    const meanAqi = Math.round(live.reduce((sum, station) => sum + station.aqi, 0) / live.length);
    const meanPm25 = Number(
      (live.reduce((sum, station) => sum + (station.pm25 ?? 0), 0) / live.length).toFixed(1),
    );
    const days = [...city.days];
    days[days.length - 1] = {
      ...days[days.length - 1],
      aqi: meanAqi,
      pm25: meanPm25 || aqiFromPm25(meanAqi),
      live: true,
    };
    return { ...city, days };
  });

  return {
    ...snapshotPayload,
    cities,
    stations,
    mode: 'live',
    warning: 'Live station readings from data.gov.in; the 45-day history is the bundled reference series.',
  };
}

/** Resolve the environment configuration once. */
export function dataConfig(env = import.meta.env ?? {}) {
  return {
    live: env.VITE_DATA_MODE === 'live',
    apiKey: env.VITE_DATA_GOV_KEY ?? '',
    resourceId: env.VITE_DATA_GOV_RESOURCE || DEFAULT_RESOURCE_ID,
    timeoutMs: FETCH_TIMEOUT_MS,
  };
}

/**
 * The single entry point the app uses.
 * Never throws: worst case you get the bundled snapshot with a warning.
 */
export async function loadDashboard({ env = import.meta.env ?? {}, fetchImpl = fetch, forceBundled = false } = {}) {
  const config = dataConfig(env);
  const base = bundledPayload();
  if (forceBundled || !config.live) return base;
  if (!config.apiKey) {
    return { ...base, mode: 'fallback', warning: 'Live mode needs VITE_DATA_GOV_KEY — showing the bundled snapshot.' };
  }
  try {
    const stations = await fetchLiveReadings({ apiKey: config.apiKey, resourceId: config.resourceId, fetchImpl });
    return mergeLive(base, stations);
  } catch (error) {
    return { ...base, mode: 'fallback', warning: `Live data unavailable (${error.message}). Showing the snapshot.` };
  }
}

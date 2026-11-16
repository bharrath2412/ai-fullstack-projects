import { describe, expect, it, vi } from 'vitest';
import {
  DEFAULT_RESOURCE_ID,
  bundledPayload,
  dataConfig,
  fetchLiveReadings,
  loadDashboard,
  mergeLive,
  normaliseGovInRecords,
} from '../src/data/source.js';
import { aqiFromPm25 } from '../src/lib/aqi.js';

const rows = [
  { city: 'Chennai', station: 'Adyar', pollutant_id: 'PM2.5', pollutant_avg: '48', last_update: '16-11-2026 09:00:00' },
  { city: 'Chennai', station: 'Adyar', pollutant_id: 'PM10', pollutant_avg: '92' },
  { city: 'Chennai', station: 'Adyar', pollutant_id: 'NO2', pollutant_avg: '31' },
  { city: 'Delhi', station: 'Anand Vihar', pollutant_id: 'PM2.5', pollutant_avg: '210' },
];

describe('normaliseGovInRecords', () => {
  it('folds one row per pollutant into one record per station', () => {
    const stations = normaliseGovInRecords(rows);
    expect(stations).toHaveLength(2);
    const adyar = stations.find((station) => station.zone === 'Adyar');
    expect(adyar.name).toBe('Adyar, Chennai');
    expect(adyar.cityId).toBe('chennai');
    expect(adyar.pm25).toBe(48);
    // PM10 (92 µg/m³) outranks PM2.5 (48 µg/m³) here, so the AQI follows PM10.
    expect(adyar.dominant).toBe('PM10');
    expect(adyar.aqi).toBe(adyar.indices.PM10);
    expect(adyar.indices['PM2.5']).toBe(aqiFromPm25(48));
    expect(adyar.aqi).toBe(92);
  });

  it('tolerates alternative field names and junk numbers', () => {
    const stations = normaliseGovInRecords([
      { city_name: 'Mumbai', station_name: 'Worli', pollutant_id: 'PM2.5', pollutant_avg: 'oops' },
      { city_name: 'Mumbai', station_name: 'Worli', pollutant_id: 'PM10', pollutant_avg: '180' },
    ]);
    expect(stations).toHaveLength(1);
    expect(stations[0].id).toBe('mumbai-worli');
    expect(stations[0].pm25).toBeNull();
    expect(stations[0].indices['PM2.5']).toBe(0);
    expect(stations[0].aqi).toBeGreaterThan(0);
  });

  it('returns an empty array for empty input', () => {
    expect(normaliseGovInRecords([])).toEqual([]);
    expect(normaliseGovInRecords()).toEqual([]);
  });
});

describe('fetchLiveReadings', () => {
  it('refuses to call the API without a key', async () => {
    await expect(fetchLiveReadings({ apiKey: '' })).rejects.toThrow(/VITE_DATA_GOV_KEY/);
  });

  it('builds the documented query and parses records', async () => {
    const fetchImpl = vi.fn(async () => ({ ok: true, json: async () => ({ records: rows }) }));
    const stations = await fetchLiveReadings({ apiKey: 'k', fetchImpl });
    expect(stations).toHaveLength(2);
    const url = fetchImpl.mock.calls[0][0];
    expect(url).toContain(DEFAULT_RESOURCE_ID);
    expect(url).toContain('api-key=k');
    expect(url).toContain('format=json');
  });

  it('passes the city filter through when asked', async () => {
    const fetchImpl = vi.fn(async () => ({ ok: true, json: async () => ({ records: rows }) }));
    await fetchLiveReadings({ apiKey: 'k', city: 'Chennai', fetchImpl });
    expect(decodeURIComponent(fetchImpl.mock.calls[0][0])).toContain('filters[city]=Chennai');
  });

  it('throws on HTTP errors and on empty payloads', async () => {
    await expect(
      fetchLiveReadings({ apiKey: 'k', fetchImpl: async () => ({ ok: false, status: 429 }) }),
    ).rejects.toThrow(/429/);
    await expect(
      fetchLiveReadings({ apiKey: 'k', fetchImpl: async () => ({ ok: true, json: async () => ({ records: [] }) }) }),
    ).rejects.toThrow(/no station rows/);
  });
});

describe('mergeLive', () => {
  it('overwrites the latest day for cities that have live stations', () => {
    const base = bundledPayload();
    const stations = [
      { cityId: 'chennai', name: 'Adyar, Chennai', zone: 'Adyar', aqi: 200, pm25: 95 },
      { cityId: 'chennai', name: 'Velachery, Chennai', zone: 'Velachery', aqi: 100, pm25: 55 },
    ];
    const merged = mergeLive(base, stations);
    const chennai = merged.cities.find((city) => city.id === 'chennai');
    const delhi = merged.cities.find((city) => city.id === 'delhi');
    expect(chennai.days.at(-1).aqi).toBe(150); // mean of 200 and 100
    expect(chennai.days.at(-1).live).toBe(true);
    expect(delhi.days.at(-1).live).toBeUndefined();
    expect(chennai.days.length).toBe(base.cities.find((c) => c.id === 'chennai').days.length);
    expect(merged.mode).toBe('live');
    expect(merged.warning).toMatch(/data\.gov\.in/);
    expect(merged.stations).toHaveLength(2);
  });

  it('ignores stations with no usable AQI', () => {
    const base = bundledPayload();
    const before = base.cities.find((city) => city.id === 'mumbai').days.at(-1).aqi;
    const merged = mergeLive(base, [{ cityId: 'mumbai', aqi: 0, pm25: null }]);
    expect(merged.cities.find((city) => city.id === 'mumbai').days.at(-1).aqi).toBe(before);
  });
});

describe('loadDashboard', () => {
  it('returns the bundled snapshot by default', async () => {
    const payload = await loadDashboard({ env: {} });
    expect(payload.mode).toBe('bundled');
    expect(payload.warning).toBeNull();
    expect(payload.cities.length).toBeGreaterThanOrEqual(5);
  });

  it('warns instead of throwing when live mode has no key', async () => {
    const payload = await loadDashboard({ env: { VITE_DATA_MODE: 'live' } });
    expect(payload.mode).toBe('fallback');
    expect(payload.warning).toMatch(/VITE_DATA_GOV_KEY/);
  });

  it('falls back to the snapshot when the network fails', async () => {
    const payload = await loadDashboard({
      env: { VITE_DATA_MODE: 'live', VITE_DATA_GOV_KEY: 'k' },
      fetchImpl: async () => {
        throw new Error('offline');
      },
    });
    expect(payload.mode).toBe('fallback');
    expect(payload.warning).toMatch(/offline/);
    expect(payload.cities.length).toBeGreaterThan(0);
  });

  it('uses live stations when the fetch succeeds', async () => {
    const payload = await loadDashboard({
      env: { VITE_DATA_MODE: 'live', VITE_DATA_GOV_KEY: 'k' },
      fetchImpl: async () => ({ ok: true, json: async () => ({ records: rows }) }),
    });
    expect(payload.mode).toBe('live');
    expect(payload.stations).toHaveLength(2);
  });

  it('honours forceBundled even in live mode', async () => {
    const payload = await loadDashboard({ env: { VITE_DATA_MODE: 'live', VITE_DATA_GOV_KEY: 'k' }, forceBundled: true });
    expect(payload.mode).toBe('bundled');
  });
});

describe('dataConfig', () => {
  it('reads env vars with safe defaults', () => {
    expect(dataConfig({})).toEqual({
      live: false,
      apiKey: '',
      resourceId: DEFAULT_RESOURCE_ID,
      timeoutMs: 6000,
    });
    const config = dataConfig({
      VITE_DATA_MODE: 'live',
      VITE_DATA_GOV_KEY: 'secret',
      VITE_DATA_GOV_RESOURCE: 'res-1',
    });
    expect(config.live).toBe(true);
    expect(config.apiKey).toBe('secret');
    expect(config.resourceId).toBe('res-1');
  });
});

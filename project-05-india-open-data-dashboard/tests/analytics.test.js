import { describe, expect, it } from 'vitest';
import { aqiFromPm25, categoryFor } from '../src/lib/aqi.js';
import {
  categoryDistribution,
  compareCities,
  describeAirA11y,
  filterStations,
  latestDay,
  metricMeta,
  series,
  smoothedAqi,
  summarizeCity,
  validateSnapshot,
  zonesFor,
} from '../src/lib/analytics.js';

const makeDay = (date, pm25) => ({
  date,
  pm25,
  pm10: Number((pm25 * 1.7).toFixed(1)),
  no2: 20,
  temp_c: 28,
  humidity: 70,
  aqi: aqiFromPm25(pm25),
});

const city = (id, name, pmValues) => ({
  id,
  name,
  state: 'Test',
  days: pmValues.map((pm25, index) =>
    makeDay(`2026-11-${String(index + 1).padStart(2, '0')}`, pm25),
  ),
});

const stations = [
  { id: 's1', name: 'Adyar, Chennai', cityId: 'chennai', zone: 'Adyar', aqi: 120, dominant: 'PM2.5' },
  { id: 's2', name: 'Anna Nagar, Chennai', cityId: 'chennai', zone: 'Anna Nagar', aqi: 80, dominant: 'PM10' },
  { id: 's3', name: 'Anand Vihar, Delhi', cityId: 'delhi', zone: 'Anand Vihar', aqi: 330, dominant: 'PM2.5' },
];

describe('series slicing', () => {
  it('returns the requested window with category per point', () => {
    const subject = city('c', 'Chennai', [10, 20, 30, 40, 50]);
    const result = series(subject, 'pm25', 3);
    expect(result).toHaveLength(3);
    expect(result[0].value).toBe(30);
    expect(result[2].value).toBe(50);
    expect(result[0].category.label).toBe(categoryFor(aqiFromPm25(30)).label);
  });

  it('never asks for more days than exist', () => {
    const subject = city('c', 'Chennai', [10, 20]);
    expect(series(subject, 'aqi', 45)).toHaveLength(2);
    expect(series(null, 'aqi', 7)).toEqual([]);
  });
});

describe('summarizeCity', () => {
  it('computes latest, average, peak and trend', () => {
    const subject = city('chennai', 'Chennai', [20, 20, 20, 20, 20, 20, 20, 60, 60, 60, 60, 60, 60, 60]);
    const summary = summarizeCity(subject, 7);
    expect(summary.latest.pm25).toBe(60);
    expect(summary.windowAverage).toBe(aqiFromPm25(60));
    expect(summary.peak).toBe(aqiFromPm25(60));
    expect(summary.trend.direction).toBe('up');
    expect(summary.pm25Average).toBe(60);
  });

  it('handles a city with no days', () => {
    expect(summarizeCity({ id: 'x', name: 'X', days: [] })).toBeNull();
    expect(latestDay({ days: [] })).toBeNull();
  });
});

describe('city comparison', () => {
  it('sorts by average AQI, worst first', () => {
    const rows = compareCities(
      [city('a', 'Clean', [10, 10]), city('b', 'Dirty', [90, 90]), city('c', 'Mid', [45, 45])],
      'aqi',
      2,
    );
    expect(rows.map((row) => row.name)).toEqual(['Dirty', 'Mid', 'Clean']);
    expect(rows[0].category.label).toBe(categoryFor(aqiFromPm25(90)).label);
  });
});

describe('category distribution', () => {
  it('counts days per band and orders them by severity', () => {
    const subject = city('c', 'X', [10, 10, 45, 100, 130]);
    const distribution = categoryDistribution(subject, 5);
    const total = distribution.reduce((sum, bucket) => sum + bucket.count, 0);
    expect(total).toBe(5);
    const labels = distribution.map((bucket) => bucket.category.label);
    expect(labels).toEqual([...labels].sort((a, b) => bandIndex(a) - bandIndex(b)));
  });

  const bandIndex = (label) =>
    ['Good', 'Satisfactory', 'Moderate', 'Poor', 'Very Poor', 'Severe'].indexOf(label);
});

describe('station filtering', () => {
  it('filters by city, zone and free text', () => {
    expect(filterStations(stations, { cityId: 'chennai' }).every((s) => s.cityId === 'chennai')).toBe(true);
    expect(filterStations(stations, { cityId: 'chennai', zone: 'Adyar' })).toHaveLength(1);
    expect(filterStations(stations, { query: 'anand' })).toHaveLength(1);
    expect(filterStations(stations, { query: 'NAGAR' })).toHaveLength(1);
    expect(filterStations(stations, { query: 'chennai' })[0].id).toBe('s1');
  });

  it('sorts worst first and supports a max-AQI ceiling', () => {
    const all = filterStations(stations, {});
    expect(all.map((s) => s.aqi)).toEqual([330, 120, 80]);
    expect(filterStations(stations, { maxAqi: 100 }).map((s) => s.id)).toEqual(['s2']);
    expect(filterStations(stations, { query: '   ' })).toHaveLength(3);
  });

  it('lists zones for a city', () => {
    expect(zonesFor(stations, 'chennai')).toEqual(['Adyar', 'Anna Nagar']);
  });
});

describe('presentation helpers', () => {
  it('exposes metric metadata with a fallback', () => {
    expect(metricMeta('pm25').label).toBe('PM2.5');
    expect(metricMeta('nope').key).toBe('aqi');
  });

  it('smooths the AQI series', () => {
    const subject = city('c', 'X', [10, 10, 10, 10]);
    expect(smoothedAqi(subject, 2)).toEqual([17, 17, 17, 17]);
    expect(smoothedAqi({ days: [] })).toEqual([]);
  });

  it('writes a screen-reader summary', () => {
    const summary = summarizeCity(city('c', 'X', [40, 40, 40, 40, 40, 40, 40, 40]), 7);
    expect(describeAirA11y(summary)).toMatch(/Current AQI \d+, (Good|Satisfactory|Moderate|Poor)/);
    expect(describeAirA11y(null)).toMatch(/No air quality data/);
  });
});

describe('snapshot validation', () => {
  it('accepts a consistent snapshot', () => {
    const snapshot = {
      cities: [city('chennai', 'Chennai', [10, 20])],
      stations: [{ id: 's1' }],
    };
    expect(validateSnapshot(snapshot)).toEqual([]);
  });

  it('flags AQI/PM2.5 mismatches, bad dates and empty cities', () => {
    const snapshot = {
      cities: [
        {
          id: 'x',
          name: 'X',
          days: [
            { date: 'not-a-date', pm25: 10, aqi: 999 },
            { date: '2026-11-02', pm25: -5, aqi: 10 },
          ],
        },
      ],
      stations: [],
    };
    const problems = validateSnapshot(snapshot);
    expect(problems.some((p) => p.includes('bad date'))).toBe(true);
    expect(problems.some((p) => p.includes('mismatch'))).toBe(true);
    expect(problems).toContain('no stations');
    expect(validateSnapshot(null)).toEqual(['snapshot is not an object']);
  });

  it('validates the real committed snapshot file', async () => {
    const { default: snapshot } = await import('../src/data/air-quality.json');
    const problems = validateSnapshot(snapshot);
    expect(problems).toEqual([]);
    expect(snapshot.cities.length).toBeGreaterThanOrEqual(5);
    expect(snapshot.cities[0].days.length).toBeGreaterThanOrEqual(30);
  });
});

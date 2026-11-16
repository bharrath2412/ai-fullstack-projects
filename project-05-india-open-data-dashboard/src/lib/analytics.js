/**
 * Everything the dashboard computes lives here, as pure functions over the
 * snapshot shape ({ cities: [{ days: [...] }], stations: [...] }). Views stay dumb,
 * tests stay fast, and the same maths runs in a worker or on the server later.
 */
import { aqiFromPm25, categoryFor, movingAverage, trend } from './aqi.js';

export const METRICS = [
  { key: 'aqi', label: 'AQI', unit: 'index', colour: '#818cf8' },
  { key: 'pm25', label: 'PM2.5', unit: 'µg/m³', colour: '#f472b6' },
  { key: 'pm10', label: 'PM10', unit: 'µg/m³', colour: '#fbbf24' },
  { key: 'no2', label: 'NO₂', unit: 'µg/m³', colour: '#38bdf8' },
  { key: 'temp_c', label: 'Temperature', unit: '°C', colour: '#fb7185' },
  { key: 'humidity', label: 'Humidity', unit: '%', colour: '#34d399' },
];

export const RANGES = [
  { key: 7, label: '7 days' },
  { key: 14, label: '14 days' },
  { key: 30, label: '30 days' },
  { key: 45, label: '45 days' },
];

export const metricMeta = (key) => METRICS.find((metric) => metric.key === key) ?? METRICS[0];

export const latestDay = (city) => (city?.days?.length ? city.days[city.days.length - 1] : null);

/** Slice a city's series to the last `days` entries for one metric. */
export function series(city, metric = 'aqi', days = 30) {
  if (!city?.days?.length) return [];
  const slice = city.days.slice(-Math.min(days, city.days.length));
  return slice.map((day) => ({
    date: day.date,
    value: Number(day[metric]),
    aqi: day.aqi,
    category: categoryFor(day.aqi),
  }));
}

/** KPI block for the selected city. */
export function summarizeCity(city, window = 7) {
  const latest = latestDay(city);
  if (!latest) return null;
  const aqiSeries = city.days.map((day) => day.aqi);
  const windowSlice = aqiSeries.slice(-window);
  const peak = Math.max(...aqiSeries);
  const peakDay = city.days[aqiSeries.indexOf(peak)];
  const avg = windowSlice.reduce((sum, value) => sum + value, 0) / windowSlice.length;

  return {
    latest,
    category: categoryFor(latest.aqi),
    windowAverage: Number(avg.toFixed(1)),
    peak,
    peakDate: peakDay?.date ?? null,
    worstCategory: categoryFor(peak),
    trend: trend(aqiSeries, window),
    pm25Average: Number(
      (city.days.slice(-window).reduce((sum, day) => sum + day.pm25, 0) / windowSlice.length).toFixed(1),
    ),
  };
}

/** City-vs-city comparison, worst air first. */
export function compareCities(cities, metric = 'aqi', window = 7) {
  return cities
    .map((city) => {
      const values = city.days.slice(-window).map((day) => Number(day[metric]));
      const average = values.reduce((sum, value) => sum + value, 0) / (values.length || 1);
      return {
        id: city.id,
        name: city.name,
        state: city.state,
        average: Number(average.toFixed(1)),
        latest: Number(latestDay(city)?.[metric] ?? 0),
        category: categoryFor(latestDay(city)?.aqi ?? 0),
      };
    })
    .sort((a, b) => b.average - a.average);
}

/** How many days fell in each CPCB band — feeds the distribution bar chart. */
export function categoryDistribution(city, days = 45) {
  const slice = city?.days?.slice(-days) ?? [];
  const buckets = new Map();
  for (const day of slice) {
    const category = categoryFor(day.aqi);
    buckets.set(category.key, {
      category,
      count: (buckets.get(category.key)?.count ?? 0) + 1,
    });
  }
  return [...buckets.values()].sort((a, b) => a.category.max - b.category.max);
}

/**
 * Station search + filters. Returns a filtered, sorted copy.
 * `query` matches the station name or zone, case-insensitively.
 */
export function filterStations(stations, { query = '', zone = 'all', cityId = 'all', maxAqi = null } = {}) {
  const needle = query.trim().toLowerCase();
  return stations
    .filter((station) => (cityId === 'all' ? true : station.cityId === cityId))
    .filter((station) => (zone === 'all' ? true : station.zone === zone))
    .filter((station) => (maxAqi === null ? true : station.aqi <= maxAqi))
    .filter((station) => {
      if (!needle) return true;
      return (
        station.name.toLowerCase().includes(needle) || station.zone.toLowerCase().includes(needle)
      );
    })
    .sort((a, b) => b.aqi - a.aqi);
}

/** Zones available for the selected city — drives the filter dropdown. */
export function zonesFor(stations, cityId) {
  return [...new Set(stations.filter((station) => station.cityId === cityId).map((station) => station.zone))].sort();
}

/** 7-day smoothed AQI for the selected city (used by the sparkline column). */
export function smoothedAqi(city, window = 7) {
  return movingAverage(city?.days?.map((day) => day.aqi) ?? [], window);
}

/** A one-line, human, screen-reader friendly description of the current air. */
export function describeAirA11y(summary) {
  if (!summary) return 'No air quality data available.';
  const { latest, category, trend: cityTrend } = summary;
  const direction =
    cityTrend.direction === 'up' ? 'worsening' : cityTrend.direction === 'down' ? 'improving' : 'stable';
  const change =
    cityTrend.changePct === null ? '' : `, ${Math.abs(cityTrend.changePct)}% versus the previous week`;
  return `Current AQI ${latest.aqi}, ${category.label} (${category.advice}). Air quality is ${direction}${change}.`;
}

/** Sanity guard used by tests and the data adapter. */
export function validateSnapshot(snapshot) {
  const problems = [];
  if (!snapshot || typeof snapshot !== 'object') return ['snapshot is not an object'];
  if (!Array.isArray(snapshot.cities) || snapshot.cities.length === 0) problems.push('no cities');
  for (const city of snapshot.cities ?? []) {
    if (!city.id || !city.name) problems.push(`city missing id/name: ${JSON.stringify(city).slice(0, 40)}`);
    if (!Array.isArray(city.days) || city.days.length < 2) problems.push(`${city.id}: fewer than 2 days`);
    for (const day of city.days ?? []) {
      if (!/^\d{4}-\d{2}-\d{2}$/.test(day.date)) problems.push(`${city.id}: bad date ${day.date}`);
      if (!Number.isFinite(day.pm25) || day.pm25 < 0) problems.push(`${city.id}: bad pm25 on ${day.date}`);
      const expected = aqiFromPm25(day.pm25);
      if (Math.abs(expected - day.aqi) > 1) problems.push(`${city.id}: aqi/pm25 mismatch on ${day.date}`);
    }
  }
  if (!Array.isArray(snapshot.stations) || snapshot.stations.length === 0) problems.push('no stations');
  return problems;
}

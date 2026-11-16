/**
 * CPCB (Central Pollution Control Board) AQI maths.
 *
 * Deliberately implemented from the published Indian breakpoints, not the US EPA
 * ones — they disagree (a PM2.5 of 60 is "Satisfactory" in India, "Moderate" in the
 * US), and mixing them is the most common bug in Indian AQI dashboards.
 *
 * Pure functions only: no DOM, no fetching, so the whole file is unit-tested.
 */

/** PM2.5 breakpoints: [concentration low, high, sub-index low, high]. */
export const PM25_BREAKPOINTS = [
  [0, 30, 0, 50],
  [30, 60, 51, 100],
  [60, 90, 101, 200],
  [90, 120, 201, 300],
  [120, 250, 301, 400],
  [250, 500, 401, 500],
];

/** PM10 breakpoints. */
export const PM10_BREAKPOINTS = [
  [0, 50, 0, 50],
  [50, 100, 51, 100],
  [100, 250, 101, 200],
  [250, 350, 201, 300],
  [350, 430, 301, 400],
  [430, 600, 401, 500],
];

/** NO2 breakpoints (µg/m³). */
export const NO2_BREAKPOINTS = [
  [0, 40, 0, 50],
  [40, 80, 51, 100],
  [80, 180, 101, 200],
  [180, 280, 201, 300],
  [280, 400, 301, 400],
  [400, 600, 401, 500],
];

export const CATEGORIES = [
  { key: 'good', label: 'Good', max: 50, color: '#34d399', advice: 'Air quality is satisfactory; go outside.' },
  { key: 'satisfactory', label: 'Satisfactory', max: 100, color: '#a3e635', advice: 'Minor discomfort possible for very sensitive people.' },
  { key: 'moderate', label: 'Moderate', max: 200, color: '#facc15', advice: 'Sensitive groups should limit prolonged outdoor exertion.' },
  { key: 'poor', label: 'Poor', max: 300, color: '#fb923c', advice: 'Avoid outdoor exercise; consider a mask outdoors.' },
  { key: 'very-poor', label: 'Very Poor', max: 400, color: '#f87171', advice: 'Respiratory illness likely on prolonged exposure. Stay indoors.' },
  { key: 'severe', label: 'Severe', max: Infinity, color: '#b91c1c', advice: 'Health emergency. Avoid all outdoor activity.' },
];

/** Linear interpolation inside a CPCB breakpoint table, clamped at both ends. */
export function subIndex(concentration, breakpoints) {
  const value = Number(concentration);
  if (!Number.isFinite(value) || value < 0) return 0;
  for (const [cLow, cHigh, iLow, iHigh] of breakpoints) {
    if (value >= cLow && value <= cHigh) {
      return Math.round(((iHigh - iLow) / (cHigh - cLow)) * (value - cLow) + iLow);
    }
  }
  const last = breakpoints[breakpoints.length - 1];
  return value > last[1] ? last[3] : 0;
}

export const aqiFromPm25 = (pm25) => subIndex(pm25, PM25_BREAKPOINTS);
export const aqiFromPm10 = (pm10) => subIndex(pm10, PM10_BREAKPOINTS);
export const aqiFromNo2 = (no2) => subIndex(no2, NO2_BREAKPOINTS);

/** AQI is the *worst* sub-index; the pollutant that produced it is the dominant one. */
export function computeAqi({ pm25, pm10, no2 }) {
  const indices = {
    'PM2.5': aqiFromPm25(pm25),
    PM10: aqiFromPm10(pm10),
    NO2: aqiFromNo2(no2),
  };
  let dominant = 'PM2.5';
  for (const [pollutant, value] of Object.entries(indices)) {
    if (value > indices[dominant]) dominant = pollutant;
  }
  return { aqi: indices[dominant], dominant, indices };
}

export function categoryFor(aqi) {
  const value = Number(aqi);
  return CATEGORIES.find((category) => value <= category.max) ?? CATEGORIES[CATEGORIES.length - 1];
}

export const colorFor = (aqi) => categoryFor(aqi).color;

/** Simple trailing mean; ignores null/undefined so gaps do not poison the average. */
export function movingAverage(values, window = 7) {
  if (!Array.isArray(values) || values.length === 0) return [];
  const size = Math.max(1, Math.floor(window));
  return values.map((_, index) => {
    const slice = values.slice(Math.max(0, index - size + 1), index + 1).filter((v) => Number.isFinite(v));
    if (slice.length === 0) return null;
    return Number((slice.reduce((sum, v) => sum + v, 0) / slice.length).toFixed(1));
  });
}

/** Percentage change, safe when the baseline is 0 or missing. */
export function percentChange(current, previous) {
  if (!Number.isFinite(current) || !Number.isFinite(previous) || previous === 0) return null;
  return Number((((current - previous) / previous) * 100).toFixed(1));
}

/**
 * Compare the mean of the last `window` days against the mean of the `window`
 * days before them. Returns { current, previous, changePct, direction }.
 */
export function trend(values, window = 7) {
  if (!Array.isArray(values) || values.length < 2) {
    return { current: null, previous: null, changePct: null, direction: 'flat' };
  }
  const size = Math.min(window, Math.floor(values.length / 2)) || 1;
  const currentSlice = values.slice(-size);
  const previousSlice = values.slice(-size * 2, -size);
  const mean = (arr) => (arr.length ? arr.reduce((sum, v) => sum + v, 0) / arr.length : null);
  const current = mean(currentSlice);
  const previous = mean(previousSlice);
  const changePct = percentChange(current, previous);
  let direction = 'flat';
  if (changePct !== null) direction = changePct > 2 ? 'up' : changePct < -2 ? 'down' : 'flat';
  return { current, previous, changePct, direction };
}

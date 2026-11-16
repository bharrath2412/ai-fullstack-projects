import { describe, expect, it } from 'vitest';
import {
  CATEGORIES,
  aqiFromPm10,
  aqiFromPm25,
  aqiFromNo2,
  categoryFor,
  colorFor,
  computeAqi,
  movingAverage,
  percentChange,
  subIndex,
  trend,
} from '../src/lib/aqi.js';

describe('CPCB sub-index interpolation', () => {
  it('matches the published PM2.5 breakpoints at their edges', () => {
    expect(aqiFromPm25(0)).toBe(0);
    expect(aqiFromPm25(30)).toBe(50);
    expect(aqiFromPm25(60)).toBe(100);
    expect(aqiFromPm25(90)).toBe(200);
    expect(aqiFromPm25(120)).toBe(300);
    expect(aqiFromPm25(250)).toBe(400);
    expect(aqiFromPm25(500)).toBe(500);
  });

  it('interpolates linearly inside a band', () => {
    // 45 µg/m³ sits halfway through 30-60 → halfway through 51-100
    expect(aqiFromPm25(45)).toBe(76);
  });

  it('clamps above the table and rejects junk input', () => {
    expect(aqiFromPm25(1200)).toBe(500);
    expect(aqiFromPm25(-5)).toBe(0);
    expect(aqiFromPm25('abc')).toBe(0);
    expect(subIndex(NaN, [[0, 10, 0, 10]])).toBe(0);
  });

  it('handles PM10 and NO2 tables', () => {
    expect(aqiFromPm10(50)).toBe(50);
    expect(aqiFromPm10(100)).toBe(100);
    expect(aqiFromNo2(40)).toBe(50);
    expect(aqiFromNo2(80)).toBe(100);
  });
});

describe('computeAqi', () => {
  it('takes the worst sub-index and names that pollutant', () => {
    const result = computeAqi({ pm25: 20, pm10: 300, no2: 40 });
    expect(result.dominant).toBe('PM10');
    expect(result.aqi).toBe(result.indices.PM10);
    expect(result.aqi).toBeGreaterThan(result.indices['PM2.5']);
  });

  it('defaults to PM2.5 when everything is clean', () => {
    const result = computeAqi({ pm25: 15, pm10: 20, no2: 10 });
    expect(result.dominant).toBe('PM2.5');
    expect(result.aqi).toBe(aqiFromPm25(15));
  });
});

describe('categories', () => {
  it('maps every band boundary to the right label', () => {
    expect(categoryFor(0).label).toBe('Good');
    expect(categoryFor(50).label).toBe('Good');
    expect(categoryFor(51).label).toBe('Satisfactory');
    expect(categoryFor(100).label).toBe('Satisfactory');
    expect(categoryFor(101).label).toBe('Moderate');
    expect(categoryFor(200).label).toBe('Moderate');
    expect(categoryFor(201).label).toBe('Poor');
    expect(categoryFor(301).label).toBe('Very Poor');
    expect(categoryFor(401).label).toBe('Severe');
    expect(categoryFor(9999).label).toBe('Severe');
  });

  it('exposes a colour and advice for every band', () => {
    for (const category of CATEGORIES) {
      expect(category.color).toMatch(/^#[0-9a-f]{6}$/i);
      expect(category.advice.length).toBeGreaterThan(10);
    }
    expect(colorFor(350)).toBe('#f87171');
  });
});

describe('time-series helpers', () => {
  it('smooths with a trailing window and ignores gaps', () => {
    expect(movingAverage([10, 20, 30], 2)).toEqual([10, 15, 25]);
    expect(movingAverage([10, null, 30], 2)).toEqual([10, 10, 30]);
    expect(movingAverage([], 3)).toEqual([]);
  });

  it('computes percentage change safely', () => {
    expect(percentChange(120, 100)).toBe(20);
    expect(percentChange(80, 100)).toBe(-20);
    expect(percentChange(10, 0)).toBeNull();
    expect(percentChange(undefined, 5)).toBeNull();
  });

  it('compares the last window against the previous one', () => {
    const rising = trend([100, 100, 100, 100, 150, 150, 150, 150], 4);
    expect(rising.current).toBe(150);
    expect(rising.previous).toBe(100);
    expect(rising.direction).toBe('up');
    expect(rising.changePct).toBe(50);

    const falling = trend([200, 200, 200, 200, 100, 100, 100, 100], 4);
    expect(falling.direction).toBe('down');

    const flat = trend([50, 50, 50, 50], 2);
    expect(flat.direction).toBe('flat');

    expect(trend([], 7).direction).toBe('flat');
  });
});

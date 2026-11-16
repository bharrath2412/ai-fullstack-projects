#!/usr/bin/env node
/**
 * Deterministic snapshot generator for AirGrid.
 *
 * Public CPCB feeds (data.gov.in) need a free API key, are rate-limited and are
 * occasionally down — none of which should make a demo or CI flaky. So the app
 * ships with a *reproducible* 45-day snapshot shaped exactly like the live feed,
 * plus a live adapter that slots in when VITE_DATA_GOV_KEY is present.
 *
 *   npm run data        # regenerates src/data/air-quality.json
 *
 * The numbers are synthetic but not arbitrary: each city has a baseline AQI, a
 * seasonal curve (winter inversion in the north, monsoon washout on the coast),
 * weekday traffic and a festival spike for Delhi. That keeps the charts honest
 * enough to be worth building, without pretending to be real observations.
 */
import { writeFileSync, mkdirSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const OUT = resolve(here, '../src/data/air-quality.json');

const DAYS = 45;
const END_DATE = new Date('2026-11-16T00:00:00Z');

/** Mulberry32 — tiny deterministic PRNG so the snapshot is byte-identical everywhere. */
function rng(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const CITIES = [
  {
    id: 'chennai',
    name: 'Chennai',
    state: 'Tamil Nadu',
    stateCode: 'TN',
    base: 62,
    monsoonDip: 18, // NE monsoon washes particulates out
    temp: 29.5,
    humidity: 76,
    zones: ['Adyar', 'Anna Nagar', 'T. Nagar', 'Velachery', 'Manali'],
  },
  {
    id: 'delhi',
    name: 'Delhi',
    state: 'Delhi',
    stateCode: 'DL',
    base: 168,
    monsoonDip: 55,
    winterSpike: 110, // stubble burning + inversion from late October
    temp: 21.0,
    humidity: 58,
    zones: ['Anand Vihar', 'RK Puram', 'Punjabi Bagh', 'Okhla', 'Dwarka'],
  },
  {
    id: 'bengaluru',
    name: 'Bengaluru',
    state: 'Karnataka',
    stateCode: 'KA',
    base: 74,
    monsoonDip: 26,
    temp: 24.5,
    humidity: 68,
    zones: ['Jayanagar', 'Whitefield', 'Hebbal', 'Silk Board', 'Peenya'],
  },
  {
    id: 'mumbai',
    name: 'Mumbai',
    state: 'Maharashtra',
    stateCode: 'MH',
    base: 96,
    monsoonDip: 34,
    temp: 30.2,
    humidity: 79,
    zones: ['Bandra', 'Sion', 'Colaba', 'Andheri', 'Worli'],
  },
  {
    id: 'hyderabad',
    name: 'Hyderabad',
    state: 'Telangana',
    stateCode: 'TG',
    base: 84,
    monsoonDip: 22,
    temp: 27.8,
    humidity: 63,
    zones: ['Bollaram', 'Sanathnagar', 'Ameerpet', 'Kukatpally', 'Charminar'],
  },
];

const PM25_SUB_INDEX = [
  [0, 30, 0, 50],
  [30, 60, 51, 100],
  [60, 90, 101, 200],
  [90, 120, 201, 300],
  [120, 250, 301, 400],
  [250, 500, 401, 500],
];

function aqiFromPm25(pm25) {
  const value = Math.max(0, Math.min(pm25, 499.9));
  for (const [cLow, cHigh, iLow, iHigh] of PM25_SUB_INDEX) {
    if (value >= cLow && value <= cHigh) {
      return Math.round(((iHigh - iLow) / (cHigh - cLow)) * (value - cLow) + iLow);
    }
  }
  return 500;
}

function isoDate(offsetFromEnd) {
  const date = new Date(END_DATE.getTime() - offsetFromEnd * 86_400_000);
  return date.toISOString().slice(0, 10);
}

const cities = CITIES.map((city, cityIndex) => {
  const random = rng(1000 + cityIndex * 137);
  const days = [];

  for (let i = 0; i < DAYS; i += 1) {
    const offset = DAYS - 1 - i; // 0 = oldest
    const date = isoDate(offset);
    const dayOfWeek = new Date(`${date}T00:00:00Z`).getUTCDay();

    // Seasonal position: Nov sits at the end of the monsoon, start of winter.
    const seasonal = Math.cos(((offset + 8) / DAYS) * Math.PI * 2); // 1 at the ends
    const monsoon = Math.max(0, seasonal) * city.monsoonDip;
    const winter = city.winterSpike ? Math.max(0, -seasonal) * city.winterSpike : 0;
    const weekend = dayOfWeek === 0 || dayOfWeek === 6 ? -9 : 3;
    const festival = city.id === 'delhi' && offset >= 6 && offset <= 8 ? 240 - (offset - 6) * 60 : 0;
    const noise = (random() - 0.5) * 26;

    const pm25 = Math.max(8, city.base + winter - monsoon + weekend + festival + noise);
    const pm10 = pm25 * (1.55 + random() * 0.4);
    const no2 = 18 + pm25 * 0.28 + random() * 12;
    const temp = city.temp - seasonal * 3.2 + (random() - 0.5) * 2.4;
    const humidity = Math.min(97, Math.max(28, city.humidity + monsoon * 0.25 + (random() - 0.5) * 12));

    days.push({
      date,
      aqi: aqiFromPm25(pm25),
      pm25: Number(pm25.toFixed(1)),
      pm10: Number(pm10.toFixed(1)),
      no2: Number(no2.toFixed(1)),
      temp_c: Number(temp.toFixed(1)),
      humidity: Math.round(humidity),
    });
  }

  const stations = city.zones.map((zone, zoneIndex) => {
    const last = days[days.length - 1];
    const drift = 0.72 + rng(cityIndex * 50 + zoneIndex)() * 0.62; // 0.72 - 1.34
    const stationPm25 = Number((last.pm25 * drift).toFixed(1));
    return {
      id: `${city.id}-${zone.toLowerCase().replace(/[^a-z]+/g, '-')}`,
      name: `${zone}, ${city.name}`,
      cityId: city.id,
      zone,
      aqi: aqiFromPm25(stationPm25),
      pm25: stationPm25,
      dominant: stationPm25 > 90 ? 'PM2.5' : 'PM10',
      lastUpdated: `${last.date}T09:00:00+05:30`,
    };
  });

  return {
    id: city.id,
    name: city.name,
    state: city.state,
    stateCode: city.stateCode,
    lat: null,
    lon: null,
    days,
    stations,
  };
});

const payload = {
  schemaVersion: 1,
  source: 'synthetic-snapshot',
  // Deterministic on purpose: the snapshot's timestamp is the end of its own series,
  // not the wall clock when it was generated. That makes regeneration byte-identical,
  // which is what the CI diff check enforces.
  generatedAt: END_DATE.toISOString(),
  windowDays: DAYS,
  units: { aqi: 'CPCB index', pm25: 'µg/m³', pm10: 'µg/m³', no2: 'µg/m³', temp_c: '°C', humidity: '%' },
  cities,
  stations: cities.flatMap((city) => city.stations),
};

mkdirSync(dirname(OUT), { recursive: true });
writeFileSync(OUT, `${JSON.stringify(payload, null, 2)}\n`);

const summary = cities
  .map((city) => {
    const last = city.days[city.days.length - 1];
    return `${city.name.padEnd(11)} AQI ${String(last.aqi).padStart(3)}  PM2.5 ${last.pm25}`;
  })
  .join('\n');
console.log(`Wrote ${OUT}\n${cities.length} cities × ${DAYS} days\n\n${summary}`);

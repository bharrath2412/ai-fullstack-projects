import { useEffect, useMemo, useState } from 'react';
import { loadDashboard } from './data/source.js';
import { CATEGORIES, categoryFor, colorFor } from './lib/aqi.js';
import {
  METRICS,
  RANGES,
  categoryDistribution,
  compareCities,
  describeAirA11y,
  filterStations,
  latestDay,
  metricMeta,
  series,
  summarizeCity,
  zonesFor,
} from './lib/analytics.js';
import LineChart from './components/LineChart.jsx';
import CompareBars from './components/CompareBars.jsx';
import StationTable from './components/StationTable.jsx';

const initialCityFromUrl = () => {
  const param = new URLSearchParams(window.location.search).get('city');
  return param || 'chennai';
};

export default function App() {
  const [payload, setPayload] = useState(null);
  const [cityId, setCityId] = useState(initialCityFromUrl);
  const [metric, setMetric] = useState('aqi');
  const [range, setRange] = useState(30);
  const [query, setQuery] = useState('');
  const [zone, setZone] = useState('all');
  const [online, setOnline] = useState(navigator.onLine);
  const [installEvent, setInstallEvent] = useState(null);
  const [loading, setLoading] = useState(true);

  // ---- data ---------------------------------------------------------------
  useEffect(() => {
    let cancelled = false;
    loadDashboard().then((data) => {
      if (!cancelled) {
        setPayload(data);
        setLoading(false);
      }
    });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const on = () => setOnline(true);
    const off = () => setOnline(false);
    window.addEventListener('online', on);
    window.addEventListener('offline', off);
    return () => {
      window.removeEventListener('online', on);
      window.removeEventListener('offline', off);
    };
  }, []);

  useEffect(() => {
    const handler = (event) => {
      event.preventDefault();
      setInstallEvent(event);
    };
    window.addEventListener('beforeinstallprompt', handler);
    return () => window.removeEventListener('beforeinstallprompt', handler);
  }, []);

  const cities = payload?.cities ?? [];
  const city = cities.find((item) => item.id === cityId) ?? cities[0] ?? null;
  const meta = metricMeta(metric);

  const summary = useMemo(() => (city ? summarizeCity(city, 7) : null), [city]);
  const points = useMemo(() => (city ? series(city, metric, range) : []), [city, metric, range]);
  const comparison = useMemo(() => (cities.length ? compareCities(cities, 'aqi', 7) : []), [cities]);
  const distribution = useMemo(() => (city ? categoryDistribution(city, range) : []), [city, range]);
  const zones = useMemo(() => (payload ? zonesFor(payload.stations, cityId) : []), [payload, cityId]);
  const stations = useMemo(
    () => (payload ? filterStations(payload.stations, { query, zone, cityId }) : []),
    [payload, query, zone, cityId],
  );

  const selectCity = (id) => {
    setCityId(id);
    setZone('all');
    const url = new URL(window.location.href);
    url.searchParams.set('city', id);
    window.history.replaceState({}, '', url);
  };

  if (loading || !city) {
    return (
      <div className="boot">
        <div className="spinner" />
        <p>Loading AirGrid…</p>
      </div>
    );
  }

  const latest = latestDay(city);
  const category = categoryFor(latest.aqi);
  const a11ySummary = describeAirA11y(summary);

  return (
    <>
      <a className="skip-link" href="#main">
        Skip to dashboard
      </a>

      <header className="topbar">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">AG</span>
          <div>
            <h1>AirGrid</h1>
            <p className="muted">CPCB air quality · Chennai, Delhi, Bengaluru, Mumbai, Hyderabad</p>
          </div>
        </div>

        <div className="topbar-right">
          <span className={`badge ${online ? '' : 'warn'}`} role="status">
            {online ? 'Online' : 'Offline · cached data'}
          </span>
          <span className="badge">{payload.mode === 'live' ? 'Live feed' : 'Snapshot'}</span>
          {installEvent && (
            <button
              className="btn primary small"
              onClick={async () => {
                installEvent.prompt();
                await installEvent.userChoice;
                setInstallEvent(null);
              }}
            >
              Install app
            </button>
          )}
        </div>
      </header>

      {payload.warning && (
        <p className="notice" role="status">
          {payload.warning}
        </p>
      )}

      <main id="main">
        <nav className="city-tabs" aria-label="Choose a city">
          {cities.map((item) => {
            const itemLatest = latestDay(item);
            const itemCategory = categoryFor(itemLatest.aqi);
            return (
              <button
                key={item.id}
                className={`city-tab ${item.id === cityId ? 'active' : ''}`}
                onClick={() => selectCity(item.id)}
                aria-pressed={item.id === cityId}
              >
                <span className="dot" style={{ background: itemCategory.color }} />
                <span className="city-name">{item.name}</span>
                <span className="city-aqi">{itemLatest.aqi}</span>
              </button>
            );
          })}
        </nav>

        <section className="hero" aria-labelledby="hero-heading" style={{ '--band': category.color }}>
          <div className="hero-main">
            <h2 className="eyebrow" id="hero-heading">
              {city.name}, {city.state} · {latest.date}
            </h2>
            <p className="hero-aqi">
              {latest.aqi}
              <span className="hero-unit">AQI</span>
            </p>
            <p className="hero-band">{category.label}</p>
            <p className="hero-advice">{category.advice}</p>
            <p className="visually-hidden">{a11ySummary}</p>
          </div>

          <dl className="hero-stats">
            <div>
              <dt>PM2.5</dt>
              <dd>{latest.pm25} <small>µg/m³</small></dd>
            </div>
            <div>
              <dt>PM10</dt>
              <dd>{latest.pm10} <small>µg/m³</small></dd>
            </div>
            <div>
              <dt>7-day mean</dt>
              <dd>{summary.windowAverage}</dd>
            </div>
            <div>
              <dt>Peak</dt>
              <dd>
                {summary.peak} <small>{summary.peakDate?.slice(5)}</small>
              </dd>
            </div>
            <div>
              <dt>vs last week</dt>
              <dd className={summary.trend.direction}>
                {summary.trend.changePct === null
                  ? '—'
                  : `${summary.trend.changePct > 0 ? '+' : ''}${summary.trend.changePct}%`}
              </dd>
            </div>
            <div>
              <dt>Temp / humidity</dt>
              <dd>
                {latest.temp_c}° <small>{latest.humidity}%</small>
              </dd>
            </div>
          </dl>
        </section>

        <section className="panel" aria-labelledby="trend-heading">
          <header className="panel-head wrap">
            <h2 id="trend-heading">{meta.label} trend</h2>
            <div className="controls">
              <div className="segmented" role="group" aria-label="Metric">
                {METRICS.map((item) => (
                  <button
                    key={item.key}
                    className={metric === item.key ? 'active' : ''}
                    onClick={() => setMetric(item.key)}
                    aria-pressed={metric === item.key}
                  >
                    {item.label}
                  </button>
                ))}
              </div>
              <div className="segmented" role="group" aria-label="Range">
                {RANGES.map((item) => (
                  <button
                    key={item.key}
                    className={range === item.key ? 'active' : ''}
                    onClick={() => setRange(item.key)}
                    aria-pressed={range === item.key}
                  >
                    {item.label}
                  </button>
                ))}
              </div>
            </div>
          </header>

          <LineChart points={points} metric={metric} label={meta.label} unit={meta.unit} />

          <details className="data-table">
            <summary>View as table ({points.length} rows)</summary>
            <div className="table-wrap">
              <table>
                <caption className="visually-hidden">{meta.label} by day for {city.name}</caption>
                <thead>
                  <tr>
                    <th scope="col">Date</th>
                    <th scope="col">AQI</th>
                    <th scope="col">Band</th>
                    <th scope="col">{meta.label}</th>
                  </tr>
                </thead>
                <tbody>
                  {points.slice().reverse().map((point) => (
                    <tr key={point.date}>
                      <td>{point.date}</td>
                      <td>{point.aqi}</td>
                      <td style={{ color: point.category.color }}>{point.category.label}</td>
                      <td>{point.value}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
        </section>

        <div className="grid-2">
          <section className="panel" aria-labelledby="compare-heading">
            <header className="panel-head">
              <h2 id="compare-heading">City comparison</h2>
            </header>
            <CompareBars rows={comparison} selectedId={cityId} onSelect={selectCity} metricLabel="AQI" />
          </section>

          <section className="panel" aria-labelledby="bands-heading">
            <header className="panel-head">
              <h2 id="bands-heading">Days per CPCB band</h2>
              <span className="pill">last {range} days</span>
            </header>
            <ul className="band-list">
              {distribution.map(({ category: band, count }) => {
                const share = Math.round((count / range) * 100);
                return (
                  <li key={band.key}>
                    <span className="band-label">
                      <span className="dot" style={{ background: band.color }} />
                      {band.label}
                    </span>
                    <span className="band-track" aria-hidden="true">
                      <span className="band-fill" style={{ width: `${share}%`, background: band.color }} />
                    </span>
                    <span className="band-count">
                      {count}d · {share}%
                    </span>
                  </li>
                );
              })}
            </ul>
            <details className="legend">
              <summary>CPCB AQI bands</summary>
              <ul>
                {CATEGORIES.map((band) => (
                  <li key={band.key}>
                    <span className="dot" style={{ background: band.color }} />
                    <strong>{band.label}</strong> — {band.advice}
                  </li>
                ))}
              </ul>
            </details>
          </section>
        </div>

        <StationTable
          stations={stations}
          query={query}
          onQueryChange={setQuery}
          zone={zone}
          zones={zones}
          onZoneChange={setZone}
          cityName={city.name}
        />
      </main>

      <footer className="footer">
        <p>
          Data: bundled CPCB-shaped reference series (deterministic) · live mode via{' '}
          <code>data.gov.in</code> when <code>VITE_DATA_GOV_KEY</code> is set. AQI computed from
          CPCB breakpoints.
        </p>
        <p className="muted">
          Installable PWA · works offline · {payload.generatedAt?.slice(0, 10)} snapshot
        </p>
      </footer>
    </>
  );
}

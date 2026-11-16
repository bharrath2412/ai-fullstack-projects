import { useMemo, useState } from 'react';
import { colorFor } from '../lib/aqi.js';

/**
 * Dependency-free SVG line chart.
 *
 * - responsive via viewBox, so no ResizeObserver and no layout thrash
 * - keyboard accessible: arrow keys move a focusable point readout
 * - every point has a <title>, and the whole figure has an aria-label summary
 */
export default function LineChart({ points, metric, label, unit }) {
  const [active, setActive] = useState(null);
  const width = 760;
  const height = 280;
  const padding = { top: 18, right: 16, bottom: 34, left: 48 };

  const geometry = useMemo(() => {
    if (!points?.length) return null;
    const values = points.map((point) => point.value).filter((value) => Number.isFinite(value));
    if (!values.length) return null;

    const min = Math.min(...values);
    const max = Math.max(...values);
    const span = max - min || 1;
    const innerWidth = width - padding.left - padding.right;
    const innerHeight = height - padding.top - padding.bottom;

    const x = (index) => padding.left + (index / Math.max(1, points.length - 1)) * innerWidth;
    const y = (value) => padding.top + innerHeight - ((value - min) / span) * innerHeight;

    const path = points.map((point, index) => `${index === 0 ? 'M' : 'L'}${x(index).toFixed(1)},${y(point.value).toFixed(1)}`).join(' ');
    const area = `${path} L${x(points.length - 1).toFixed(1)},${(height - padding.bottom).toFixed(1)} L${padding.left},${(height - padding.bottom).toFixed(1)} Z`;

    // Four gridlines, rounded to something readable.
    const ticks = Array.from({ length: 4 }, (_, i) => {
      const value = min + (span * i) / 3;
      return { value, y: y(value) };
    });

    return { x, y, path, area, min, max, ticks, innerWidth, innerHeight };
  }, [points, metric]);

  if (!geometry) {
    return <p className="chart-empty">No data for this range.</p>;
  }

  const activePoint = active !== null ? points[active] : null;
  const summary = `Line chart of ${label} over ${points.length} days. Minimum ${Math.round(geometry.min)}${unit === 'index' ? '' : ` ${unit}`}, maximum ${Math.round(geometry.max)}${unit === 'index' ? '' : ` ${unit}`}.`;

  const move = (delta) => {
    setActive((current) => {
      const next = current === null ? points.length - 1 : current + delta;
      return Math.max(0, Math.min(points.length - 1, next));
    });
  };

  return (
    <figure className="chart" aria-label={summary}>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label={summary}
        tabIndex={0}
        onKeyDown={(event) => {
          if (event.key === 'ArrowRight') { event.preventDefault(); move(1); }
          if (event.key === 'ArrowLeft') { event.preventDefault(); move(-1); }
          if (event.key === 'Escape') setActive(null);
        }}
        onBlur={() => setActive(null)}
      >
        <defs>
          <linearGradient id="areaFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="rgba(129,140,248,0.35)" />
            <stop offset="100%" stopColor="rgba(129,140,248,0.02)" />
          </linearGradient>
        </defs>

        {geometry.ticks.map((tick) => (
          <g key={tick.value}>
            <line
              x1={padding.left}
              x2={width - padding.right}
              y1={tick.y}
              y2={tick.y}
              stroke="rgba(148,163,184,0.16)"
              strokeDasharray="4 4"
            />
            <text x={padding.left - 8} y={tick.y + 3} textAnchor="end" className="axis">
              {Math.round(tick.value)}
            </text>
          </g>
        ))}

        <path d={geometry.area} fill="url(#areaFill)" />
        <path d={geometry.path} fill="none" stroke="#818cf8" strokeWidth="2.5" strokeLinejoin="round" />

        {points.map((point, index) => (
          <g key={point.date}>
            <circle
              cx={geometry.x(index)}
              cy={geometry.y(point.value)}
              r={active === index ? 5 : 2.6}
              fill={metric === 'aqi' ? colorFor(point.aqi) : '#c7d2fe'}
              stroke={active === index ? '#fff' : 'none'}
              strokeWidth="1.5"
            >
              <title>{`${point.date}: ${point.value}${unit === 'index' ? '' : ` ${unit}`}`}</title>
            </circle>
            {/* Invisible hit area — 22px is a comfortable touch target. */}
            <rect
              x={geometry.x(index) - 10}
              y={padding.top}
              width="20"
              height={geometry.innerHeight}
              fill="transparent"
              onMouseEnter={() => setActive(index)}
              onMouseLeave={() => setActive(null)}
              onFocus={() => setActive(index)}
              tabIndex={-1}
            />
          </g>
        ))}

        {[0, Math.floor(points.length / 2), points.length - 1].map((index) => (
          <text key={index} x={geometry.x(index)} y={height - 12} textAnchor="middle" className="axis">
            {points[index].date.slice(5)}
          </text>
        ))}
      </svg>

      <figcaption>
        {activePoint ? (
          <span>
            <strong>{activePoint.date}</strong> · {activePoint.value}
            {unit === 'index' ? '' : ` ${unit}`}
            {metric === 'aqi' ? ` · ${activePoint.category.label}` : ''}
          </span>
        ) : (
          <span className="muted">
            {label} · last {points.length} days. Use ← → to inspect values.
          </span>
        )}
      </figcaption>
    </figure>
  );
}

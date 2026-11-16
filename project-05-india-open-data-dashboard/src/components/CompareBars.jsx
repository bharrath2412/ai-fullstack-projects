import { colorFor } from '../lib/aqi.js';

/** Horizontal comparison bars — one row per city, worst first. */
export default function CompareBars({ rows, selectedId, onSelect, metricLabel }) {
  const peak = Math.max(...rows.map((row) => row.average), 1);

  return (
    <ul className="compare">
      {rows.map((row) => {
        const width = Math.max(4, (row.average / peak) * 100);
        return (
          <li key={row.id}>
            <button
              className={`compare-row ${row.id === selectedId ? 'selected' : ''}`}
              onClick={() => onSelect(row.id)}
              aria-pressed={row.id === selectedId}
            >
              <span className="compare-label">
                <span className="dot" style={{ background: colorFor(row.latest) }} />
                {row.name}
              </span>
              <span className="compare-track">
                <span
                  className="compare-fill"
                  style={{ width: `${width}%`, background: colorFor(row.latest) }}
                />
              </span>
              <span className="compare-value">{Math.round(row.average)}</span>
            </button>
          </li>
        );
      })}
      <li className="compare-note muted">7-day mean {metricLabel}</li>
    </ul>
  );
}

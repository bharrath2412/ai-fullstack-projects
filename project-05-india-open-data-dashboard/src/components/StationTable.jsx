import { categoryFor } from '../lib/aqi.js';

/** Station-level table: searchable, sortable by AQI, keyboard friendly. */
export default function StationTable({ stations, query, onQueryChange, zone, zones, onZoneChange, cityName }) {
  return (
    <section className="panel" aria-labelledby="stations-heading">
      <header className="panel-head">
        <h2 id="stations-heading">Monitoring stations</h2>
        <span className="pill">{stations.length} shown</span>
      </header>

      <div className="station-controls">
        <label className="visually-hidden" htmlFor="station-search">
          Search stations in {cityName}
        </label>
        <input
          id="station-search"
          className="input"
          type="search"
          placeholder={`Search stations in ${cityName}…`}
          value={query}
          onChange={(event) => onQueryChange(event.target.value)}
        />
        <label className="visually-hidden" htmlFor="zone-filter">
          Filter by zone
        </label>
        <select
          id="zone-filter"
          className="input"
          value={zone}
          onChange={(event) => onZoneChange(event.target.value)}
        >
          <option value="all">All zones</option>
          {zones.map((zoneName) => (
            <option key={zoneName} value={zoneName}>
              {zoneName}
            </option>
          ))}
        </select>
      </div>

      {stations.length === 0 ? (
        <p className="muted" role="status">
          No stations match that search.
        </p>
      ) : (
        <div className="table-wrap">
          <table>
            <caption className="visually-hidden">
              Monitoring stations in {cityName}, sorted by AQI (worst first)
            </caption>
            <thead>
              <tr>
                <th scope="col">Station</th>
                <th scope="col">Zone</th>
                <th scope="col">AQI</th>
                <th scope="col">Band</th>
                <th scope="col">Dominant</th>
              </tr>
            </thead>
            <tbody>
              {stations.map((station) => {
                const category = categoryFor(station.aqi);
                return (
                  <tr key={station.id}>
                    <td>{station.name.split(',')[0]}</td>
                    <td className="muted">{station.zone}</td>
                    <td>
                      <span className="aqi-badge" style={{ background: `${category.color}22`, color: category.color }}>
                        {station.aqi}
                      </span>
                    </td>
                    <td style={{ color: category.color }}>{category.label}</td>
                    <td className="muted">{station.dominant}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

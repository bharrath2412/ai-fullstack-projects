/**
 * Delivery dashboard: KPI cards, a 14-day completion bar chart (pure SVG, no
 * chart library) and per-project progress bars.
 */
function StatCard({ label, value, sub, tone = '' }) {
  return (
    <div className={`stat-card ${tone}`}>
      <span className="stat-label">{label}</span>
      <strong className="stat-value">{value}</strong>
      {sub && <span className="stat-sub">{sub}</span>}
    </div>
  );
}

function CompletionChart({ data }) {
  const max = Math.max(1, ...data.map((d) => d.completed));
  const width = 560;
  const height = 180;
  const padX = 24;
  const barGap = 6;
  const barWidth = (width - padX * 2) / data.length - barGap;

  return (
    <svg
      className="chart"
      viewBox={`0 0 ${width} ${height + 26}`}
      role="img"
      aria-label="Tasks completed per day over the last 14 days"
    >
      {[0.25, 0.5, 0.75, 1].map((f) => (
        <line
          key={f}
          x1={padX}
          x2={width - padX}
          y1={height - height * f}
          y2={height - height * f}
          stroke="rgba(148,163,184,0.18)"
          strokeDasharray="4 4"
        />
      ))}
      {data.map((d, i) => {
        const barHeight = (d.completed / max) * (height - 20);
        const x = padX + i * (barWidth + barGap);
        return (
          <g key={d.day}>
            <rect
              x={x}
              y={height - barHeight}
              width={barWidth}
              height={Math.max(barHeight, d.completed > 0 ? 3 : 0)}
              rx={4}
              fill="url(#barGradient)"
            >
              <title>{`${d.day}: ${d.completed} completed`}</title>
            </rect>
            <text x={x + barWidth / 2} y={height + 18} textAnchor="middle" className="axis">
              {d.day.slice(8)}
            </text>
          </g>
        );
      })}
      <defs>
        <linearGradient id="barGradient" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#818cf8" />
          <stop offset="100%" stopColor="#4f46e5" />
        </linearGradient>
      </defs>
    </svg>
  );
}

export default function Dashboard({ stats, projects, onOpenProject }) {
  if (!stats) {
    return <p className="muted">Loading dashboard…</p>;
  }

  const { totals, completionsByDay, perProject } = stats;
  const last7 = completionsByDay.slice(-7).reduce((n, d) => n + d.completed, 0);

  return (
    <div className="dashboard">
      <div className="stat-grid">
        <StatCard label="Total tasks" value={totals.total} sub={`${projects.length} projects`} />
        <StatCard label="Completed" value={totals.done} sub={`${totals.completionRate}% of all tasks`} tone="good" />
        <StatCard label="In progress" value={totals.inProgress} sub={`${totals.todo} still to do`} tone="info" />
        <StatCard label="Overdue" value={totals.overdue} sub={`${totals.highPriorityOpen} high priority open`} tone={totals.overdue ? 'bad' : ''} />
      </div>

      <div className="dashboard-grid">
        <section className="panel">
          <header className="panel-head">
            <h2>Completed per day</h2>
            <span className="pill">{last7} in the last 7 days</span>
          </header>
          <CompletionChart data={completionsByDay} />
        </section>

        <section className="panel">
          <header className="panel-head">
            <h2>Progress by project</h2>
          </header>
          <ul className="project-progress">
            {perProject.map((p) => {
              const pct = p.total ? Math.round((p.done / p.total) * 100) : 0;
              return (
                <li key={p.id}>
                  <button className="progress-row" onClick={() => onOpenProject(p.id)}>
                    <span className="progress-top">
                      <span className="dot" style={{ background: p.color }} />
                      <span className="project-name">{p.name}</span>
                      <span className="muted small">
                        {p.done}/{p.total}
                      </span>
                    </span>
                    <span className="bar">
                      <span
                        className="bar-fill"
                        style={{ width: `${pct}%`, background: p.color }}
                      />
                    </span>
                  </button>
                </li>
              );
            })}
            {perProject.length === 0 && <li className="muted">No projects yet.</li>}
          </ul>
        </section>
      </div>

      <section className="panel">
        <header className="panel-head">
          <h2>Status split</h2>
        </header>
        <div className="status-split">
          {[
            ['To do', stats.byStatus.todo, '#64748b'],
            ['In progress', stats.byStatus.in_progress, '#0ea5e9'],
            ['Done', stats.byStatus.done, '#10b981'],
          ].map(([label, value, color]) => (
            <div key={label} className="split-item">
              <span className="dot" style={{ background: color }} />
              <span>{label}</span>
              <strong>{value}</strong>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}

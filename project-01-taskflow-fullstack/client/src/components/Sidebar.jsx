import { useState } from 'react';

const PALETTE = ['#6366f1', '#0ea5e9', '#10b981', '#f59e0b', '#ef4444', '#a855f7'];

export default function Sidebar({
  projects,
  activeProjectId,
  onSelect,
  onCreate,
  onDelete,
  user,
  onLogout,
  stats,
}) {
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ name: '', description: '', color: PALETTE[0] });

  const submit = async (event) => {
    event.preventDefault();
    if (!form.name.trim()) return;
    await onCreate(form);
    setForm({ name: '', description: '', color: PALETTE[0] });
    setShowForm(false);
  };

  return (
    <aside className="sidebar">
      <div className="brand">
        <span className="brand-mark">TF</span>
        <div>
          <strong>TaskFlow</strong>
          <small>{stats?.totals.total ?? 0} tasks tracked</small>
        </div>
      </div>

      <nav className="project-list">
        <button
          className={`project-item ${activeProjectId === 'all' ? 'active' : ''}`}
          onClick={() => onSelect('all')}
        >
          <span className="dot" style={{ background: '#94a3b8' }} />
          <span className="project-name">All tasks</span>
          <span className="count">{stats?.totals.total ?? projects.reduce((n, p) => n + p.taskCount, 0)}</span>
        </button>

        {projects.map((project) => (
          <div key={project.id} className={`project-row ${activeProjectId === project.id ? 'active' : ''}`}>
            <button className="project-item" onClick={() => onSelect(project.id)}>
              <span className="dot" style={{ background: project.color }} />
              <span className="project-name">{project.name}</span>
              <span className="count">{project.taskCount}</span>
            </button>
            <button
              className="icon-btn danger"
              title="Delete project"
              aria-label={`Delete ${project.name}`}
              onClick={() => onDelete(project.id)}
            >
              ×
            </button>
          </div>
        ))}
      </nav>

      {showForm ? (
        <form className="project-form" onSubmit={submit}>
          <input
            className="input"
            placeholder="Project name"
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            autoFocus
            required
            maxLength={80}
          />
          <input
            className="input"
            placeholder="Short description"
            value={form.description}
            onChange={(e) => setForm({ ...form, description: e.target.value })}
            maxLength={500}
          />
          <div className="swatches">
            {PALETTE.map((color) => (
              <button
                type="button"
                key={color}
                aria-label={`Colour ${color}`}
                className={`swatch ${form.color === color ? 'selected' : ''}`}
                style={{ background: color }}
                onClick={() => setForm({ ...form, color })}
              />
            ))}
          </div>
          <div className="row">
            <button className="btn primary small">Create</button>
            <button type="button" className="btn ghost small" onClick={() => setShowForm(false)}>
              Cancel
            </button>
          </div>
        </form>
      ) : (
        <button className="btn dashed" onClick={() => setShowForm(true)}>
          + New project
        </button>
      )}

      <div className="user-box">
        <div className="avatar">{user.name.slice(0, 1).toUpperCase()}</div>
        <div className="user-meta">
          <strong>{user.name}</strong>
          <small>{user.email}</small>
        </div>
        <button className="btn ghost small" onClick={onLogout}>
          Sign out
        </button>
      </div>
    </aside>
  );
}

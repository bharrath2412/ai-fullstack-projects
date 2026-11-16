import { useState } from 'react';
import TaskCard from './TaskCard.jsx';

const COLUMNS = [
  { key: 'todo', label: 'To do', accent: '#64748b' },
  { key: 'in_progress', label: 'In progress', accent: '#0ea5e9' },
  { key: 'done', label: 'Done', accent: '#10b981' },
];

export default function Board({ grouped, projects, activeProjectId, onCreate, onMove, onEdit, onDelete }) {
  const [dragOver, setDragOver] = useState(null);
  const [composer, setComposer] = useState(null); // { status, title, projectId }
  const [dragging, setDragging] = useState(null);

  const defaultProject =
    activeProjectId !== 'all' ? activeProjectId : projects[0]?.id ?? '';

  const openComposer = (status) => {
    if (!projects.length) return;
    setComposer({ status, title: '', projectId: defaultProject });
  };

  const submitComposer = async (event) => {
    event.preventDefault();
    if (!composer?.title.trim() || !composer.projectId) return;
    await onCreate({
      projectId: composer.projectId,
      title: composer.title.trim(),
      status: composer.status,
    });
    setComposer((prev) => (prev ? { ...prev, title: '' } : null));
  };

  const handleDrop = (status) => {
    setDragOver(null);
    if (dragging && dragging.status !== status) {
      onMove(dragging.id, { status }, { silent: false });
    }
    setDragging(null);
  };

  return (
    <div className="board">
      {COLUMNS.map((column) => {
        const items = grouped[column.key] ?? [];
        return (
          <section
            key={column.key}
            className={`column ${dragOver === column.key ? 'drag-over' : ''}`}
            onDragOver={(e) => {
              e.preventDefault();
              setDragOver(column.key);
            }}
            onDragLeave={() => setDragOver((c) => (c === column.key ? null : c))}
            onDrop={() => handleDrop(column.key)}
            aria-label={`${column.label} column`}
          >
            <header className="column-head">
              <span className="column-title">
                <span className="dot" style={{ background: column.accent }} />
                {column.label}
                <span className="count">{items.length}</span>
              </span>
              <button
                className="icon-btn"
                title={`Add task to ${column.label}`}
                onClick={() => openComposer(column.key)}
                disabled={!projects.length}
              >
                +
              </button>
            </header>

            {composer?.status === column.key && (
              <form className="composer" onSubmit={submitComposer}>
                <input
                  className="input"
                  autoFocus
                  placeholder="What needs doing?"
                  value={composer.title}
                  onChange={(e) => setComposer({ ...composer, title: e.target.value })}
                  maxLength={140}
                />
                <select
                  className="input"
                  value={composer.projectId}
                  onChange={(e) => setComposer({ ...composer, projectId: e.target.value })}
                >
                  {projects.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                    </option>
                  ))}
                </select>
                <div className="row">
                  <button className="btn primary small">Add</button>
                  <button
                    type="button"
                    className="btn ghost small"
                    onClick={() => setComposer(null)}
                  >
                    Close
                  </button>
                </div>
              </form>
            )}

            <div className="column-body">
              {items.map((task) => (
                <TaskCard
                  key={task.id}
                  task={task}
                  onDragStart={() => setDragging(task)}
                  onDragEnd={() => {
                    setDragging(null);
                    setDragOver(null);
                  }}
                  onEdit={() => onEdit(task)}
                  onDelete={() => onDelete(task.id)}
                  onToggle={() =>
                    onMove(
                      task.id,
                      { status: task.status === 'done' ? 'todo' : 'done' },
                      { silent: false },
                    )
                  }
                />
              ))}

              {items.length === 0 && !composer && (
                <p className="empty">Nothing here yet.</p>
              )}
            </div>
          </section>
        );
      })}
    </div>
  );
}

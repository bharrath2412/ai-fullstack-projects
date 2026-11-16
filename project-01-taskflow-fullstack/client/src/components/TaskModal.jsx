import { useEffect, useState } from 'react';

export default function TaskModal({ task, projects, onClose, onSave, onDelete }) {
  const [form, setForm] = useState({
    title: task.title,
    notes: task.notes ?? '',
    status: task.status,
    priority: task.priority,
    dueDate: task.dueDate ?? '',
  });
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const onKey = (e) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const submit = async (event) => {
    event.preventDefault();
    setBusy(true);
    await onSave({
      title: form.title.trim(),
      notes: form.notes,
      status: form.status,
      priority: form.priority,
      dueDate: form.dueDate ? form.dueDate : null,
    });
    setBusy(false);
  };

  const project = projects.find((p) => p.id === task.projectId);

  return (
    <div className="modal-backdrop" onClick={onClose} role="presentation">
      <div
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="task-modal-title"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="modal-head">
          <div>
            <h2 id="task-modal-title">Edit task</h2>
            <small className="muted">{project?.name}</small>
          </div>
          <button className="icon-btn" onClick={onClose} aria-label="Close">
            ×
          </button>
        </header>

        <form onSubmit={submit} className="stack">
          <label>
            Title
            <input
              className="input"
              value={form.title}
              onChange={(e) => setForm({ ...form, title: e.target.value })}
              required
              maxLength={140}
            />
          </label>

          <label>
            Notes
            <textarea
              className="input"
              rows={4}
              value={form.notes}
              onChange={(e) => setForm({ ...form, notes: e.target.value })}
              placeholder="Context, links, acceptance criteria…"
              maxLength={4000}
            />
          </label>

          <div className="grid-2">
            <label>
              Status
              <select
                className="input"
                value={form.status}
                onChange={(e) => setForm({ ...form, status: e.target.value })}
              >
                <option value="todo">To do</option>
                <option value="in_progress">In progress</option>
                <option value="done">Done</option>
              </select>
            </label>

            <label>
              Priority
              <select
                className="input"
                value={form.priority}
                onChange={(e) => setForm({ ...form, priority: e.target.value })}
              >
                <option value="low">Low</option>
                <option value="medium">Medium</option>
                <option value="high">High</option>
              </select>
            </label>
          </div>

          <label>
            Due date
            <input
              className="input"
              type="date"
              value={form.dueDate ?? ''}
              onChange={(e) => setForm({ ...form, dueDate: e.target.value })}
            />
          </label>

          <footer className="modal-foot">
            <button type="button" className="btn ghost danger-text" onClick={onDelete}>
              Delete task
            </button>
            <div className="row">
              <button type="button" className="btn ghost" onClick={onClose}>
                Cancel
              </button>
              <button className="btn primary" disabled={busy}>
                {busy ? 'Saving…' : 'Save changes'}
              </button>
            </div>
          </footer>
        </form>
      </div>
    </div>
  );
}

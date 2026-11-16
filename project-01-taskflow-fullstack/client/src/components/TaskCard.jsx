const PRIORITY_LABEL = { high: 'High', medium: 'Medium', low: 'Low' };

const formatDue = (iso) => {
  if (!iso) return null;
  const date = new Date(`${iso}T00:00:00`);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const diffDays = Math.round((date - today) / 86_400_000);
  if (diffDays === 0) return 'Today';
  if (diffDays === 1) return 'Tomorrow';
  if (diffDays === -1) return 'Yesterday';
  return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
};

export default function TaskCard({ task, onDragStart, onDragEnd, onEdit, onDelete, onToggle }) {
  const due = formatDue(task.dueDate);
  const overdue = task.dueDate && task.status !== 'done' && new Date(task.dueDate) < new Date();

  return (
    <article
      className={`card p-${task.priority} ${task.status === 'done' ? 'is-done' : ''}`}
      draggable
      onDragStart={onDragStart}
      onDragEnd={onDragEnd}
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === 'Enter') onEdit();
        if (e.key === 'Delete') onDelete();
      }}
    >
      <div className="card-top">
        <button
          className={`check ${task.status === 'done' ? 'checked' : ''}`}
          onClick={onToggle}
          aria-label={task.status === 'done' ? 'Mark as to do' : 'Mark as done'}
        >
          {task.status === 'done' ? '✓' : ''}
        </button>
        <h3 onClick={onEdit}>{task.title}</h3>
      </div>

      {task.notes && <p className="notes">{task.notes}</p>}

      <div className="card-meta">
        {task.projectName && (
          <span className="tag project" title={task.projectName}>
            {task.projectName}
          </span>
        )}
        <span className={`tag priority ${task.priority}`}>{PRIORITY_LABEL[task.priority]}</span>
        {due && <span className={`tag due ${overdue ? 'overdue' : ''}`}>{due}</span>}
        <button className="icon-btn danger" onClick={onDelete} title="Delete task" aria-label="Delete task">
          ×
        </button>
      </div>
    </article>
  );
}

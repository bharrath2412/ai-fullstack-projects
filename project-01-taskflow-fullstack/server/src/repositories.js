/**
 * Repositories: the only module that knows SQL.
 * Route handlers stay thin and testable because every query lives here.
 */
import { getDb, newId, now } from './db.js';

/* ------------------------------- users ---------------------------------- */

export function createUser({ email, name, passwordHash }) {
  const id = newId();
  const createdAt = now();
  getDb()
    .prepare(
      `INSERT INTO users (id, email, name, password_hash, created_at)
       VALUES (?, ?, ?, ?, ?)`,
    )
    .run(id, email.toLowerCase(), name, passwordHash, createdAt);
  return getUserById(id);
}

export const getUserById = (id) =>
  getDb().prepare('SELECT * FROM users WHERE id = ?').get(id);

export const getUserByEmail = (email) =>
  getDb().prepare('SELECT * FROM users WHERE email = ?').get(String(email).toLowerCase());

/* ------------------------------ projects -------------------------------- */

const projectRow = (row) =>
  row && {
    id: row.id,
    name: row.name,
    description: row.description,
    color: row.color,
    createdAt: row.created_at,
    taskCount: row.task_count ?? 0,
    doneCount: row.done_count ?? 0,
  };

export function listProjects(userId) {
  const rows = getDb()
    .prepare(
      `SELECT p.*,
              COUNT(t.id) AS task_count,
              SUM(CASE WHEN t.status = 'done' THEN 1 ELSE 0 END) AS done_count
         FROM projects p
         LEFT JOIN tasks t ON t.project_id = p.id
        WHERE p.user_id = ?
        GROUP BY p.id
        ORDER BY p.created_at ASC`,
    )
    .all(userId);
  return rows.map(projectRow);
}

export const getProject = (id, userId) =>
  projectRow(
    getDb()
      .prepare('SELECT * FROM projects WHERE id = ? AND user_id = ?')
      .get(id, userId),
  );

export function createProject(userId, { name, description = '', color = '#6366f1' }) {
  const id = newId();
  getDb()
    .prepare(
      `INSERT INTO projects (id, user_id, name, description, color, created_at)
       VALUES (?, ?, ?, ?, ?, ?)`,
    )
    .run(id, userId, name, description, color, now());
  return getProject(id, userId);
}

export function updateProject(id, userId, patch) {
  const existing = getProject(id, userId);
  if (!existing) return null;
  const next = { ...existing, ...patch };
  getDb()
    .prepare(
      `UPDATE projects SET name = ?, description = ?, color = ?
        WHERE id = ? AND user_id = ?`,
    )
    .run(next.name, next.description, next.color, id, userId);
  return getProject(id, userId);
}

export const deleteProject = (id, userId) =>
  getDb().prepare('DELETE FROM projects WHERE id = ? AND user_id = ?').run(id, userId).changes > 0;

/* -------------------------------- tasks --------------------------------- */

const taskRow = (row) =>
  row && {
    id: row.id,
    projectId: row.project_id,
    projectName: row.project_name ?? null,
    title: row.title,
    notes: row.notes,
    status: row.status,
    priority: row.priority,
    dueDate: row.due_date,
    position: row.position,
    createdAt: row.created_at,
    updatedAt: row.updated_at,
  };

const TASK_SELECT = `
  SELECT t.*, p.name AS project_name
    FROM tasks t
    JOIN projects p ON p.id = t.project_id
`;

const SORTABLE = {
  position: 't.position ASC, t.created_at ASC',
  created: 't.created_at DESC',
  updated: 't.updated_at DESC',
  dueDate: 't.due_date IS NULL, t.due_date ASC',
  priority: "CASE t.priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END ASC",
  title: 't.title COLLATE NOCASE ASC',
};

export function listTasks(userId, filters = {}) {
  const where = ['t.user_id = ?'];
  const params = [userId];

  if (filters.projectId) {
    where.push('t.project_id = ?');
    params.push(filters.projectId);
  }
  if (filters.status) {
    where.push('t.status = ?');
    params.push(filters.status);
  }
  if (filters.priority) {
    where.push('t.priority = ?');
    params.push(filters.priority);
  }
  if (filters.q) {
    where.push('(t.title LIKE ? OR t.notes LIKE ?)');
    params.push(`%${filters.q}%`, `%${filters.q}%`);
  }
  if (filters.dueBefore) {
    where.push('t.due_date IS NOT NULL AND t.due_date <= ?');
    params.push(filters.dueBefore);
  }

  const orderBy = SORTABLE[filters.sort] ?? SORTABLE.position;
  const limit = Math.min(Number(filters.limit ?? 100), 200);
  const offset = Number(filters.offset ?? 0);

  const rows = getDb()
    .prepare(
      `${TASK_SELECT} WHERE ${where.join(' AND ')}
       ORDER BY ${orderBy} LIMIT ? OFFSET ?`,
    )
    .all(...params, limit, offset);

  const total = getDb()
    .prepare(`SELECT COUNT(*) AS n FROM tasks t WHERE ${where.join(' AND ')}`)
    .get(...params).n;

  return { items: rows.map(taskRow), total, limit, offset };
}

export const getTask = (id, userId) =>
  taskRow(
    getDb()
      .prepare(`${TASK_SELECT} WHERE t.id = ? AND t.user_id = ?`)
      .get(id, userId),
  );

export function createTask(userId, data) {
  const id = newId();
  const timestamp = now();
  const nextPosition =
    getDb()
      .prepare('SELECT COALESCE(MAX(position), 0) + 1 AS pos FROM tasks WHERE project_id = ?')
      .get(data.projectId).pos;

  getDb()
    .prepare(
      `INSERT INTO tasks
         (id, project_id, user_id, title, notes, status, priority, due_date, position, created_at, updated_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
    )
    .run(
      id,
      data.projectId,
      userId,
      data.title,
      data.notes ?? '',
      data.status ?? 'todo',
      data.priority ?? 'medium',
      data.dueDate ?? null,
      nextPosition,
      timestamp,
      timestamp,
    );
  return getTask(id, userId);
}

const COLUMN_BY_KEY = {
  title: 'title',
  notes: 'notes',
  status: 'status',
  priority: 'priority',
  dueDate: 'due_date',
  projectId: 'project_id',
  position: 'position',
};

export function updateTask(id, userId, patch) {
  const existing = getTask(id, userId);
  if (!existing) return null;

  const fields = [];
  const values = [];
  for (const [key, column] of Object.entries(COLUMN_BY_KEY)) {
    if (patch[key] !== undefined) {
      fields.push(`${column} = ?`);
      values.push(patch[key]);
    }
  }
  if (!fields.length) return existing;

  fields.push('updated_at = ?');
  values.push(now(), id, userId);

  getDb()
    .prepare(`UPDATE tasks SET ${fields.join(', ')} WHERE id = ? AND user_id = ?`)
    .run(...values);
  return getTask(id, userId);
}

export const deleteTask = (id, userId) =>
  getDb().prepare('DELETE FROM tasks WHERE id = ? AND user_id = ?').run(id, userId).changes > 0;

/** Reorder: place task `id` between `beforeId` and `afterId` using float positions. */
export function moveTask(id, userId, { beforeId, afterId }) {
  const task = getTask(id, userId);
  if (!task) return null;

  const before = beforeId ? getTask(beforeId, userId) : null;
  const after = afterId ? getTask(afterId, userId) : null;

  const lower = before?.position ?? 0;
  const upper = after?.position ?? lower + 2;
  const position = (lower + upper) / 2;

  return updateTask(id, userId, { position });
}

/* ------------------------------ activities ------------------------------ */

export function logActivity(userId, action, detail = '', taskId = null) {
  getDb()
    .prepare(
      `INSERT INTO activities (user_id, task_id, action, detail, created_at)
       VALUES (?, ?, ?, ?, ?)`,
    )
    .run(userId, taskId, action, detail, now());
}

export function listActivity(userId, limit = 20) {
  return getDb()
    .prepare(
      `SELECT id, task_id AS taskId, action, detail, created_at AS createdAt
         FROM activities WHERE user_id = ?
        ORDER BY id DESC LIMIT ?`,
    )
    .all(userId, Math.min(limit, 100));
}

/* -------------------------------- stats --------------------------------- */

export function getStats(userId) {
  const db = getDb();
  const counts = db
    .prepare(
      `SELECT
         COUNT(*) AS total,
         SUM(status = 'todo') AS todo,
         SUM(status = 'in_progress') AS inProgress,
         SUM(status = 'done') AS done,
         SUM(priority = 'high' AND status != 'done') AS highPriorityOpen,
         SUM(due_date IS NOT NULL AND due_date < date('now') AND status != 'done') AS overdue
       FROM tasks WHERE user_id = ?`,
    )
    .get(userId);

  const byStatus = { todo: counts.todo ?? 0, in_progress: counts.inProgress ?? 0, done: counts.done ?? 0 };

  // Completed per day for the last 14 days (zero-filled so charts render).
  const raw = db
    .prepare(
      `SELECT date(updated_at) AS day, COUNT(*) AS n
         FROM tasks
        WHERE user_id = ? AND status = 'done'
          AND updated_at >= date('now', '-13 days')
        GROUP BY day`,
    )
    .all(userId);
  const byDay = [];
  for (let i = 13; i >= 0; i -= 1) {
    const day = new Date(Date.now() - i * 86_400_000).toISOString().slice(0, 10);
    byDay.push({ day, completed: raw.find((r) => r.day === day)?.n ?? 0 });
  }

  const perProject = db
    .prepare(
      `SELECT p.id, p.name, p.color,
              COUNT(t.id) AS total,
              SUM(CASE WHEN t.status = 'done' THEN 1 ELSE 0 END) AS done
         FROM projects p LEFT JOIN tasks t ON t.project_id = p.id
        WHERE p.user_id = ? GROUP BY p.id ORDER BY total DESC`,
    )
    .all(userId)
    .map((r) => ({
      id: r.id,
      name: r.name,
      color: r.color,
      total: r.total,
      done: r.done ?? 0,
    }));

  const total = counts.total ?? 0;
  return {
    totals: {
      total,
      todo: byStatus.todo,
      inProgress: byStatus.in_progress,
      done: byStatus.done,
      highPriorityOpen: counts.highPriorityOpen ?? 0,
      overdue: counts.overdue ?? 0,
      completionRate: total === 0 ? 0 : Math.round((byStatus.done / total) * 100),
    },
    byStatus,
    completionsByDay: byDay,
    perProject,
  };
}

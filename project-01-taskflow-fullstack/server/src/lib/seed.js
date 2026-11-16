/**
 * Demo data generator: `npm run seed`
 *
 * Creates (or reuses) demo@taskflow.dev / Demo1234 and fills three projects
 * with realistic tasks so the dashboard and charts have something to show.
 */
import { initDb, getDb, now } from '../db.js';
import { hashPassword } from '../lib/auth.js';
import {
  createUser,
  getUserByEmail,
  createProject,
  createTask,
  updateTask,
} from '../repositories.js';

const DEMO = { email: 'demo@taskflow.dev', name: 'Demo User', password: 'Demo1234' };

const PROJECTS = [
  {
    name: 'Website relaunch',
    color: '#6366f1',
    description: 'Marketing site rebuild with the new design system.',
    tasks: [
      ['Audit current pages and redirects', 'done', 'high', -12],
      ['Build responsive hero section', 'done', 'medium', -9],
      ['Set up analytics events', 'in_progress', 'high', -2],
      ['Write launch announcement', 'todo', 'medium', 3],
      ['Lighthouse pass > 95', 'todo', 'low', 8],
    ],
  },
  {
    name: 'Mobile app v2',
    color: '#0ea5e9',
    description: 'Offline mode, push notifications and a redesigned check-out.',
    tasks: [
      ['Design offline sync strategy', 'done', 'high', -20],
      ['Implement local cache layer', 'in_progress', 'high', -1],
      ['Push notification opt-in flow', 'todo', 'medium', 5],
      ['Rewrite cart screen', 'todo', 'high', -3],
      ['Beta rollout plan', 'todo', 'low', 12],
    ],
  },
  {
    name: 'Data platform',
    color: '#10b981',
    description: 'Warehouse, dbt models and a self-serve metrics layer.',
    tasks: [
      ['Model product_event fact table', 'done', 'medium', -15],
      ['Add freshness tests', 'in_progress', 'medium', 2],
      ['Expose revenue metrics to BI', 'todo', 'high', 7],
    ],
  },
];

export async function seedDemoData({ log = true } = {}) {
  initDb();

  let user = getUserByEmail(DEMO.email);
  if (!user) {
    user = createUser({
      email: DEMO.email,
      name: DEMO.name,
      passwordHash: await hashPassword(DEMO.password),
    });
  }

  const db = getDb();
  const existing = db.prepare('SELECT COUNT(*) AS n FROM projects WHERE user_id = ?').get(user.id).n;
  if (existing > 0) {
    if (log) console.log('Demo projects already exist, skipping.');
    return { user, password: DEMO.password };
  }

  const dayMs = 86_400_000;
  let created = 0;

  for (const group of PROJECTS) {
    const project = createProject(user.id, {
      name: group.name,
      description: group.description,
      color: group.color,
    });

    for (const [title, status, priority, dueOffset] of group.tasks) {
      const task = createTask(user.id, {
        projectId: project.id,
        title,
        status,
        priority,
        dueDate: new Date(Date.now() + dueOffset * dayMs).toISOString().slice(0, 10),
      });
      created += 1;

      // Spread "done" completion timestamps over the past two weeks so the
      // activity chart is not a single spike.
      if (status === 'done') {
        const completedAt = new Date(Date.now() - Math.floor(Math.random() * 13 + 1) * dayMs)
          .toISOString();
        db.prepare('UPDATE tasks SET updated_at = ? WHERE id = ?').run(completedAt, task.id);
      }
    }
  }

  db.prepare(
    'INSERT INTO activities (user_id, action, detail, created_at) VALUES (?, ?, ?, ?)',
  ).run(user.id, 'seeded', `${created} demo tasks across ${PROJECTS.length} projects`, now());

  if (log) {
    console.log(`Seeded ${created} tasks for ${DEMO.email} / ${DEMO.password}`);
  }
  return { user, password: DEMO.password };
}

// Allow `node src/lib/seed.js` directly.
if (import.meta.url === `file://${process.argv[1]}`) {
  seedDemoData().then(() => process.exit(0));
}

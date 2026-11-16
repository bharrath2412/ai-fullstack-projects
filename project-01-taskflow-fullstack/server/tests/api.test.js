/**
 * Integration tests against the real HTTP app, real SQLite (in-memory) and
 * real JWTs. Run with: npm test
 */
import test, { before, after, describe } from 'node:test';
import assert from 'node:assert/strict';
import { createApp } from '../src/app.js';
import { initDb, closeDb, getDb } from '../src/db.js';

let server;
let baseUrl;

const api = async (path, { method = 'GET', token, body } = {}) => {
  const res = await fetch(`${baseUrl}${path}`, {
    method,
    headers: {
      'content-type': 'application/json',
      ...(token ? { authorization: `Bearer ${token}` } : {}),
    },
    ...(body ? { body: JSON.stringify(body) } : {}),
  });
  const text = await res.text();
  return { status: res.status, body: text ? JSON.parse(text) : null };
};

before(async () => {
  initDb(':memory:');
  const app = createApp({ requestLogger: false });
  await new Promise((resolve) => {
    server = app.listen(0, '127.0.0.1', resolve);
  });
  baseUrl = `http://127.0.0.1:${server.address().port}`;
});

after(async () => {
  await new Promise((resolve) => server.close(resolve));
  closeDb();
});

describe('auth', () => {
  test('registers a user and returns a token', async () => {
    const { status, body } = await api('/api/auth/register', {
      method: 'POST',
      body: { email: 'A@Example.com', name: 'Ada', password: 'Passw0rd1' },
    });
    assert.equal(status, 201);
    assert.ok(body.token);
    assert.equal(body.user.email, 'a@example.com', 'email should be normalised');
    assert.equal(body.user.password_hash, undefined, 'never leak hashes');
  });

  test('rejects weak passwords with field-level details', async () => {
    const { status, body } = await api('/api/auth/register', {
      method: 'POST',
      body: { email: 'b@example.com', name: 'Bo', password: 'short' },
    });
    assert.equal(status, 422);
    assert.equal(body.error.code, 'validation_error');
    assert.ok(body.error.details.some((d) => d.path === 'password'));
  });

  test('rejects duplicate emails with 409', async () => {
    const payload = { email: 'dup@example.com', name: 'Dup', password: 'Passw0rd1' };
    assert.equal((await api('/api/auth/register', { method: 'POST', body: payload })).status, 201);
    assert.equal((await api('/api/auth/register', { method: 'POST', body: payload })).status, 409);
  });

  test('login works and wrong password fails generically', async () => {
    await api('/api/auth/register', {
      method: 'POST',
      body: { email: 'login@example.com', name: 'Logan', password: 'Passw0rd1' },
    });
    const ok = await api('/api/auth/login', {
      method: 'POST',
      body: { email: 'login@example.com', password: 'Passw0rd1' },
    });
    assert.equal(ok.status, 200);

    const bad = await api('/api/auth/login', {
      method: 'POST',
      body: { email: 'login@example.com', password: 'wrong' },
    });
    assert.equal(bad.status, 401);
    assert.match(bad.body.error.message, /incorrect/i);
  });

  test('protected routes require a valid bearer token', async () => {
    assert.equal((await api('/api/projects')).status, 401);
    assert.equal((await api('/api/projects', { token: 'not-a-jwt' })).status, 401);
  });
});

describe('projects & tasks', () => {
  let token;
  let projectId;

  before(async () => {
    const { body } = await api('/api/auth/register', {
      method: 'POST',
      body: { email: 'worker@example.com', name: 'Worker', password: 'Passw0rd1' },
    });
    token = body.token;
    const created = await api('/api/projects', {
      method: 'POST',
      token,
      body: { name: 'Launch', color: '#ff0055' },
    });
    projectId = created.body.project.id;
  });

  test('creates and lists a project', async () => {
    const list = await api('/api/projects', { token });
    assert.equal(list.status, 200);
    assert.equal(list.body.items.length, 1);
    assert.equal(list.body.items[0].name, 'Launch');
  });

  test('task lifecycle: create, update, complete, delete', async () => {
    const created = await api('/api/tasks', {
      method: 'POST',
      token,
      body: { projectId, title: 'Ship it', priority: 'high' },
    });
    assert.equal(created.status, 201);
    const taskId = created.body.task.id;
    assert.equal(created.body.task.status, 'todo');

    const updated = await api(`/api/tasks/${taskId}`, {
      method: 'PATCH',
      token,
      body: { status: 'done' },
    });
    assert.equal(updated.status, 200);
    assert.equal(updated.body.task.status, 'done');
    assert.notEqual(updated.body.task.updatedAt, created.body.task.updatedAt);

    const stats = await api('/api/stats', { token });
    assert.equal(stats.body.totals.done, 1);
    assert.equal(stats.body.totals.completionRate, 100);
    assert.equal(stats.body.completionsByDay.length, 14);

    assert.equal((await api(`/api/tasks/${taskId}`, { method: 'DELETE', token })).status, 204);
    assert.equal((await api(`/api/tasks/${taskId}`, { token })).status, 404);
  });

  test('filters, searches and paginates', async () => {
    await api('/api/tasks', {
      method: 'POST',
      token,
      body: { projectId, title: 'Write docs', status: 'in_progress', priority: 'low' },
    });
    const byQuery = await api('/api/tasks?q=docs', { token });
    assert.equal(byQuery.body.items.length, 1);

    const byStatus = await api('/api/tasks?status=todo', { token });
    assert.equal(byStatus.body.items.length, 0);

    const paged = await api('/api/tasks?limit=1&offset=0', { token });
    assert.equal(paged.body.items.length, 1);
    assert.equal(paged.body.total, 1);
  });

  test('rejects a task in a project the user does not own', async () => {
    const other = await api('/api/auth/register', {
      method: 'POST',
      body: { email: 'intruder@example.com', name: 'Eve', password: 'Passw0rd1' },
    });
    const attempt = await api('/api/tasks', {
      method: 'POST',
      token: other.body.token,
      body: { projectId, title: 'Hijack' },
    });
    assert.equal(attempt.status, 400);
  });

  test('unknown project ids are 404 and cascade deletes remove tasks', async () => {
    const ghost = await api('/api/projects/00000000-0000-4000-8000-000000000000', { token });
    assert.equal(ghost.status, 404);

    assert.equal((await api(`/api/projects/${projectId}`, { method: 'DELETE', token })).status, 204);
    const remaining = getDb()
      .prepare('SELECT COUNT(*) AS n FROM tasks WHERE project_id = ?')
      .get(projectId).n;
    assert.equal(remaining, 0, 'ON DELETE CASCADE should clear child tasks');
  });
});

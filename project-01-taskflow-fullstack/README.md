# TaskFlow — full-stack project & task manager

A production-shaped MERN-style app with a **React + Vite** frontend and an **Express + SQLite** API.
No ORM, no CSS framework — everything is explicit so you can read the whole request path.

![stack](https://img.shields.io/badge/React-18-61dafb) ![stack](https://img.shields.io/badge/Express-4-000) ![stack](https://img.shields.io/badge/SQLite-WAL-003b57) ![stack](https://img.shields.io/badge/tests-node%3Atest-10%20passing-10b981)

## Features

**Backend**
- JWT auth (`bcrypt` hashing, 7-day tokens, `iss` claim), generic 401s for wrong email *or* password
- Zod validation on every body and query string, with field-level error details
- REST API: projects CRUD, tasks CRUD, filtering (`status`, `priority`, `q`, `dueBefore`), sorting, pagination
- Kanban ordering with float positions (`POST /tasks/:id/move`) — no full renumber on drag
- Dashboard aggregates computed in SQL (status split, 14-day completion series, per-project progress)
- Activity log written on create/status-change/delete
- In-memory sliding-window rate limiter, Helmet security headers, ownership checks on every row
- Idempotent schema migration on boot, WAL + `foreign_keys=ON`, graceful SIGTERM shutdown
- 10 integration tests against real HTTP + real SQLite

**Frontend**
- Login / register with inline validation feedback and token persistence
- Kanban board with native HTML5 drag & drop between To do / In progress / Done
- Optimistic updates with automatic rollback on failure
- Project sidebar with colour picker, task counts, delete cascade
- Dashboard: KPI cards, dependency-free SVG bar chart, per-project progress bars
- Task modal editor, toast notifications, keyboard support (`Enter` to edit, `Delete` to remove)
- Fully responsive, dark theme, zero UI dependencies

## Quick start

```bash
# terminal 1 — API
cd server
npm install
npm run seed          # optional: demo@taskflow.dev / Demo1234
npm run dev           # http://localhost:4000

# terminal 2 — web app
cd client
npm install
npm run dev           # http://localhost:5173  (proxies /api -> :4000)
```

Open http://localhost:5173 and either register or use the demo account.

## API reference

| Method | Path | Notes |
| --- | --- | --- |
| POST | `/api/auth/register` | `{email,name,password}` → `{token,user}` |
| POST | `/api/auth/login` | → `{token,user}` |
| GET | `/api/auth/me` | requires `Authorization: Bearer <jwt>` |
| GET/POST | `/api/projects` | list (with task counts) / create |
| GET/PATCH/DELETE | `/api/projects/:id` | owner-scoped |
| GET | `/api/tasks` | `?status=&priority=&q=&sort=&limit=&offset=` |
| POST | `/api/tasks` | `{projectId,title,priority?,status?,dueDate?}` |
| PATCH/DELETE | `/api/tasks/:id` | partial update / delete |
| POST | `/api/tasks/:id/move` | `{beforeId,afterId}` reorder |
| GET | `/api/tasks/activity` | recent activity feed |
| GET | `/api/stats` | dashboard aggregates |
| GET | `/api/health` | liveness probe |

Example:

```bash
curl -s localhost:4000/api/auth/login \
  -H 'content-type: application/json' \
  -d '{"email":"demo@taskflow.dev","password":"Demo1234"}'
```

## Data model

```
users ──┬── projects ──┬── tasks
        │              │
        └── activities ┘   (task_id nullable, ON DELETE CASCADE everywhere)
```

## Tests

```bash
cd server && npm test
```

Covers registration/normalisation, weak-password rejection, duplicate email → 409, generic login
failure, token enforcement, task lifecycle, filtering/pagination, cross-user access denial, and
`ON DELETE CASCADE` behaviour.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `PORT` | `4000` | API port |
| `DB_PATH` | `server/data/taskflow.db` | SQLite file |
| `JWT_SECRET` | dev placeholder | **required in production** |
| `JWT_EXPIRES_IN` | `7d` | token lifetime |
| `CORS_ORIGIN` | `http://localhost:5173` | comma-separated origins |
| `SEED_ON_START` | `false` | seed demo data at boot |
| `RATE_LIMIT_MAX` | `300` | requests per window per user/IP |

## Docker

```bash
docker compose up --build     # API on :4000
```

Or build the SPA and serve it from any static host, pointing it at the API.

## Project layout

```
server/
  src/
    app.js            # express app factory (no listen) -> testable
    index.js          # entrypoint, graceful shutdown
    config.js         # env parsing + production safety check
    db.js             # sqlite bootstrap, pragmas, schema
    repositories.js   # ALL sql lives here
    lib/{auth,validate,errors,rateLimit,seed}.js
    routes/{auth,projects,tasks,stats}.js
  tests/api.test.js
client/
  src/
    api.js            # fetch wrapper + token storage
    App.jsx           # state, optimistic updates, rollbacks
    components/       # AuthScreen, Sidebar, Board, TaskCard, TaskModal, Dashboard, Toasts
    styles.css        # design tokens + layout
```

## Possible extensions

- Refresh-token rotation and httpOnly cookies instead of `localStorage`
- WebSocket broadcast so two tabs stay in sync
- Attachment uploads to S3-compatible storage
- Playwright e2e around the drag & drop flow

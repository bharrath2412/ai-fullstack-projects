/** Task CRUD, filtering, reordering and activity feed. */
import { Router } from 'express';
import { asyncHandler, AppError } from '../lib/errors.js';
import { requireAuth } from '../lib/auth.js';
import { validate, schemas } from '../lib/validate.js';
import {
  listTasks,
  createTask,
  getTask,
  updateTask,
  deleteTask,
  moveTask,
  getProject,
  logActivity,
  listActivity,
} from '../repositories.js';

export const tasksRouter = Router();
tasksRouter.use(requireAuth);

const assertProject = (projectId, userId) => {
  if (!getProject(projectId, userId)) throw AppError.badRequest('Project does not exist');
};

tasksRouter.get(
  '/',
  validate(schemas.taskQuery, 'query'),
  asyncHandler(async (req, res) => {
    res.json(listTasks(req.user.id, req.query));
  }),
);

tasksRouter.get(
  '/activity',
  asyncHandler(async (req, res) => {
    res.json({ items: listActivity(req.user.id, Number(req.query.limit ?? 20)) });
  }),
);

tasksRouter.post(
  '/',
  validate(schemas.taskCreate),
  asyncHandler(async (req, res) => {
    assertProject(req.body.projectId, req.user.id);
    const task = createTask(req.user.id, req.body);
    logActivity(req.user.id, 'created', task.title, task.id);
    res.status(201).json({ task });
  }),
);

tasksRouter.get(
  '/:id',
  asyncHandler(async (req, res) => {
    const task = getTask(req.params.id, req.user.id);
    if (!task) throw AppError.notFound('Task not found');
    res.json({ task });
  }),
);

tasksRouter.patch(
  '/:id',
  validate(schemas.taskUpdate),
  asyncHandler(async (req, res) => {
    const existing = getTask(req.params.id, req.user.id);
    if (!existing) throw AppError.notFound('Task not found');

    const task = updateTask(req.params.id, req.user.id, req.body);
    if (req.body.status && req.body.status !== existing.status) {
      logActivity(req.user.id, `status:${req.body.status}`, task.title, task.id);
    }
    res.json({ task });
  }),
);

tasksRouter.post(
  '/:id/move',
  validate(schemas.taskMove),
  asyncHandler(async (req, res) => {
    const task = moveTask(req.params.id, req.user.id, req.body);
    if (!task) throw AppError.notFound('Task not found');
    res.json({ task });
  }),
);

tasksRouter.delete(
  '/:id',
  asyncHandler(async (req, res) => {
    const task = getTask(req.params.id, req.user.id);
    if (!task) throw AppError.notFound('Task not found');
    deleteTask(req.params.id, req.user.id);
    logActivity(req.user.id, 'deleted', task.title, task.id);
    res.status(204).end();
  }),
);

/** Project CRUD, scoped to the authenticated user. */
import { Router } from 'express';
import { asyncHandler, AppError } from '../lib/errors.js';
import { requireAuth } from '../lib/auth.js';
import { validate, schemas } from '../lib/validate.js';
import {
  listProjects,
  createProject,
  updateProject,
  deleteProject,
  getProject,
} from '../repositories.js';

export const projectsRouter = Router();
projectsRouter.use(requireAuth);

projectsRouter.get(
  '/',
  asyncHandler(async (req, res) => {
    res.json({ items: listProjects(req.user.id) });
  }),
);

projectsRouter.post(
  '/',
  validate(schemas.projectCreate),
  asyncHandler(async (req, res) => {
    if (listProjects(req.user.id).some((p) => p.name.toLowerCase() === req.body.name.toLowerCase())) {
      throw AppError.conflict('You already have a project with that name');
    }
    res.status(201).json({ project: createProject(req.user.id, req.body) });
  }),
);

projectsRouter.get(
  '/:id',
  asyncHandler(async (req, res) => {
    const project = getProject(req.params.id, req.user.id);
    if (!project) throw AppError.notFound('Project not found');
    res.json({ project });
  }),
);

projectsRouter.patch(
  '/:id',
  validate(schemas.projectUpdate),
  asyncHandler(async (req, res) => {
    const project = updateProject(req.params.id, req.user.id, req.body);
    if (!project) throw AppError.notFound('Project not found');
    res.json({ project });
  }),
);

projectsRouter.delete(
  '/:id',
  asyncHandler(async (req, res) => {
    if (!deleteProject(req.params.id, req.user.id)) throw AppError.notFound('Project not found');
    res.status(204).end();
  }),
);

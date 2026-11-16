/** Dashboard aggregates: GET /api/stats */
import { Router } from 'express';
import { asyncHandler } from '../lib/errors.js';
import { requireAuth } from '../lib/auth.js';
import { getStats } from '../repositories.js';

export const statsRouter = Router();
statsRouter.use(requireAuth);

statsRouter.get(
  '/',
  asyncHandler(async (req, res) => {
    res.json(getStats(req.user.id));
  }),
);

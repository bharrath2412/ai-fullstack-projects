/** POST /register, POST /login, GET /me */
import { Router } from 'express';
import { asyncHandler, AppError } from '../lib/errors.js';
import { hashPassword, verifyPassword, signToken, requireAuth, publicUser } from '../lib/auth.js';
import { validate, schemas } from '../lib/validate.js';
import { createUser, getUserByEmail } from '../repositories.js';

export const authRouter = Router();

authRouter.post(
  '/register',
  validate(schemas.register),
  asyncHandler(async (req, res) => {
    const { email, name, password } = req.body;
    if (getUserByEmail(email)) {
      throw AppError.conflict('An account with that email already exists');
    }
    const user = createUser({ email, name, passwordHash: await hashPassword(password) });
    res.status(201).json({ token: signToken(user), user: publicUser(user) });
  }),
);

authRouter.post(
  '/login',
  validate(schemas.login),
  asyncHandler(async (req, res) => {
    const { email, password } = req.body;
    const user = getUserByEmail(email);
    // Same generic message for unknown email and wrong password.
    if (!user || !(await verifyPassword(password, user.password_hash))) {
      throw AppError.unauthorized('Email or password is incorrect');
    }
    res.json({ token: signToken(user), user: publicUser(user) });
  }),
);

authRouter.get('/me', requireAuth, (req, res) => {
  res.json({ user: publicUser(req.user) });
});

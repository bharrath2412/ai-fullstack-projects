/** Password hashing, JWT issuing/verification and the auth middleware. */
import bcrypt from 'bcryptjs';
import jwt from 'jsonwebtoken';
import { config } from '../config.js';
import { AppError } from './errors.js';
import { getUserById } from '../repositories.js';

export const hashPassword = (plain) => bcrypt.hash(plain, config.bcryptRounds);
export const verifyPassword = (plain, hash) => bcrypt.compare(plain, hash);

export function signToken(user) {
  return jwt.sign({ sub: user.id, email: user.email }, config.jwt.secret, {
    expiresIn: config.jwt.expiresIn,
    issuer: 'taskflow',
  });
}

export function verifyToken(token) {
  try {
    return jwt.verify(token, config.jwt.secret, { issuer: 'taskflow' });
  } catch {
    throw AppError.unauthorized('Session expired or token invalid');
  }
}

/** Populates req.user from the `Authorization: Bearer <jwt>` header. */
export function requireAuth(req, res, next) {
  try {
    const header = req.get('authorization') ?? '';
    const [scheme, token] = header.split(' ');
    if (scheme?.toLowerCase() !== 'bearer' || !token) {
      throw AppError.unauthorized();
    }
    const payload = verifyToken(token);
    const user = getUserById(payload.sub);
    if (!user) throw AppError.unauthorized('Account no longer exists');
    req.user = user;
    next();
  } catch (err) {
    next(err);
  }
}

export const publicUser = (user) => ({
  id: user.id,
  email: user.email,
  name: user.name,
  createdAt: user.created_at,
});

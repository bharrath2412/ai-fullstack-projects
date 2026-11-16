/**
 * Centralised configuration. Everything is overridable through env vars so the
 * same build runs locally, in Docker and in CI.
 */
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, '..');

const bool = (value, fallback) =>
  value === undefined ? fallback : ['1', 'true', 'yes'].includes(String(value).toLowerCase());

export const config = {
  env: process.env.NODE_ENV ?? 'development',
  port: Number(process.env.PORT ?? 4000),
  root,
  dbPath: process.env.DB_PATH ?? path.join(root, 'data', 'taskflow.db'),
  jwt: {
    secret: process.env.JWT_SECRET ?? 'dev-only-secret-change-me',
    expiresIn: process.env.JWT_EXPIRES_IN ?? '7d',
  },
  bcryptRounds: Number(process.env.BCRYPT_ROUNDS ?? 10),
  cors: {
    origin: (process.env.CORS_ORIGIN ?? 'http://localhost:5173').split(','),
  },
  rateLimit: {
    windowMs: Number(process.env.RATE_LIMIT_WINDOW_MS ?? 60_000),
    max: Number(process.env.RATE_LIMIT_MAX ?? 300),
  },
  logRequests: bool(process.env.LOG_REQUESTS, true),
  seedOnStart: bool(process.env.SEED_ON_START, false),
};

export function assertProductionSafety() {
  if (config.env === 'production' && config.jwt.secret === 'dev-only-secret-change-me') {
    throw new Error('Refusing to boot: set a real JWT_SECRET before running in production.');
  }
}

/**
 * Express app factory.
 *
 * Kept separate from index.js so tests can boot the app on an ephemeral port
 * without touching process.env or the production entrypoint.
 */
import express from 'express';
import cors from 'cors';
import helmet from 'helmet';
import { config } from './config.js';
import { rateLimit } from './lib/rateLimit.js';
import { errorHandler, notFoundHandler } from './lib/errors.js';
import { authRouter } from './routes/auth.js';
import { projectsRouter } from './routes/projects.js';
import { tasksRouter } from './routes/tasks.js';
import { statsRouter } from './routes/stats.js';

export function createApp({ corsOrigin = config.cors.origin, requestLogger = config.logRequests } = {}) {
  const app = express();

  app.disable('x-powered-by');
  app.set('trust proxy', 1);
  app.use(helmet());
  app.use(cors({ origin: corsOrigin, credentials: false }));
  app.use(express.json({ limit: '256kb' }));

  if (requestLogger) {
    app.use((req, res, next) => {
      const started = process.hrtime.bigint();
      res.on('finish', () => {
        const ms = Number(process.hrtime.bigint() - started) / 1e6;
        console.log(
          `${req.method} ${req.originalUrl} ${res.statusCode} ${ms.toFixed(1)}ms`,
        );
      });
      next();
    });
  }

  app.get('/api/health', (req, res) => {
    res.json({ status: 'ok', uptime: process.uptime(), env: config.env });
  });

  app.use('/api', rateLimit());
  app.use('/api/auth', authRouter);
  app.use('/api/projects', projectsRouter);
  app.use('/api/tasks', tasksRouter);
  app.use('/api/stats', statsRouter);

  app.use(notFoundHandler);
  app.use(errorHandler);

  return app;
}

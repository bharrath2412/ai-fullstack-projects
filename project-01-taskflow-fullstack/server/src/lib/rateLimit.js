/**
 * Minimal in-memory sliding-window rate limiter.
 *
 * Good enough for a single node process; behind multiple instances you would
 * move the counters into Redis. Kept dependency-free on purpose.
 */
import { config } from '../config.js';
import { AppError } from './errors.js';

export function rateLimit({ windowMs = config.rateLimit.windowMs, max = config.rateLimit.max } = {}) {
  /** @type {Map<string, number[]>} */
  const hits = new Map();

  // Periodic sweep so the map cannot grow unbounded.
  const sweeper = setInterval(() => {
    const cutoff = Date.now() - windowMs;
    for (const [key, stamps] of hits) {
      const kept = stamps.filter((t) => t > cutoff);
      if (kept.length) hits.set(key, kept);
      else hits.delete(key);
    }
  }, windowMs).unref?.();

  const middleware = (req, res, next) => {
    const key = req.user?.id ?? req.ip ?? 'anonymous';
    const nowMs = Date.now();
    const cutoff = nowMs - windowMs;
    const stamps = (hits.get(key) ?? []).filter((t) => t > cutoff);

    if (stamps.length >= max) {
      res.set('Retry-After', String(Math.ceil(windowMs / 1000)));
      return next(new AppError(429, 'rate_limited', 'Too many requests, slow down a little'));
    }

    stamps.push(nowMs);
    hits.set(key, stamps);
    res.set('X-RateLimit-Limit', String(max));
    res.set('X-RateLimit-Remaining', String(Math.max(0, max - stamps.length)));
    next();
  };

  middleware.stop = () => clearInterval(sweeper);
  return middleware;
}

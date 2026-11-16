/** Error plumbing shared by every route. */

export class AppError extends Error {
  constructor(status, code, message, details) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
  }

  static badRequest(message, details) {
    return new AppError(400, 'bad_request', message, details);
  }

  static unauthorized(message = 'Authentication required') {
    return new AppError(401, 'unauthorized', message);
  }

  static forbidden(message = 'You do not have access to this resource') {
    return new AppError(403, 'forbidden', message);
  }

  static notFound(message = 'Resource not found') {
    return new AppError(404, 'not_found', message);
  }

  static conflict(message = 'Resource already exists') {
    return new AppError(409, 'conflict', message);
  }
}

/** Wrap async handlers so rejected promises reach the error middleware. */
export const asyncHandler = (fn) => (req, res, next) =>
  Promise.resolve(fn(req, res, next)).catch(next);

export function notFoundHandler(req, res) {
  res.status(404).json({
    error: { code: 'not_found', message: `No route for ${req.method} ${req.originalUrl}` },
  });
}

// eslint-disable-next-line no-unused-vars
export function errorHandler(err, req, res, next) {
  if (err instanceof AppError) {
    return res.status(err.status).json({
      error: { code: err.code, message: err.message, details: err.details },
    });
  }

  if (err?.name === 'ZodError') {
    return res.status(422).json({
      error: {
        code: 'validation_error',
        message: 'Request payload is invalid',
        details: err.issues.map((i) => ({ path: i.path.join('.'), message: i.message })),
      },
    });
  }

  if (err?.code === 'SQLITE_CONSTRAINT_UNIQUE') {
    return res
      .status(409)
      .json({ error: { code: 'conflict', message: 'That value is already taken' } });
  }

  console.error('[unhandled]', err);
  return res.status(500).json({
    error: { code: 'internal_error', message: 'Something went wrong on our side' },
  });
}

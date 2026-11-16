/** Zod schemas + a validate() middleware. Controllers get typed, clean input. */
import { z } from 'zod';
import { AppError } from './errors.js';

const isoDate = z
  .string()
  .regex(/^\d{4}-\d{2}-\d{2}$/, 'Expected YYYY-MM-DD')
  .nullable();

export const schemas = {
  register: z.object({
    email: z.string().trim().toLowerCase().email('Enter a valid email'),
    name: z.string().trim().min(2, 'At least 2 characters').max(60),
    password: z
      .string()
      .min(8, 'Use at least 8 characters')
      .max(128)
      .regex(/[a-zA-Z]/, 'Include at least one letter')
      .regex(/[0-9]/, 'Include at least one number'),
  }),

  login: z.object({
    email: z.string().trim().toLowerCase().email(),
    password: z.string().min(1),
  }),

  projectCreate: z.object({
    name: z.string().trim().min(1, 'Name is required').max(80),
    description: z.string().trim().max(500).optional().default(''),
    color: z
      .string()
      .regex(/^#[0-9a-fA-F]{6}$/, 'Use a hex colour like #6366f1')
      .optional()
      .default('#6366f1'),
  }),

  projectUpdate: z
    .object({
      name: z.string().trim().min(1).max(80).optional(),
      description: z.string().trim().max(500).optional(),
      color: z.string().regex(/^#[0-9a-fA-F]{6}$/).optional(),
    })
    .refine((v) => Object.keys(v).length > 0, { message: 'Nothing to update' }),

  taskCreate: z.object({
    projectId: z.string().uuid('Invalid project id'),
    title: z.string().trim().min(1, 'Title is required').max(140),
    notes: z.string().trim().max(4000).optional().default(''),
    status: z.enum(['todo', 'in_progress', 'done']).optional().default('todo'),
    priority: z.enum(['low', 'medium', 'high']).optional().default('medium'),
    dueDate: isoDate.optional().default(null),
  }),

  taskUpdate: z
    .object({
      title: z.string().trim().min(1).max(140).optional(),
      notes: z.string().trim().max(4000).optional(),
      status: z.enum(['todo', 'in_progress', 'done']).optional(),
      priority: z.enum(['low', 'medium', 'high']).optional(),
      dueDate: isoDate.optional(),
      position: z.number().finite().optional(),
    })
    .refine((v) => Object.keys(v).length > 0, { message: 'Nothing to update' }),

  taskMove: z.object({
    beforeId: z.string().uuid().nullable().optional(),
    afterId: z.string().uuid().nullable().optional(),
  }),

  taskQuery: z.object({
    projectId: z.string().uuid().optional(),
    status: z.enum(['todo', 'in_progress', 'done']).optional(),
    priority: z.enum(['low', 'medium', 'high']).optional(),
    q: z.string().trim().max(120).optional(),
    dueBefore: z.string().regex(/^\d{4}-\d{2}-\d{2}$/).optional(),
    sort: z.enum(['position', 'created', 'updated', 'dueDate', 'priority', 'title']).optional(),
    limit: z.coerce.number().int().min(1).max(200).optional(),
    offset: z.coerce.number().int().min(0).optional(),
  }),
};

/** `where` is 'body' | 'query'. Parsed values replace req[where]. */
export const validate = (schema, where = 'body') => (req, res, next) => {
  const result = schema.safeParse(req[where] ?? {});
  if (!result.success) {
    return next(
      new AppError(
        422,
        'validation_error',
        'Request payload is invalid',
        result.error.issues.map((i) => ({ path: i.path.join('.'), message: i.message })),
      ),
    );
  }
  req[where] = result.data;
  next();
};

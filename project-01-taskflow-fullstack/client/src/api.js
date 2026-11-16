/** Thin fetch wrapper: token storage, JSON handling, typed errors. */

const TOKEN_KEY = 'taskflow.token';

export const getToken = () => localStorage.getItem(TOKEN_KEY);
export const setToken = (token) =>
  token ? localStorage.setItem(TOKEN_KEY, token) : localStorage.removeItem(TOKEN_KEY);

export class ApiError extends Error {
  constructor(status, code, message, details) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details ?? [];
  }
}

let onUnauthorized = () => {};
export const setUnauthorizedHandler = (fn) => {
  onUnauthorized = fn;
};

async function request(path, { method = 'GET', body, signal } = {}) {
  const token = getToken();
  const res = await fetch(`/api${path}`, {
    method,
    signal,
    headers: {
      'content-type': 'application/json',
      ...(token ? { authorization: `Bearer ${token}` } : {}),
    },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });

  if (res.status === 204) return null;

  const text = await res.text();
  const payload = text ? JSON.parse(text) : null;

  if (!res.ok) {
    const error = payload?.error ?? {};
    if (res.status === 401) onUnauthorized();
    throw new ApiError(
      res.status,
      error.code ?? 'unknown',
      error.message ?? `Request failed (${res.status})`,
      error.details,
    );
  }
  return payload;
}

export const api = {
  register: (body) => request('/auth/register', { method: 'POST', body }),
  login: (body) => request('/auth/login', { method: 'POST', body }),
  me: () => request('/auth/me'),

  listProjects: () => request('/projects'),
  createProject: (body) => request('/projects', { method: 'POST', body }),
  updateProject: (id, body) => request(`/projects/${id}`, { method: 'PATCH', body }),
  deleteProject: (id) => request(`/projects/${id}`, { method: 'DELETE' }),

  listTasks: (params = {}) => {
    const qs = new URLSearchParams(
      Object.entries(params).filter(([, v]) => v !== undefined && v !== '' && v !== null),
    ).toString();
    return request(`/tasks${qs ? `?${qs}` : ''}`);
  },
  createTask: (body) => request('/tasks', { method: 'POST', body }),
  updateTask: (id, body) => request(`/tasks/${id}`, { method: 'PATCH', body }),
  deleteTask: (id) => request(`/tasks/${id}`, { method: 'DELETE' }),
  activity: () => request('/tasks/activity'),

  stats: () => request('/stats'),
};

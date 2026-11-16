import { useState } from 'react';
import { api } from '../api.js';

const DEMO = { email: 'demo@taskflow.dev', password: 'Demo1234' };

export default function AuthScreen({ onAuthed }) {
  const [mode, setMode] = useState('login');
  const [form, setForm] = useState({ name: '', email: '', password: '' });
  const [errors, setErrors] = useState([]);
  const [busy, setBusy] = useState(false);

  const submit = async (event) => {
    event.preventDefault();
    setBusy(true);
    setErrors([]);
    try {
      const payload =
        mode === 'login'
          ? await api.login({ email: form.email, password: form.password })
          : await api.register(form);
      onAuthed(payload);
    } catch (err) {
      setErrors(
        err.details?.length
          ? err.details.map((d) => `${d.path}: ${d.message}`)
          : [err.message],
      );
    } finally {
      setBusy(false);
    }
  };

  const fillDemo = () => {
    setMode('login');
    setForm({ name: '', ...DEMO });
  };

  return (
    <div className="auth">
      <div className="auth-card">
        <div className="brand large">
          <span className="brand-mark">TF</span>
          <div>
            <strong>TaskFlow</strong>
            <small>Projects, tasks & delivery insights</small>
          </div>
        </div>

        <div className="segmented full">
          <button
            className={mode === 'login' ? 'active' : ''}
            onClick={() => setMode('login')}
            type="button"
          >
            Sign in
          </button>
          <button
            className={mode === 'register' ? 'active' : ''}
            onClick={() => setMode('register')}
            type="button"
          >
            Create account
          </button>
        </div>

        <form onSubmit={submit} className="stack">
          {mode === 'register' && (
            <label>
              Name
              <input
                className="input"
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                placeholder="Ada Lovelace"
                required
                minLength={2}
              />
            </label>
          )}

          <label>
            Email
            <input
              className="input"
              type="email"
              value={form.email}
              onChange={(e) => setForm({ ...form, email: e.target.value })}
              placeholder="you@example.com"
              required
            />
          </label>

          <label>
            Password
            <input
              className="input"
              type="password"
              value={form.password}
              onChange={(e) => setForm({ ...form, password: e.target.value })}
              placeholder={mode === 'register' ? 'At least 8 chars, 1 number' : '••••••••'}
              required
              minLength={mode === 'register' ? 8 : 1}
            />
          </label>

          {errors.length > 0 && (
            <ul className="form-errors" role="alert">
              {errors.map((e) => (
                <li key={e}>{e}</li>
              ))}
            </ul>
          )}

          <button className="btn primary" disabled={busy}>
            {busy ? 'Please wait…' : mode === 'login' ? 'Sign in' : 'Create account'}
          </button>
        </form>

        <p className="hint">
          Demo account: <button type="button" className="link" onClick={fillDemo}>demo@taskflow.dev / Demo1234</button>
          <br />
          <small>Run <code>npm run seed</code> in the server folder to create it.</small>
        </p>
      </div>
    </div>
  );
}

import { useCallback, useEffect, useMemo, useState } from 'react';
import { api, setToken, getToken, setUnauthorizedHandler } from './api.js';
import AuthScreen from './components/AuthScreen.jsx';
import Sidebar from './components/Sidebar.jsx';
import Board from './components/Board.jsx';
import Dashboard from './components/Dashboard.jsx';
import TaskModal from './components/TaskModal.jsx';
import Toasts from './components/Toasts.jsx';

const STATUSES = ['todo', 'in_progress', 'done'];

export default function App() {
  const [booting, setBooting] = useState(true);
  const [user, setUser] = useState(null);
  const [projects, setProjects] = useState([]);
  const [tasks, setTasks] = useState([]);
  const [stats, setStats] = useState(null);
  const [activeProjectId, setActiveProjectId] = useState('all');
  const [view, setView] = useState('board');
  const [query, setQuery] = useState('');
  const [priority, setPriority] = useState('all');
  const [editing, setEditing] = useState(null);
  const [toasts, setToasts] = useState([]);
  const [loading, setLoading] = useState(false);

  const toast = useCallback((message, tone = 'info') => {
    const id = Math.random().toString(36).slice(2);
    setToasts((prev) => [...prev, { id, message, tone }]);
    setTimeout(() => setToasts((prev) => prev.filter((t) => t.id !== id)), 4000);
  }, []);

  const logout = useCallback(() => {
    setToken(null);
    setUser(null);
    setProjects([]);
    setTasks([]);
    setStats(null);
  }, []);

  useEffect(() => {
    setUnauthorizedHandler(logout);
  }, [logout]);

  // --- boot: reuse an existing token if it is still valid -------------------
  useEffect(() => {
    (async () => {
      if (!getToken()) {
        setBooting(false);
        return;
      }
      try {
        const { user: me } = await api.me();
        setUser(me);
      } catch {
        setToken(null);
      } finally {
        setBooting(false);
      }
    })();
  }, []);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [projectRes, taskRes, statsRes] = await Promise.all([
        api.listProjects(),
        api.listTasks({ limit: 200 }),
        api.stats(),
      ]);
      setProjects(projectRes.items);
      setTasks(taskRes.items);
      setStats(statsRes);
    } catch (err) {
      toast(err.message, 'error');
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => {
    if (user) refresh();
  }, [user, refresh]);

  // --- mutations -----------------------------------------------------------
  const handleCreateTask = async (draft) => {
    try {
      const { task } = await api.createTask(draft);
      setTasks((prev) => [...prev, task]);
      refresh();
    } catch (err) {
      toast(err.message, 'error');
    }
  };

  const handleUpdateTask = async (id, patch, { silent = false } = {}) => {
    const snapshot = tasks;
    setTasks((prev) => prev.map((t) => (t.id === id ? { ...t, ...patch } : t)));
    try {
      const { task } = await api.updateTask(id, patch);
      setTasks((prev) => prev.map((t) => (t.id === id ? task : t)));
      if (!silent) refresh();
    } catch (err) {
      setTasks(snapshot); // rollback optimistic change
      toast(err.message, 'error');
    }
  };

  const handleDeleteTask = async (id) => {
    const snapshot = tasks;
    setTasks((prev) => prev.filter((t) => t.id !== id));
    setEditing(null);
    try {
      await api.deleteTask(id);
      refresh();
    } catch (err) {
      setTasks(snapshot);
      toast(err.message, 'error');
    }
  };

  const handleCreateProject = async (draft) => {
    try {
      const { project } = await api.createProject(draft);
      setProjects((prev) => [...prev, project]);
      setActiveProjectId(project.id);
      toast(`Project “${project.name}” created`, 'success');
    } catch (err) {
      toast(err.message, 'error');
    }
  };

  const handleDeleteProject = async (id) => {
    if (!window.confirm('Delete this project and all of its tasks?')) return;
    try {
      await api.deleteProject(id);
      if (activeProjectId === id) setActiveProjectId('all');
      refresh();
      toast('Project deleted', 'success');
    } catch (err) {
      toast(err.message, 'error');
    }
  };

  // --- derived data --------------------------------------------------------
  const visibleTasks = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return tasks.filter((task) => {
      if (activeProjectId !== 'all' && task.projectId !== activeProjectId) return false;
      if (priority !== 'all' && task.priority !== priority) return false;
      if (!needle) return true;
      return (
        task.title.toLowerCase().includes(needle) ||
        (task.notes ?? '').toLowerCase().includes(needle)
      );
    });
  }, [tasks, activeProjectId, priority, query]);

  const grouped = useMemo(() => {
    const base = Object.fromEntries(STATUSES.map((s) => [s, []]));
    for (const task of visibleTasks) base[task.status].push(task);
    for (const status of STATUSES) base[status].sort((a, b) => a.position - b.position);
    return base;
  }, [visibleTasks]);

  const activeProject = projects.find((p) => p.id === activeProjectId) ?? null;

  if (booting) {
    return (
      <div className="boot">
        <div className="spinner" />
        <p>Loading TaskFlow…</p>
      </div>
    );
  }

  if (!user) {
    return (
      <AuthScreen
        onAuthed={(payload) => {
          setToken(payload.token);
          setUser(payload.user);
        }}
      />
    );
  }

  return (
    <div className="shell">
      <Sidebar
        projects={projects}
        activeProjectId={activeProjectId}
        onSelect={(id) => {
          setActiveProjectId(id);
          setView('board');
        }}
        onCreate={handleCreateProject}
        onDelete={handleDeleteProject}
        user={user}
        onLogout={logout}
        stats={stats}
      />

      <main className="main">
        <header className="topbar">
          <div>
            <h1>{view === 'dashboard' ? 'Dashboard' : activeProject?.name ?? 'All tasks'}</h1>
            <p className="muted">
              {view === 'dashboard'
                ? 'Delivery health across every project'
                : activeProject?.description || 'Every task, grouped by status'}
            </p>
          </div>

          <div className="topbar-actions">
            <div className="segmented" role="tablist">
              <button
                role="tab"
                aria-selected={view === 'board'}
                className={view === 'board' ? 'active' : ''}
                onClick={() => setView('board')}
              >
                Board
              </button>
              <button
                role="tab"
                aria-selected={view === 'dashboard'}
                className={view === 'dashboard' ? 'active' : ''}
                onClick={() => setView('dashboard')}
              >
                Dashboard
              </button>
            </div>
            <button className="btn ghost" onClick={refresh} disabled={loading}>
              {loading ? 'Syncing…' : 'Refresh'}
            </button>
          </div>
        </header>

        {view === 'board' ? (
          <>
            <div className="filters">
              <input
                className="input search"
                placeholder="Search tasks…"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                aria-label="Search tasks"
              />
              <select
                className="input"
                value={priority}
                onChange={(e) => setPriority(e.target.value)}
                aria-label="Filter by priority"
              >
                <option value="all">All priorities</option>
                <option value="high">High</option>
                <option value="medium">Medium</option>
                <option value="low">Low</option>
              </select>
              <span className="pill">{visibleTasks.length} shown</span>
            </div>

            <Board
              grouped={grouped}
              projects={projects}
              activeProjectId={activeProjectId}
              onCreate={handleCreateTask}
              onMove={handleUpdateTask}
              onEdit={setEditing}
              onDelete={handleDeleteTask}
            />
          </>
        ) : (
          <Dashboard stats={stats} projects={projects} onOpenProject={(id) => {
            setActiveProjectId(id);
            setView('board');
          }} />
        )}
      </main>

      {editing && (
        <TaskModal
          task={editing}
          projects={projects}
          onClose={() => setEditing(null)}
          onSave={async (patch) => {
            await handleUpdateTask(editing.id, patch);
            setEditing(null);
          }}
          onDelete={() => handleDeleteTask(editing.id)}
        />
      )}

      <Toasts toasts={toasts} onDismiss={(id) => setToasts((p) => p.filter((t) => t.id !== id))} />
    </div>
  );
}

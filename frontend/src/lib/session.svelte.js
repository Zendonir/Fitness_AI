import { api } from './api.js';

export const session = $state({ user: null, settings: null, config: null, loaded: false });

export async function loadConfig() {
  session.config = await api.get('/api/auth/config');
  return session.config;
}

export async function loadSession() {
  try {
    const me = await api.get('/api/auth/me', { allow401: true });
    session.user = me.user;
    session.settings = me.settings;
    applyTheme(me.settings);
  } catch {
    session.user = null;
  } finally {
    session.loaded = true;
  }
  return session.user;
}

export async function saveSettings(patch) {
  session.settings = await api.patch('/api/me/settings', patch);
  applyTheme(session.settings);
  return session.settings;
}

export function applyTheme(s) {
  if (!s || typeof document === 'undefined') return;
  const t = s.theme || {};
  const root = document.documentElement;
  const dark = t.mode === 'dark' || (t.mode !== 'light' && matchMedia('(prefers-color-scheme: dark)').matches);
  root.classList.toggle('dark', dark);
  root.style.setProperty('--accent', t.accent || '#22c55e');
  for (const [k, v] of Object.entries(t.macro_colors || {})) root.style.setProperty(`--${k}`, v);
  root.classList.remove('density-compact', 'density-large');
  if (t.density === 'compact') root.classList.add('density-compact');
  if (t.density === 'large') root.classList.add('density-large');
  try { localStorage.setItem('ff_theme', JSON.stringify({ mode: t.mode, accent: t.accent })); } catch {}
}

export const isAdmin = () => session.user?.role === 'admin';
export const isTrainer = () => ['trainer', 'admin'].includes(session.user?.role);

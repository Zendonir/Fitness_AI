// CSS-Variablen für Canvas-Diagramme (ECharts kann keine var() auflösen)
export const cv = (name, fallback = '#888') => {
  if (typeof document === 'undefined') return fallback;
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
};
export const accent = () => cv('--accent', '#22c55e');
export const PALETTE = ['#22c55e', '#3b82f6', '#f59e0b', '#ef4444', '#a855f7', '#14b8a6', '#ec4899', '#84cc16', '#f97316', '#06b6d4', '#6366f1', '#eab308', '#10b981', '#f43f5e', '#8b5cf6', '#0ea5e9', '#d946ef', '#65a30d'];

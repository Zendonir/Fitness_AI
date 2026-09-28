export const toasts = $state({ list: [] });
let n = 0;
export function toast(message, type = 'info', ms = 2800) {
  const id = ++n;
  toasts.list.push({ id, message, type });
  setTimeout(() => (toasts.list = toasts.list.filter((t) => t.id !== id)), ms);
}
export const toastError = (e) => toast(e?.message || String(e), 'error', 4000);

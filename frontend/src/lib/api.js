import { queue, uuid } from './offline.js';
import { net } from './net.svelte.js';

export class ApiError extends Error {
  constructor(status, message, data) {
    super(message);
    this.status = status;
    this.data = data;
  }
}

// Endpunkte, die offline gepuffert werden dürfen (idempotent über client_id)
const QUEUEABLE = [/^\/api\/workouts$/, /^\/api\/workouts\/\d+\/sets$/, /^\/api\/meals$/, /^\/api\/water$/, /^\/api\/body$/, /^\/api\/cardio$/, /^\/api\/sets\/\d+$/];

async function request(method, path, body, opts = {}) {
  const headers = { 'X-Requested-With': 'fitforge', ...(opts.headers || {}) };
  let payload = body;
  if (body !== undefined && !(body instanceof FormData)) {
    headers['Content-Type'] = 'application/json';
    payload = JSON.stringify(body);
  }
  let res;
  try {
    res = await fetch(path, { method, headers, body: payload, credentials: 'same-origin', signal: opts.signal });
  } catch (err) {
    if (err.name === 'AbortError') throw err;
    const canQueue = method !== 'GET' && !(body instanceof FormData) && QUEUEABLE.some((r) => r.test(path));
    if (canQueue && opts.queue !== false) {
      const data = body && typeof body === 'object' ? { ...body, client_id: body.client_id || uuid() } : body;
      await queue.add({ method, path, body: data });
      net.pending = await queue.count();
      return { ...data, id: undefined, _offline: true };
    }
    net.online = false;
    throw new ApiError(0, 'Keine Verbindung zum Server');
  }
  net.online = true;
  if (res.status === 401 && !opts.allow401) {
    if (typeof window !== 'undefined' && !location.pathname.startsWith('/login')) {
      location.href = '/login?next=' + encodeURIComponent(location.pathname + location.search);
    }
    throw new ApiError(401, 'Nicht angemeldet');
  }
  const ct = res.headers.get('content-type') || '';
  const data = ct.includes('application/json') ? await res.json() : opts.raw ? res : await res.text();
  if (!res.ok) {
    let msg = typeof data === 'object' ? data?.detail : data;
    if (Array.isArray(msg)) msg = msg.map((d) => d.msg).join(', ');
    throw new ApiError(res.status, msg || `Fehler ${res.status}`, data);
  }
  return data;
}

export const api = {
  get: (p, o) => request('GET', p, undefined, o),
  post: (p, b, o) => request('POST', p, b ?? {}, o),
  put: (p, b, o) => request('PUT', p, b ?? {}, o),
  patch: (p, b, o) => request('PATCH', p, b ?? {}, o),
  del: (p, b, o) => request('DELETE', p, b, o),
  upload: (p, formData, o) => request('POST', p, formData, o)
};

export function qs(params) {
  const s = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== '') s.set(k, v);
  const str = s.toString();
  return str ? '?' + str : '';
}

let syncing = false;
export async function syncQueue() {
  if (syncing || !navigator.onLine) return 0;
  syncing = true;
  let done = 0;
  try {
    for (const item of await queue.all()) {
      try {
        await request(item.method, item.path, item.body, { queue: false });
        await queue.remove(item.id);
        done++;
      } catch (e) {
        if (e.status === 0) break; // weiterhin offline
        await queue.remove(item.id); // Serverfehler: verwerfen, um Endlosschleifen zu vermeiden
      }
    }
  } finally {
    syncing = false;
    net.pending = await queue.count();
  }
  return done;
}

// Server-Sent Events per fetch (POST mit Body), Callback pro Event
export async function stream(path, body, onEvent, signal) {
  const res = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'fitforge' },
    body: JSON.stringify(body),
    signal
  });
  if (!res.ok) {
    let msg = `Fehler ${res.status}`;
    try { msg = (await res.json()).detail || msg; } catch {}
    throw new ApiError(res.status, msg);
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = '';
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let idx;
    while ((idx = buf.indexOf('\n\n')) >= 0) {
      const block = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      let event = 'message', data = '';
      for (const line of block.split('\n')) {
        if (line.startsWith('event: ')) event = line.slice(7);
        else if (line.startsWith('data: ')) data += line.slice(6);
      }
      try { onEvent(event, JSON.parse(data || '{}')); } catch {}
    }
  }
}

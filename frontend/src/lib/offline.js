// Offline-Queue in IndexedDB: schreibende Requests werden bei fehlender Verbindung gespeichert
// und beim nächsten "online"-Ereignis (oder App-Start) in Reihenfolge nachgesendet.
const DB_NAME = 'fitforge';
const STORE = 'queue';

function openDb() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, 1);
    req.onupgradeneeded = () => req.result.createObjectStore(STORE, { keyPath: 'id', autoIncrement: true });
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

async function tx(mode, fn) {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const t = db.transaction(STORE, mode);
    const result = fn(t.objectStore(STORE));
    t.oncomplete = () => resolve(result?.result ?? result);
    t.onerror = () => reject(t.error);
  });
}

export const queue = {
  add: (item) => tx('readwrite', (s) => s.add({ ...item, created: Date.now() })),
  all: () => tx('readonly', (s) => s.getAll()),
  remove: (id) => tx('readwrite', (s) => s.delete(id)),
  count: () => tx('readonly', (s) => s.count())
};

export function uuid() {
  return crypto.randomUUID ? crypto.randomUUID() : 'id-' + Date.now() + '-' + Math.random().toString(16).slice(2);
}

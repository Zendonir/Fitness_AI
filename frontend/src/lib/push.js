import { api } from './api.js';

const urlB64ToUint8 = (s) => {
  const pad = '='.repeat((4 - (s.length % 4)) % 4);
  const raw = atob((s + pad).replace(/-/g, '+').replace(/_/g, '/'));
  return Uint8Array.from(raw, (c) => c.charCodeAt(0));
};

export const pushSupported = () => 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window;
export const isStandalone = () => matchMedia('(display-mode: standalone)').matches || navigator.standalone === true;

export async function currentSubscription() {
  if (!pushSupported()) return null;
  const reg = await navigator.serviceWorker.ready;
  return reg.pushManager.getSubscription();
}

export async function enablePush() {
  const cfg = await api.get('/api/push/config');
  if (!cfg.enabled) throw new Error('Push ist auf dem Server nicht konfiguriert (VAPID-Schlüssel fehlen).');
  if (!pushSupported()) throw new Error('Dieses Gerät unterstützt kein Web-Push. Auf dem iPhone: App zum Home-Bildschirm hinzufügen (iOS 16.4+).');
  const perm = await Notification.requestPermission();
  if (perm !== 'granted') throw new Error('Benachrichtigungen wurden nicht erlaubt.');
  const reg = await navigator.serviceWorker.ready;
  const sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: urlB64ToUint8(cfg.public_key) });
  await api.post('/api/push/subscribe', sub.toJSON());
  return sub;
}

export async function disablePush() {
  const sub = await currentSubscription();
  if (sub) {
    await api.post('/api/push/unsubscribe', sub.toJSON());
    await sub.unsubscribe();
  }
}

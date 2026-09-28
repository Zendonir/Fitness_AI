import { session } from './session.svelte.js';

const LB = 2.20462;
const MI = 0.621371;
const KJ = 4.184;

const u = () => session.settings?.units || { weight: 'kg', distance: 'km', energy: 'kcal' };

export const weightUnit = () => u().weight;
export const energyUnit = () => u().energy;
export const distUnit = () => u().distance;

export function toDisplayWeight(kg) {
  if (kg == null) return null;
  return u().weight === 'lb' ? Math.round(kg * LB * 10) / 10 : Math.round(kg * 100) / 100;
}
export function fromDisplayWeight(v) {
  if (v === '' || v == null) return null;
  const n = Number(String(v).replace(',', '.'));
  return u().weight === 'lb' ? n / LB : n;
}
export const fmtWeight = (kg, digits = 1) => (kg == null ? '–' : `${fmtNum(toDisplayWeight(kg), digits)} ${u().weight}`);
export function energy(kcal) {
  if (kcal == null) return null;
  return u().energy === 'kJ' ? Math.round(kcal * KJ) : Math.round(kcal);
}
export const fmtEnergy = (kcal) => (kcal == null ? '–' : `${fmtNum(energy(kcal), 0)} ${u().energy}`);
export function fmtDist(m) {
  if (m == null) return '–';
  const km = m / 1000;
  return u().distance === 'mi' ? `${fmtNum(km * MI, 2)} mi` : `${fmtNum(km, 2)} km`;
}
export function fmtNum(n, digits = 1) {
  if (n == null || Number.isNaN(n)) return '–';
  return Number(n).toLocaleString('de-DE', { maximumFractionDigits: digits, minimumFractionDigits: 0 });
}
export function fmtDuration(sec) {
  if (!sec) return '0:00';
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = Math.floor(sec % 60);
  return h ? `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}` : `${m}:${String(s).padStart(2, '0')}`;
}
export function pace(sec, m) {
  if (!sec || !m) return '–';
  const perKm = sec / (m / 1000) / (u().distance === 'mi' ? MI : 1);
  return `${Math.floor(perKm / 60)}:${String(Math.round(perKm % 60)).padStart(2, '0')} /${u().distance}`;
}

export const today = () => isoDate(new Date());
export function isoDate(d) {
  const x = new Date(d);
  return `${x.getFullYear()}-${String(x.getMonth() + 1).padStart(2, '0')}-${String(x.getDate()).padStart(2, '0')}`;
}
export function addDays(iso, n) {
  const d = new Date(iso + 'T12:00:00');
  d.setDate(d.getDate() + n);
  return isoDate(d);
}
export function fmtDate(iso, opts = { weekday: 'short', day: '2-digit', month: '2-digit' }) {
  if (!iso) return '';
  const d = typeof iso === 'string' && iso.length === 10 ? new Date(iso + 'T12:00:00') : new Date(iso);
  return d.toLocaleDateString('de-DE', opts);
}
export function relDay(iso) {
  const t = today();
  if (iso === t) return 'Heute';
  if (iso === addDays(t, -1)) return 'Gestern';
  if (iso === addDays(t, 1)) return 'Morgen';
  return fmtDate(iso);
}
export function fmtTime(ts) {
  return new Date(ts).toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' });
}

export const MUSCLES = {
  chest: 'Brust', front_delts: 'Vordere Schulter', side_delts: 'Seitliche Schulter', rear_delts: 'Hintere Schulter',
  biceps: 'Bizeps', triceps: 'Trizeps', forearms: 'Unterarme', abs: 'Bauch', obliques: 'Seitl. Bauch', lats: 'Latissimus',
  traps: 'Trapez', upper_back: 'Oberer Rücken', lower_back: 'Unterer Rücken', glutes: 'Gesäß', quads: 'Quadrizeps',
  hamstrings: 'Beinbeuger', adductors: 'Adduktoren', calves: 'Waden'
};
export const EQUIPMENT = {
  barbell: 'Langhantel', dumbbell: 'Kurzhantel', machine: 'Maschine', cable: 'Kabelzug', bodyweight: 'Körpergewicht',
  kettlebell: 'Kettlebell', band: 'Band', other: 'Sonstiges'
};
export const CARDIO = { run: 'Laufen', bike: 'Rad', row: 'Rudern', walk: 'Gehen', swim: 'Schwimmen', other: 'Sonstiges' };
export const GOALS = { bulk: 'Aufbau', maintain: 'Erhalt', cut: 'Moderates Defizit' };

// Übungsanimationen aus ExerciseGymGifsDB (https://github.com/JahelCuadrado/ExerciseGymGifsDB).
// Die GIFs werden direkt vom CDN (bzw. einem eigenen Spiegel) geladen – FitForge speichert nur die ID.
import { session } from './session.svelte.js';

export const mediaBase = () => session.config?.exercise_media_base || '';
export const mediaEnabled = () => !!mediaBase() && session.settings?.show_exercise_media !== false;
export const gifUrl = (id) => (id && mediaBase() ? `${mediaBase()}/${id}.gif` : null);
export const thumbUrl = (id) => (id && mediaBase() ? `${mediaBase()}/${id}.thumb.webp` : null);

// Muskelgruppen der Bibliothek -> FitForge
const MUSCLE_MAP = {
  pectorals: ['chest'], biceps: ['biceps'], triceps: ['triceps'], forearms: ['forearms'], abs: ['abs'], lats: ['lats'],
  traps: ['traps'], 'upper-back': ['upper_back'], spine: ['lower_back'], glutes: ['glutes'], quads: ['quads'],
  hamstrings: ['hamstrings'], adductors: ['adductors'], abductors: ['glutes'], calves: ['calves'], 'serratus-anterior': ['chest'],
  'levator-scapulae': ['traps'], cardio: []
};
const EQUIP_MAP = { barbell: 'barbell', 'ez-bar': 'barbell', dumbbell: 'dumbbell', cable: 'cable', machine: 'machine', lever: 'machine',
  smith: 'machine', sled: 'machine', bodyweight: 'bodyweight', band: 'band', kettlebell: 'kettlebell', other: 'other' };
export const LIB_MUSCLES = {
  pectorals: 'Brust', delts: 'Schultern', lats: 'Latissimus', 'upper-back': 'Oberer Rücken', traps: 'Trapez', spine: 'Unterer Rücken',
  biceps: 'Bizeps', triceps: 'Trizeps', forearms: 'Unterarme', abs: 'Bauch', quads: 'Quadrizeps', hamstrings: 'Beinbeuger',
  glutes: 'Gesäß', adductors: 'Adduktoren', abductors: 'Abduktoren', calves: 'Waden', cardio: 'Cardio', 'serratus-anterior': 'Sägemuskel'
};

function mapDelts(slug) {
  if (/rear|reverse|face/.test(slug)) return ['rear_delts'];
  if (/lateral|side|upright/.test(slug)) return ['side_delts'];
  return ['front_delts'];
}
export function toFitforge(ex) {
  const prim = ex.muscle === 'delts' ? mapDelts(ex.slug) : MUSCLE_MAP[ex.muscle] || [];
  const sec = [...new Set((ex.secondaryMuscles || []).flatMap((m) => (m === 'delts' ? ['front_delts'] : MUSCLE_MAP[m] || [])))].filter((m) => !prim.includes(m));
  return {
    name: ex.name,
    category: ex.category === 'cardio' ? 'cardio' : ex.category === 'stretching' ? 'mobility' : 'compound',
    equipment: EQUIP_MAP[ex.equipment] || 'other',
    primary_muscles: prim,
    secondary_muscles: sec,
    instructions: (ex.instructions || []).join('\n'),
    media_id: ex.id
  };
}

const cache = new Map();
async function getJson(path) {
  if (cache.has(path)) return cache.get(path);
  const res = await fetch(`${mediaBase()}${path}`);
  if (!res.ok) throw new Error('Übungsbibliothek nicht erreichbar');
  const data = await res.json();
  cache.set(path, data);
  return data;
}
export async function libraryMuscle(muscle, lang = 'en') {
  const d = await getJson(`/api/${lang}/muscles/${muscle}.json`);
  return d.exercises || d;
}

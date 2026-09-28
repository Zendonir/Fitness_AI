<script>
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { api } from '$lib/api.js';
  import { toastError } from '$lib/toast.svelte.js';
  import { EQUIPMENT, MUSCLES } from '$lib/units.js';
  import Header from '$components/Header.svelte';
  import Icon from '$components/Icon.svelte';
  import Sheet from '$components/Sheet.svelte';
  import Skeleton from '$components/Skeleton.svelte';
  import ExerciseMedia from '$components/ExerciseMedia.svelte';
  import MediaLibrary from '$components/MediaLibrary.svelte';
  import { mediaEnabled, toFitforge } from '$lib/media.js';

  let list = $state(null);
  let q = $state(''), muscle = $state(''), equipment = $state('');
  let newOpen = $state(false);
  let libOpen = $state(false), libMode = $state('import');
  let form = $state({ name: '', media_id: null, category: 'compound', equipment: 'barbell', primary_muscles: [], secondary_muscles: [], instructions: '', custom_fields: [], progression: { rep_min: 8, rep_max: 12, increment_kg: 2.5, all_sets: true } });

  onMount(async () => { list = await api.get('/api/exercises'); });
  const filtered = $derived((list || []).filter((e) => (!q || e.name.toLowerCase().includes(q.toLowerCase()))
    && (!muscle || e.primary_muscles.includes(muscle) || e.secondary_muscles.includes(muscle)) && (!equipment || e.equipment === equipment)));
  function toggle(arr, m) { return arr.includes(m) ? arr.filter((x) => x !== m) : [...arr, m]; }
  async function importFromLibrary(e) {
    try {
      const created = await api.post('/api/exercises', toFitforge(e));
      goto(`/training/exercises/${created.id}`);
    } catch (err) { toastError(err); }
  }
  function pickMedia(e) {
    const f = toFitforge(e);
    form = { ...form, media_id: f.media_id, name: form.name || f.name, equipment: f.equipment,
      primary_muscles: form.primary_muscles.length ? form.primary_muscles : f.primary_muscles,
      secondary_muscles: form.secondary_muscles.length ? form.secondary_muscles : f.secondary_muscles };
  }
  async function create() {
    try {
      const e = await api.post('/api/exercises', form);
      goto(`/training/exercises/${e.id}`);
    } catch (err) { toastError(err); }
  }
</script>

<Header title="Übungen" back="/training">
  {#snippet actions()}
    {#if mediaEnabled()}<button class="btn-soft btn-sm" onclick={() => { libMode = 'import'; libOpen = true; }}><Icon name="image" size={16} /> Bibliothek</button>{/if}
    <button class="btn-primary btn-sm" onclick={() => (newOpen = true)}><Icon name="plus" size={16} /> Eigene</button>
  {/snippet}
</Header>
<div class="px-4">
  <input class="input mb-2" placeholder="Suchen …" bind:value={q} />
  <div class="mb-3 grid grid-cols-2 gap-2">
    <select class="input py-2" bind:value={muscle}><option value="">Alle Muskeln</option>{#each Object.entries(MUSCLES) as [k, l]}<option value={k}>{l}</option>{/each}</select>
    <select class="input py-2" bind:value={equipment}><option value="">Alles Equipment</option>{#each Object.entries(EQUIPMENT) as [k, l]}<option value={k}>{l}</option>{/each}</select>
  </div>
  {#if !list}<Skeleton lines={6} h="h-12" />{:else}
    <div class="card p-0">
      {#each filtered as e (e.id)}
        <a href="/training/exercises/{e.id}" class="list-row">
          <ExerciseMedia id={e.media_id} name={e.name} class="h-12 w-12 rounded-xl" zoom={false} />
          <div class="min-w-0 flex-1"><div class="truncate font-medium">{e.name}{#if e.own}<span class="ml-1 text-xs text-accent">eigene</span>{/if}</div>
            <div class="truncate text-xs text-muted">{e.primary_muscles.map((m) => MUSCLES[m]).join(', ')} · {EQUIPMENT[e.equipment]}</div></div>
          <Icon name="right" size={18} class="text-muted" />
        </a>
      {/each}
    </div>
  {/if}
</div>

<Sheet bind:open={newOpen} title="Eigene Übung" full>
  <div class="space-y-3">
    {#if mediaEnabled()}
      <div class="flex items-center gap-3">
        <ExerciseMedia id={form.media_id} name={form.name} class="h-20 w-20 rounded-2xl" />
        <button class="btn-soft btn-sm" onclick={() => { libMode = 'pick'; libOpen = true; }}><Icon name="image" size={16} /> {form.media_id ? 'Animation ändern' : 'Animation wählen'}</button>
      </div>
    {/if}
    <input class="input" placeholder="Name" bind:value={form.name} />
    <div class="grid grid-cols-2 gap-2">
      <select class="input" bind:value={form.category}><option value="compound">Grundübung</option><option value="isolation">Isolation</option><option value="cardio">Cardio</option><option value="mobility">Mobilität</option></select>
      <select class="input" bind:value={form.equipment}>{#each Object.entries(EQUIPMENT) as [k, l]}<option value={k}>{l}</option>{/each}</select>
    </div>
    <span class="label">Hauptmuskeln</span>
    <div class="flex flex-wrap gap-1">{#each Object.entries(MUSCLES) as [k, l]}<button class={form.primary_muscles.includes(k) ? 'chip-active' : 'chip'} onclick={() => (form.primary_muscles = toggle(form.primary_muscles, k))}>{l}</button>{/each}</div>
    <span class="label">Hilfsmuskeln</span>
    <div class="flex flex-wrap gap-1">{#each Object.entries(MUSCLES) as [k, l]}<button class={form.secondary_muscles.includes(k) ? 'chip-active' : 'chip'} onclick={() => (form.secondary_muscles = toggle(form.secondary_muscles, k))}>{l}</button>{/each}</div>
    <textarea class="input" rows="2" placeholder="Technik-Hinweise" bind:value={form.instructions}></textarea>
    <button class="btn-primary w-full" disabled={!form.name} onclick={create}>Anlegen</button>
  </div>
</Sheet>

<MediaLibrary bind:open={libOpen} title={libMode === 'import' ? 'Übung aus der Bibliothek übernehmen' : 'Animation wählen'}
  onpick={(e) => (libMode === 'import' ? importFromLibrary(e) : pickMedia(e))} />

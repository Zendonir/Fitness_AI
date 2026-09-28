<script>
  import { onMount } from 'svelte';
  import { api } from '$lib/api.js';
  import { toast, toastError } from '$lib/toast.svelte.js';
  import { CARDIO, fmtDate, fmtDist, fmtDuration, pace, distUnit } from '$lib/units.js';
  import { uuid } from '$lib/offline.js';
  import Header from '$components/Header.svelte';
  import Icon from '$components/Icon.svelte';
  import Sheet from '$components/Sheet.svelte';
  import Empty from '$components/Empty.svelte';
  import Skeleton from '$components/Skeleton.svelte';

  let list = $state(null);
  let addOpen = $state(false);
  let form = $state(reset());
  let fileInput = $state();
  function reset() {
    const now = new Date();
    return { kind: 'run', date: now.toISOString().slice(0, 16), minutes: 30, seconds: 0, distance: 5, avg_hr: null, max_hr: null, kcal: null, notes: '' };
  }
  async function load() { list = await api.get('/api/cardio'); }
  onMount(load);

  async function save() {
    try {
      const km = Number(String(form.distance).replace(',', '.')) || null;
      await api.post('/api/cardio', {
        kind: form.kind, started_at: new Date(form.date).toISOString(), duration_s: Number(form.minutes) * 60 + Number(form.seconds),
        distance_m: km ? (distUnit() === 'mi' ? km * 1609.34 : km * 1000) : null, avg_hr: form.avg_hr || null, max_hr: form.max_hr || null,
        kcal: form.kcal || null, notes: form.notes, client_id: uuid()
      });
      addOpen = false; form = reset(); toast('Gespeichert', 'success'); load();
    } catch (e) { toastError(e); }
  }
  async function importFile(e) {
    const f = e.currentTarget.files?.[0];
    if (!f) return;
    const fd = new FormData();
    fd.append('file', f);
    try {
      const r = await api.upload('/api/cardio/import', fd);
      toast(`${r.imported} importiert${r.skipped ? `, ${r.skipped} Duplikate übersprungen` : ''}`, 'success');
      load();
    } catch (err) { toastError(err); } finally { e.currentTarget.value = ''; }
  }
  async function del(c) {
    if (!confirm('Einheit löschen?')) return;
    await api.del(`/api/cardio/${c.id}`);
    load();
  }
</script>

<Header title="Ausdauer" back="/training">
  {#snippet actions()}
    <button class="p-2 text-muted" onclick={() => fileInput.click()} aria-label="Import"><Icon name="download" /></button>
    <button class="btn-primary btn-sm" onclick={() => (addOpen = true)}><Icon name="plus" size={16} /></button>
  {/snippet}
</Header>
<input type="file" accept=".gpx,.csv,application/gpx+xml,text/csv" class="hidden" bind:this={fileInput} onchange={importFile} />

<div class="px-4">
  <p class="mb-3 text-sm text-muted">Importiere GPX-Dateien (Strava, Garmin, Komoot) oder CSV (Spalten: date;type;duration;distance_km;avg_hr).</p>
  {#if !list}<Skeleton />{:else if !list.length}
    <Empty icon="run" title="Noch keine Ausdauereinheiten" />
  {:else}
    <div class="card p-0">
      {#each list as c}
        <div class="list-row">
          <div class="rounded-xl bg-surface-2 p-2"><Icon name="run" size={18} /></div>
          <div class="flex-1"><div class="font-medium">{CARDIO[c.kind]} · {fmtDist(c.distance_m)}</div>
            <div class="text-xs text-muted">{fmtDate(c.started_at)} · {fmtDuration(c.duration_s)} · {pace(c.duration_s, c.distance_m)}{c.avg_hr ? ` · Ø ${c.avg_hr} bpm` : ''}{c.source !== 'manual' ? ` · ${c.source.toUpperCase()}` : ''}</div></div>
          <button class="p-1 text-muted" onclick={() => del(c)} aria-label="Löschen"><Icon name="trash" size={16} /></button>
        </div>
      {/each}
    </div>
  {/if}
</div>

<Sheet bind:open={addOpen} title="Ausdauer eintragen">
  <div class="space-y-3">
    <div class="flex flex-wrap gap-1">{#each Object.entries(CARDIO) as [k, l]}<button class={form.kind === k ? 'chip-active' : 'chip'} onclick={() => (form.kind = k)}>{l}</button>{/each}</div>
    <input type="datetime-local" class="input" bind:value={form.date} />
    <div class="grid grid-cols-3 gap-2">
      <label><span class="label">Minuten</span><input class="input" type="number" inputmode="numeric" bind:value={form.minutes} /></label>
      <label><span class="label">Sekunden</span><input class="input" type="number" inputmode="numeric" bind:value={form.seconds} /></label>
      <label><span class="label">Distanz ({distUnit()})</span><input class="input" inputmode="decimal" bind:value={form.distance} /></label>
      <label><span class="label">Ø Puls</span><input class="input" type="number" bind:value={form.avg_hr} /></label>
      <label><span class="label">Max Puls</span><input class="input" type="number" bind:value={form.max_hr} /></label>
      <label><span class="label">kcal</span><input class="input" type="number" bind:value={form.kcal} /></label>
    </div>
    <button class="btn-primary w-full" onclick={save}>Speichern</button>
  </div>
</Sheet>

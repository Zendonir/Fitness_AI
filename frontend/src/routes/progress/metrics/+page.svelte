<script>
  import { onMount } from 'svelte';
  import { api } from '$lib/api.js';
  import { toast, toastError } from '$lib/toast.svelte.js';
  import { fmtDate, today } from '$lib/units.js';
  import Header from '$components/Header.svelte';
  import Icon from '$components/Icon.svelte';
  import Sheet from '$components/Sheet.svelte';
  import Empty from '$components/Empty.svelte';

  let metrics = $state([]);
  let values = $state({});
  let day = $state(today());
  let form = $state(null);
  const KIND = { number: 'Zahl', scale: 'Skala', bool: 'Ja/Nein', text: 'Text' };
  async function load() { metrics = await api.get('/api/metrics'); }
  onMount(load);

  async function log(m, v) {
    try {
      await api.post('/api/metrics/entries', { metric_id: m.id, day, value: v });
      toast(`${m.name} gespeichert`, 'success'); load();
    } catch (e) { toastError(e); }
  }
  async function save() {
    try {
      const body = { ...form, scale_min: Number(form.scale_min), scale_max: Number(form.scale_max), target: form.target === '' || form.target == null ? null : Number(form.target) };
      if (form.id) await api.patch(`/api/metrics/${form.id}`, body); else await api.post('/api/metrics', body);
      form = null; load();
    } catch (e) { toastError(e); }
  }
  async function del() { if (confirm('Metrik inkl. aller Werte löschen?')) { await api.del(`/api/metrics/${form.id}`); form = null; load(); } }
</script>

<Header title="Eigene Metriken" back="/progress">
  {#snippet actions()}<button class="btn-primary btn-sm" onclick={() => (form = { name: '', kind: 'number', unit: '', scale_min: 1, scale_max: 10, target: '', chart: 'line', color: null })}><Icon name="plus" size={16} /></button>{/snippet}
</Header>
<div class="space-y-3 px-4">
  <input type="date" class="input" bind:value={day} />
  {#each metrics.filter((m) => !m.archived) as m}
    <div class="card">
      <div class="mb-2 flex items-center justify-between">
        <div><div class="font-semibold">{m.name}</div><div class="text-xs text-muted">{KIND[m.kind]}{m.unit ? ` · ${m.unit}` : ''}{m.last ? ` · zuletzt ${m.last.value_text ?? m.last.value_num} (${fmtDate(m.last.day)})` : ''}</div></div>
        <button class="text-muted" onclick={() => (form = { ...m })} aria-label="Bearbeiten"><Icon name="settings" size={18} /></button>
      </div>
      {#if m.kind === 'scale'}
        <div class="no-scrollbar flex gap-1 overflow-x-auto">
          {#each Array.from({ length: m.scale_max - m.scale_min + 1 }, (_, i) => m.scale_min + i) as v}<button class="chip min-w-10 justify-center" onclick={() => log(m, v)}>{v}</button>{/each}
        </div>
      {:else if m.kind === 'bool'}
        <div class="flex gap-2"><button class="btn-soft flex-1" onclick={() => log(m, true)}>Ja</button><button class="btn-soft flex-1" onclick={() => log(m, false)}>Nein</button></div>
      {:else}
        <form class="flex gap-2" onsubmit={(e) => { e.preventDefault(); log(m, values[m.id]); values[m.id] = ''; }}>
          <input class="input" inputmode={m.kind === 'number' ? 'decimal' : 'text'} placeholder={m.kind === 'number' ? `Wert${m.unit ? ` in ${m.unit}` : ''}` : 'Notiz'} bind:value={values[m.id]} />
          <button class="btn-primary"><Icon name="check" /></button>
        </form>
      {/if}
    </div>
  {:else}
    <Empty icon="chart" title="Noch keine Metriken" text="Z. B. Schlaf, Stimmung, Schritte, Körperfett oder Energielevel – mit eigenen Diagrammen." />
  {/each}
</div>

<Sheet open={!!form} title={form?.id ? 'Metrik bearbeiten' : 'Neue Metrik'} onclose={() => (form = null)}>
  {#if form}
    <div class="space-y-3">
      <input class="input" placeholder="Name, z. B. Schlafqualität" bind:value={form.name} />
      <div class="grid grid-cols-2 gap-2">
        <select class="input" bind:value={form.kind} disabled={!!form.id}>{#each Object.entries(KIND) as [k, l]}<option value={k}>{l}</option>{/each}</select>
        <input class="input" placeholder="Einheit" bind:value={form.unit} />
      </div>
      {#if form.kind === 'scale'}
        <div class="grid grid-cols-2 gap-2"><label><span class="label">Min</span><input class="input" type="number" bind:value={form.scale_min} /></label><label><span class="label">Max</span><input class="input" type="number" bind:value={form.scale_max} /></label></div>
      {/if}
      <div class="grid grid-cols-3 gap-2">
        <label><span class="label">Zielwert</span><input class="input" type="number" bind:value={form.target} /></label>
        <label><span class="label">Diagramm</span><select class="input" bind:value={form.chart}><option value="line">Linie</option><option value="bar">Balken</option></select></label>
        <label><span class="label">Farbe</span><input type="color" class="input h-12 p-1" bind:value={form.color} /></label>
      </div>
      <button class="btn-primary w-full" disabled={!form.name} onclick={save}>Speichern</button>
      {#if form.id}<button class="btn-ghost w-full text-danger" onclick={del}>Löschen</button>{/if}
    </div>
  {/if}
</Sheet>

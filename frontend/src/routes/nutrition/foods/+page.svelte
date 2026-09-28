<script>
  import { onMount } from 'svelte';
  import { api } from '$lib/api.js';
  import { toast, toastError } from '$lib/toast.svelte.js';
  import { energy, fmtNum } from '$lib/units.js';
  import Header from '$components/Header.svelte';
  import Icon from '$components/Icon.svelte';
  import Sheet from '$components/Sheet.svelte';
  import ShareSheet from '$components/ShareSheet.svelte';
  import Empty from '$components/Empty.svelte';

  const empty = () => ({ name: '', brand: '', barcode: '', kcal: 0, protein: 0, carbs: 0, sugar: 0, fat: 0, sat_fat: 0, fiber: 0, salt: 0, serving_g: null, serving_label: '' });
  let foods = $state([]);
  let form = $state(null);
  let busy = $state(false);
  let share = $state({ open: false, id: null });
  async function load() { foods = await api.get('/api/foods/mine'); }
  onMount(load);

  async function save() {
    try {
      const body = Object.fromEntries(Object.entries(form).map(([k, v]) => [k, ['name', 'brand', 'barcode', 'serving_label'].includes(k) ? v || (k === 'barcode' ? null : '') : v === '' || v === null ? (k === 'serving_g' ? null : 0) : Number(v)]));
      if (form.id) await api.patch(`/api/foods/${form.id}`, body); else await api.post('/api/foods', body);
      form = null; toast('Gespeichert', 'success'); load();
    } catch (e) { toastError(e); }
  }
  async function del() {
    if (!confirm('Löschen?')) return;
    await api.del(`/api/foods/${form.id}`); form = null; load();
  }
  async function label(e) {
    const f = e.currentTarget.files?.[0];
    if (!f) return;
    busy = true;
    const fd = new FormData(); fd.append('file', f);
    try {
      const r = (await api.upload('/api/coach/vision/label', fd)).result;
      form = { ...empty(), ...Object.fromEntries(Object.entries(r).filter(([, v]) => v !== null)), source: 'label' };
      toast('Etikett erkannt – bitte prüfen', 'success');
    } catch (err) { toastError(err); } finally { busy = false; e.currentTarget.value = ''; }
  }
</script>

<Header title="Eigene Lebensmittel" back="/nutrition">
  {#snippet actions()}
    <label class="p-2 text-muted" aria-label="Etikett fotografieren"><Icon name="camera" /><input type="file" accept="image/*" capture="environment" class="hidden" onchange={label} /></label>
    <button class="btn-primary btn-sm" onclick={() => (form = empty())}><Icon name="plus" size={16} /></button>
  {/snippet}
</Header>
<div class="px-4">
  {#if busy}<p class="mb-3 rounded-xl bg-accent/10 p-3 text-sm">Etikett wird gelesen …</p>{/if}
  {#if !foods.length}<Empty icon="apple" title="Noch keine eigenen Lebensmittel" text="Lege sie manuell an oder fotografiere ein Nährwertetikett." />{:else}
    <div class="card p-0">
      {#each foods as f}
        <button class="list-row w-full text-left" onclick={() => (form = { ...f })}>
          <div class="flex-1"><div class="text-sm font-medium">{f.name}</div><div class="text-xs text-muted">{f.brand} · {fmtNum(f.protein, 1)} P · {fmtNum(f.carbs, 1)} K · {fmtNum(f.fat, 1)} F / 100 g · {f.visibility !== 'private' ? 'geteilt' : 'privat'}</div></div>
          <span class="text-sm">{fmtNum(energy(f.kcal), 0)}</span>
        </button>
      {/each}
    </div>
  {/if}
</div>

<Sheet open={!!form} title={form?.id ? 'Lebensmittel bearbeiten' : 'Neues Lebensmittel'} onclose={() => (form = null)} full>
  {#if form}
    <div class="space-y-3">
      <input class="input" placeholder="Name" bind:value={form.name} />
      <div class="grid grid-cols-2 gap-2">
        <input class="input" placeholder="Marke" bind:value={form.brand} />
        <input class="input" placeholder="Barcode (EAN)" inputmode="numeric" bind:value={form.barcode} />
      </div>
      <p class="section-title">Nährwerte pro 100 g</p>
      <div class="grid grid-cols-2 gap-2">
        {#each [['kcal', 'Energie (kcal)'], ['protein', 'Eiweiß'], ['carbs', 'Kohlenhydrate'], ['sugar', 'davon Zucker'], ['fat', 'Fett'], ['sat_fat', 'davon gesättigt'], ['fiber', 'Ballaststoffe'], ['salt', 'Salz']] as [k, l]}
          <label><span class="label">{l}</span><input class="input" inputmode="decimal" type="number" step="0.1" bind:value={form[k]} /></label>
        {/each}
        <label><span class="label">Portion (g)</span><input class="input" inputmode="decimal" type="number" bind:value={form.serving_g} /></label>
        <label><span class="label">Portionsname</span><input class="input" placeholder="1 Becher" bind:value={form.serving_label} /></label>
      </div>
      <button class="btn-primary w-full" disabled={!form.name} onclick={save}>Speichern</button>
      {#if form.id}
        <div class="flex gap-2"><button class="btn-soft flex-1" onclick={() => (share = { open: true, id: form.id })}><Icon name="share" size={18} /> Teilen</button>
          <button class="btn-soft flex-1 text-danger" onclick={del}><Icon name="trash" size={18} /> Löschen</button></div>
      {/if}
    </div>
  {/if}
</Sheet>
{#if share.id}<ShareSheet bind:open={share.open} type="food" id={share.id} />{/if}

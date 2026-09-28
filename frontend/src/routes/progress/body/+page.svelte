<script>
  import { onMount } from 'svelte';
  import { page } from '$app/state';
  import { api } from '$lib/api.js';
  import { toast, toastError } from '$lib/toast.svelte.js';
  import { fmtDate, fmtWeight, fromDisplayWeight, today, weightUnit } from '$lib/units.js';
  import { uuid } from '$lib/offline.js';
  import Header from '$components/Header.svelte';
  import Icon from '$components/Icon.svelte';
  import Sheet from '$components/Sheet.svelte';
  import Empty from '$components/Empty.svelte';

  let tab = $state('entries');
  let body = $state(null);
  let photos = $state([]);
  let addOpen = $state(page.url.searchParams.get('add') === '1');
  let form = $state(blank());
  let compare = $state({ a: null, b: null, pos: 50 });
  let pose = $state('front');
  function blank() { return { day: today(), weight: '', body_fat_pct: '', waist_cm: '', chest_cm: '', hips_cm: '', arm_cm: '', thigh_cm: '', neck_cm: '', notes: '' }; }

  async function load() {
    [body, photos] = await Promise.all([api.get('/api/body?days=365'), api.get('/api/photos')]);
    const ps = photos.filter((p) => p.pose === pose);
    compare.a = ps.at(-1)?.id ?? null;
    compare.b = ps[0]?.id ?? null;
  }
  onMount(load);

  async function save() {
    const num = (v) => (v === '' || v === null ? null : Number(String(v).replace(',', '.')));
    try {
      await api.post('/api/body', { day: form.day, weight_kg: form.weight ? fromDisplayWeight(form.weight) : null, body_fat_pct: num(form.body_fat_pct),
        waist_cm: num(form.waist_cm), chest_cm: num(form.chest_cm), hips_cm: num(form.hips_cm), arm_cm: num(form.arm_cm), thigh_cm: num(form.thigh_cm),
        neck_cm: num(form.neck_cm), notes: form.notes, client_id: uuid() });
      addOpen = false; form = blank(); toast('Gespeichert', 'success'); load();
    } catch (e) { toastError(e); }
  }
  async function del(e) { if (confirm('Messung löschen?')) { await api.del(`/api/body/${e.id}`); load(); } }
  async function upload(ev) {
    const f = ev.currentTarget.files?.[0];
    if (!f) return;
    const fd = new FormData(); fd.append('file', f); fd.append('pose', pose); fd.append('day', today());
    try { await api.upload('/api/photos', fd); toast('Foto gespeichert (nur lokal auf deinem Server)', 'success'); load(); } catch (e) { toastError(e); }
    ev.currentTarget.value = '';
  }
  async function delPhoto(p) { if (confirm('Foto löschen?')) { await api.del(`/api/photos/${p.id}`); load(); } }
  const posePhotos = $derived(photos.filter((p) => p.pose === pose));
  const photoA = $derived(photos.find((p) => p.id == compare.a));
  const photoB = $derived(photos.find((p) => p.id == compare.b));
</script>

<Header title="Körperwerte" back="/progress">
  {#snippet actions()}<button class="btn-primary btn-sm" onclick={() => (addOpen = true)}><Icon name="plus" size={16} /></button>{/snippet}
</Header>
<div class="space-y-3 px-4">
  <div class="flex gap-1.5">{#each [['entries', 'Messungen'], ['photos', 'Fotos']] as [k, l]}<button class={tab === k ? 'chip-active' : 'chip'} onclick={() => (tab = k)}>{l}</button>{/each}</div>

  {#if tab === 'entries'}
    {#if body}
      <div class="grid grid-cols-3 gap-2 text-center">
        <div class="card p-3"><div class="text-xs text-muted">Aktuell (Ø7)</div><div class="font-bold">{body.weight_trend.length ? fmtWeight(body.weight_trend.at(-1).avg) : '–'}</div></div>
        <div class="card p-3"><div class="text-xs text-muted">7 Tage</div><div class="font-bold">{body.weekly_change_kg != null ? (body.weekly_change_kg > 0 ? '+' : '') + fmtWeight(body.weekly_change_kg, 2) : '–'}</div></div>
        <div class="card p-3"><div class="text-xs text-muted">KFA</div><div class="font-bold">{body.latest.body_fat_pct ?? '–'} %</div></div>
      </div>
      <div class="card p-0">
        {#each body.entries as e}
          <div class="list-row text-sm">
            <span class="w-20 text-muted">{fmtDate(e.day)}</span>
            <span class="flex-1">{e.weight_kg ? fmtWeight(e.weight_kg) : ''}{e.body_fat_pct ? ` · ${e.body_fat_pct} %` : ''}{e.waist_cm ? ` · Taille ${e.waist_cm}` : ''}{e.source !== 'manual' ? ` · ${e.source}` : ''}</span>
            <button class="text-muted" onclick={() => del(e)} aria-label="Löschen"><Icon name="trash" size={16} /></button>
          </div>
        {:else}<Empty icon="body" title="Noch keine Messungen" />{/each}
      </div>
    {/if}
  {:else}
    <div class="flex gap-1.5">{#each [['front', 'Vorne'], ['side', 'Seite'], ['back', 'Hinten']] as [k, l]}<button class={pose === k ? 'chip-active' : 'chip'} onclick={() => (pose = k)}>{l}</button>{/each}</div>
    <p class="text-xs text-muted">Fotos werden nur auf deinem Server gespeichert (EXIF/GPS entfernt) und nur an die KI gesendet, wenn du „Fotos“ freigibst.</p>
    {#if photoA && photoB && photoA.id !== photoB.id}
      <div class="card p-2">
        <div class="relative aspect-[3/4] overflow-hidden rounded-2xl bg-black select-none">
          <img src={photoB.url} alt="Nachher" class="absolute inset-0 h-full w-full object-contain" />
          <div class="absolute inset-0 overflow-hidden" style="clip-path: inset(0 {100 - compare.pos}% 0 0)"><img src={photoA.url} alt="Vorher" class="absolute inset-0 h-full w-full object-contain" /></div>
          <div class="absolute inset-y-0 w-0.5 bg-white shadow" style="left:{compare.pos}%"></div>
          <span class="absolute left-2 top-2 rounded-lg bg-black/60 px-2 py-1 text-xs text-white">{fmtDate(photoA.day)}</span>
          <span class="absolute right-2 top-2 rounded-lg bg-black/60 px-2 py-1 text-xs text-white">{fmtDate(photoB.day)}</span>
        </div>
        <input type="range" min="0" max="100" class="mt-2 w-full accent-[var(--accent)]" bind:value={compare.pos} />
        <div class="mt-1 grid grid-cols-2 gap-2">
          <select class="input py-1.5 text-sm" bind:value={compare.a}>{#each posePhotos as p}<option value={p.id}>Vorher: {fmtDate(p.day)}</option>{/each}</select>
          <select class="input py-1.5 text-sm" bind:value={compare.b}>{#each posePhotos as p}<option value={p.id}>Nachher: {fmtDate(p.day)}</option>{/each}</select>
        </div>
      </div>
    {/if}
    <label class="btn-soft w-full"><Icon name="camera" /> Foto aufnehmen<input type="file" accept="image/*" capture="user" class="hidden" onchange={upload} /></label>
    <div class="grid grid-cols-3 gap-2">
      {#each posePhotos as p}
        <div class="relative"><img src={p.url} alt="" class="aspect-[3/4] w-full rounded-xl object-cover" loading="lazy" />
          <span class="absolute bottom-1 left-1 rounded bg-black/60 px-1 text-[10px] text-white">{fmtDate(p.day)}</span>
          <button class="absolute right-1 top-1 rounded-full bg-black/60 p-1 text-white" onclick={() => delPhoto(p)} aria-label="Löschen"><Icon name="x" size={12} /></button></div>
      {/each}
    </div>
  {/if}
</div>

<Sheet bind:open={addOpen} title="Messung eintragen">
  <div class="space-y-3">
    <input type="date" class="input" bind:value={form.day} />
    <label class="block"><span class="label">Gewicht ({weightUnit()})</span><input class="input text-2xl font-bold" inputmode="decimal" bind:value={form.weight} /></label>
    <div class="grid grid-cols-2 gap-2">
      {#each [['body_fat_pct', 'Körperfett %'], ['waist_cm', 'Taille cm'], ['chest_cm', 'Brust cm'], ['hips_cm', 'Hüfte cm'], ['arm_cm', 'Arm cm'], ['thigh_cm', 'Oberschenkel cm'], ['neck_cm', 'Hals cm']] as [k, l]}
        <label><span class="label">{l}</span><input class="input" inputmode="decimal" bind:value={form[k]} /></label>
      {/each}
    </div>
    <button class="btn-primary w-full" onclick={save}>Speichern</button>
  </div>
</Sheet>

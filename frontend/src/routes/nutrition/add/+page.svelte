<script>
  import { onMount, onDestroy } from 'svelte';
  import { goto } from '$app/navigation';
  import { page } from '$app/state';
  import { api } from '$lib/api.js';
  import { session } from '$lib/session.svelte.js';
  import { toast, toastError } from '$lib/toast.svelte.js';
  import { energy, energyUnit, fmtNum, today } from '$lib/units.js';
  import { success } from '$lib/haptics.js';
  import { uuid } from '$lib/offline.js';
  import Header from '$components/Header.svelte';
  import Icon from '$components/Icon.svelte';
  import Sheet from '$components/Sheet.svelte';
  import Empty from '$components/Empty.svelte';

  const day = page.url.searchParams.get('day') || today();
  let slot = $state(page.url.searchParams.get('slot') || defaultSlot());
  let tab = $state(page.url.searchParams.get('mode') || 'search');
  let q = $state(''), results = $state([]), searching = $state(false);
  let favorites = $state([]), recent = $state([]), recipes = $state([]);
  let pick = $state(null); // { food | recipe, grams, servings }
  let manual = $state({ name: '', kcal: '', protein: '', carbs: '', fat: '', grams: '' });
  let photoItems = $state(null), photoBusy = $state(false), photoNote = $state('');
  let video = $state();
  let scanner = null, controls = null, scanMsg = $state('');

  function defaultSlot() {
    const h = new Date().getHours();
    const slots = session.settings?.meal_slots || ['Frühstück', 'Mittagessen', 'Abendessen', 'Snacks'];
    return h < 10 ? slots[0] : h < 15 ? slots[1] ?? slots[0] : h < 21 ? slots[2] ?? slots.at(-1) : slots.at(-1);
  }
  onMount(async () => {
    [favorites, recent, recipes] = await Promise.all([api.get('/api/favorites'), api.get('/api/foods/recent'), api.get('/api/recipes')]).catch(() => [[], [], []]);
  });
  onDestroy(stopScan);

  let timer;
  function onSearch() {
    clearTimeout(timer);
    if (q.length < 2) { results = []; return; }
    timer = setTimeout(async () => {
      searching = true;
      try { results = (await api.get(`/api/foods/search?q=${encodeURIComponent(q)}`)).results; } catch (e) { toastError(e); } finally { searching = false; }
    }, 350);
  }
  function choose(food) { pick = { food, grams: food.serving_g || 100 }; }
  function chooseRecipe(recipe) { pick = { recipe, servings: 1 }; }

  const preview = $derived.by(() => {
    if (!pick) return null;
    if (pick.food) { const f = Number(pick.grams || 0) / 100; return { kcal: pick.food.kcal * f, protein: pick.food.protein * f, carbs: pick.food.carbs * f, fat: pick.food.fat * f }; }
    const s = Number(pick.servings || 0), p = pick.recipe.per_serving;
    return { kcal: p.kcal * s, protein: p.protein * s, carbs: p.carbs * s, fat: p.fat * s };
  });

  async function log() {
    try {
      const body = pick.food ? { food_id: pick.food.id, grams: Number(pick.grams) } : { recipe_id: pick.recipe.id, servings: Number(pick.servings) };
      await api.post('/api/meals', { ...body, day, slot, source: tab === 'scan' ? 'barcode' : 'manual', client_id: uuid() });
      success();
      toast('Geloggt ✓', 'success');
      pick = null;
    } catch (e) { toastError(e); }
  }
  async function toggleFav() {
    const f = favorites.find((x) => (pick.food && x.food_id === pick.food.id) || (pick.recipe && x.recipe_id === pick.recipe.id));
    if (f) { await api.del(`/api/favorites/${f.id}`); favorites = favorites.filter((x) => x.id !== f.id); }
    else { const n = await api.post('/api/favorites', pick.food ? { food_id: pick.food.id, default_grams: Number(pick.grams) } : { recipe_id: pick.recipe.id }); favorites = [...favorites, { ...n, food: pick.food, recipe: pick.recipe }]; }
  }
  const isFav = $derived(pick && favorites.some((x) => (pick.food && x.food_id === pick.food.id) || (pick.recipe && x.recipe_id === pick.recipe.id)));

  async function logManual() {
    try {
      await api.post('/api/meals', { day, slot, name: manual.name, kcal: Number(manual.kcal) || 0, protein: Number(manual.protein) || 0,
        carbs: Number(manual.carbs) || 0, fat: Number(manual.fat) || 0, grams: Number(manual.grams) || 0, client_id: uuid() });
      success(); toast('Geloggt ✓', 'success');
      manual = { name: '', kcal: '', protein: '', carbs: '', fat: '', grams: '' };
    } catch (e) { toastError(e); }
  }

  // ---- Barcode-Scanner (ZXing, Rückkamera)
  async function startScan() {
    scanMsg = 'Kamera wird gestartet …';
    try {
      const { BrowserMultiFormatReader } = await import('@zxing/browser');
      scanner = new BrowserMultiFormatReader();
      controls = await scanner.decodeFromConstraints({ video: { facingMode: 'environment' } }, video, async (res) => {
        if (!res) return;
        stopScan();
        scanMsg = `Code ${res.getText()} – suche …`;
        try {
          const food = await api.get(`/api/foods/barcode/${res.getText()}`);
          success();
          choose(food);
          scanMsg = '';
        } catch (e) {
          scanMsg = e.status === 404 ? 'Produkt nicht gefunden. Lege es als eigenes Lebensmittel an (Etikett fotografieren).' : e.message;
        }
      });
      scanMsg = 'Barcode in den Rahmen halten';
    } catch (e) { scanMsg = 'Kamera nicht verfügbar: ' + e.message; }
  }
  function stopScan() { try { controls?.stop(); } catch {} controls = null; }
  $effect(() => { if (tab === 'scan' && video) startScan(); else stopScan(); });

  const SRC = { own: { label: 'EIGEN', cls: 'bg-accent/20 text-accent' }, bls: { label: 'BLS', cls: 'bg-protein/20 text-protein' },
    off: { label: 'PRODUKT', cls: 'bg-surface-2' }, other: { label: 'GETEILT', cls: 'bg-surface-2' } };
  const srcKey = (f) => (f.own ? 'own' : f.source === 'bls' ? 'bls' : f.source === 'off' ? 'off' : 'other');
  let estimating = $state(false), estimateFor = $state('');

  // ---- KI-Schätzung aus Text (für Gerichte, die in keiner Datenbank stehen)
  async function estimate(text) {
    estimating = true; photoItems = null;
    try {
      photoItems = (await api.post('/api/coach/estimate-food', { text })).result.items || [];
      estimateFor = text;
    } catch (e) { toastError(e); } finally { estimating = false; }
  }

  // ---- Foto-Erkennung
  async function photo(e) {
    const input = e.currentTarget;
    const f = input.files?.[0];
    if (!f) return;
    photoBusy = true; photoItems = null; estimateFor = '';
    const fd = new FormData(); fd.append('file', f); fd.append('note', photoNote);
    try { photoItems = (await api.upload('/api/coach/vision/meal', fd)).result.items || []; } catch (err) { toastError(err); } finally { photoBusy = false; input.value = ''; }
  }
  async function logPhoto() {
    try {
      await api.post('/api/meals/batch', photoItems.map((i) => ({ day, slot, name: i.name, grams: Number(i.grams) || 0, kcal: Number(i.kcal) || 0,
        protein: Number(i.protein) || 0, carbs: Number(i.carbs) || 0, fat: Number(i.fat) || 0, fiber: Number(i.fiber) || 0, source: estimateFor ? 'coach' : 'photo' })));
      success(); toast(`${photoItems.length} Einträge geloggt`, 'success');
      goto(`/nutrition?day=${day}`);
    } catch (e) { toastError(e); }
  }
  const tabs = [['search', 'Suche', 'search'], ['fav', 'Favoriten', 'star'], ['recent', 'Zuletzt', 'refresh'], ['recipes', 'Rezepte', 'book'], ['scan', 'Scan', 'barcode'], ['photo', 'Foto', 'camera'], ['manual', 'Manuell', 'edit']];
</script>

<Header title="Hinzufügen" back="/nutrition">
  {#snippet actions()}
    <select class="rounded-xl bg-surface-2 px-2 py-1.5 text-sm" bind:value={slot}>{#each session.settings?.meal_slots || [] as s}<option>{s}</option>{/each}</select>
  {/snippet}
</Header>

<div class="px-4">
  <div class="no-scrollbar -mx-4 mb-3 flex gap-1.5 overflow-x-auto px-4">
    {#each tabs as [k, l, ic]}<button class={tab === k ? 'chip-active' : 'chip'} onclick={() => (tab = k)}><Icon name={ic} size={14} /> {l}</button>{/each}
  </div>

  {#if tab === 'search'}
    <!-- svelte-ignore a11y_autofocus -->
    <input class="input mb-3" placeholder="Lebensmittel suchen (z. B. Skyr, Haferflocken) …" bind:value={q} oninput={onSearch} autofocus />
    {#if searching}<p class="text-sm text-muted">Suche in Open Food Facts …</p>{/if}
    <div class="card p-0">
      {#each results as f (f.id)}
        <button class="list-row w-full text-left" onclick={() => choose(f)}>
          <div class="min-w-0 flex-1"><div class="line-clamp-2 text-sm font-medium">{f.name}</div>
            <div class="truncate text-xs text-muted"><span class="mr-1 rounded px-1 py-px text-[10px] font-semibold {SRC[srcKey(f)].cls}">{SRC[srcKey(f)].label}</span>{f.brand || f.category || ''} · {fmtNum(f.protein, 0)} P · {fmtNum(f.carbs, 0)} K · {fmtNum(f.fat, 0)} F /100 g</div></div>
          <span class="text-sm tabular-nums">{fmtNum(energy(f.kcal), 0)}</span>
        </button>
      {:else}
        {#if q.length >= 2 && !searching}<Empty icon="search" title="Nichts gefunden" text="Lass den Coach die Nährwerte schätzen, scanne den Barcode oder trage manuell ein." />{/if}
      {/each}
    </div>
    {#if q.length >= 2 && !searching}
      <button class="btn-soft mt-3 w-full" disabled={estimating} onclick={() => estimate(q)}>
        <Icon name="sparkles" size={18} class="text-accent" /> {estimating ? 'Coach schätzt …' : `„${q}“ vom Coach schätzen lassen`}</button>
      {#if photoItems && estimateFor}{@render aiItemsBlock()}{/if}
    {/if}
    <p class="mt-4 text-center text-[10px] leading-snug text-muted">Gerichte & Grundnahrungsmittel: Bundeslebensmittelschlüssel (BLS) 4.0, Max Rubner-Institut, CC BY 4.0 ·
      Markenprodukte: Open Food Facts (ODbL)</p>
  {:else if tab === 'fav' || tab === 'recent'}
    {@const list = tab === 'fav' ? favorites.map((f) => f.food || (f.recipe && { ...f.recipe, _recipe: true })).filter(Boolean) : recent}
    <div class="card p-0">
      {#each list as f}
        <button class="list-row w-full text-left" onclick={() => (f._recipe ? chooseRecipe(recipes.find((r) => r.id === f.id)) : choose(f))}>
          <div class="min-w-0 flex-1 truncate text-sm font-medium">{f.name}</div><span class="text-sm text-muted">{f._recipe ? 'Rezept' : fmtNum(energy(f.kcal), 0)}</span>
        </button>
      {:else}<Empty icon={tab === 'fav' ? 'star' : 'refresh'} title={tab === 'fav' ? 'Noch keine Favoriten' : 'Noch nichts geloggt'} />{/each}
    </div>
  {:else if tab === 'recipes'}
    <div class="card p-0">
      {#each recipes as r}
        <button class="list-row w-full text-left" onclick={() => chooseRecipe(r)}>
          <div class="flex-1"><div class="text-sm font-medium">{r.name}</div><div class="text-xs text-muted">pro Portion: {fmtNum(r.per_serving.protein, 0)} g Protein</div></div>
          <span class="text-sm">{fmtNum(energy(r.per_serving.kcal), 0)}</span>
        </button>
      {:else}<Empty icon="book" title="Keine Rezepte"><a href="/nutrition/recipes" class="btn-soft">Rezept anlegen</a></Empty>{/each}
    </div>
  {:else if tab === 'scan'}
    <div class="relative overflow-hidden rounded-3xl bg-black">
      <!-- svelte-ignore a11y_media_has_caption -->
      <video bind:this={video} class="aspect-[3/4] w-full object-cover" playsinline muted></video>
      <div class="pointer-events-none absolute inset-x-10 top-1/2 h-28 -translate-y-1/2 rounded-2xl border-4 border-accent/80"></div>
    </div>
    <p class="mt-3 text-center text-sm text-muted">{scanMsg}</p>
    {#if !controls}<button class="btn-soft mt-2 w-full" onclick={startScan}>Erneut scannen</button>{/if}
  {:else if tab === 'photo'}
    <div class="card space-y-3 text-center">
      <p class="text-sm text-muted">Fotografiere deine Mahlzeit – die KI schätzt Lebensmittel und Mengen. Du kannst alles korrigieren, bevor es geloggt wird.</p>
      <input class="input" placeholder="Hinweis (optional), z. B. „mit Olivenöl“" bind:value={photoNote} />
      <label class="btn-primary w-full"><Icon name="camera" /> {photoBusy ? 'Analysiere …' : 'Foto aufnehmen'}
        <input type="file" accept="image/*" capture="environment" class="hidden" onchange={photo} disabled={photoBusy} /></label>
    </div>
    {#if photoItems && !estimateFor}{@render aiItemsBlock()}{/if}
  {:else if tab === 'manual'}
    <div class="card space-y-3">
      <input class="input" placeholder="Bezeichnung" bind:value={manual.name} />
      <div class="grid grid-cols-2 gap-2">
        {#each [['kcal', 'kcal'], ['grams', 'Menge (g)'], ['protein', 'Protein (g)'], ['carbs', 'Kohlenhydrate (g)'], ['fat', 'Fett (g)']] as [k, l]}
          <label><span class="label">{l}</span><input class="input" inputmode="decimal" bind:value={manual[k]} /></label>
        {/each}
      </div>
      <button class="btn-primary w-full" disabled={!manual.name} onclick={logManual}>Loggen</button>
      <button class="btn-soft w-full" disabled={!manual.name || estimating} onclick={() => estimate(manual.name)}>
        <Icon name="sparkles" size={18} class="text-accent" /> {estimating ? 'Coach schätzt …' : 'Nährwerte vom Coach schätzen lassen'}</button>
    </div>
    {#if photoItems && estimateFor}{@render aiItemsBlock()}{/if}
  {/if}
</div>

{#snippet aiItemsBlock()}
      <div class="card mt-3 space-y-2">
        {#each photoItems as it, i}
          <div class="rounded-xl bg-surface-2 p-2">
            <div class="flex gap-2"><input class="input py-1.5" bind:value={it.name} /><button class="text-danger" onclick={() => (photoItems = photoItems.filter((_, j) => j !== i))}><Icon name="x" /></button></div>
            <div class="mt-1 grid grid-cols-5 gap-1 text-xs">
              {#each [['grams', 'g'], ['kcal', 'kcal'], ['protein', 'P'], ['carbs', 'K'], ['fat', 'F']] as [k, l]}
                <label>{l}<input class="input px-1 py-1 text-center" inputmode="decimal" bind:value={it[k]} /></label>
              {/each}
            </div>
            {#if it.confidence}<p class="mt-1 text-xs text-muted">Sicherheit: {it.confidence}</p>{/if}
          </div>
        {/each}
        <button class="btn-primary w-full" disabled={!photoItems.length} onclick={logPhoto}>Alle loggen ({fmtNum(photoItems.reduce((a, i) => a + Number(i.kcal || 0), 0), 0)} kcal)</button>
      </div>
    {/snippet}

<Sheet open={!!pick} title={pick?.food?.name || pick?.recipe?.name || ''} onclose={() => (pick = null)}>
  {#if pick}
    <div class="space-y-4">
      {#if pick.food}
        <p class="text-sm text-muted">{pick.food.brand || pick.food.category}{pick.food.source === 'bls' ? ' · Quelle: BLS 4.0' : ''}</p>
        <div class="flex items-end gap-2">
          <label class="flex-1"><span class="label">Menge (g)</span><input class="input text-2xl font-bold" inputmode="decimal" type="number" bind:value={pick.grams} /></label>
        </div>
        <div class="flex flex-wrap gap-1">
          {#if pick.food.serving_g}<button class="chip-active" onclick={() => (pick.grams = pick.food.serving_g)}>{pick.food.serving_label || '1 Portion'} ({pick.food.serving_g} g)</button>{/if}
          {#each [50, 100, 150, 200, 250] as g}<button class="chip" onclick={() => (pick.grams = g)}>{g} g</button>{/each}
        </div>
      {:else}
        <label><span class="label">Portionen</span><input class="input text-2xl font-bold" inputmode="decimal" type="number" step="0.25" bind:value={pick.servings} /></label>
      {/if}
      {#if preview}
        <div class="grid grid-cols-4 gap-2 text-center">
          <div class="rounded-xl bg-surface-2 p-2"><div class="font-bold">{fmtNum(energy(preview.kcal), 0)}</div><div class="text-xs text-muted">{energyUnit()}</div></div>
          <div class="rounded-xl bg-surface-2 p-2"><div class="font-bold text-protein">{fmtNum(preview.protein, 1)}</div><div class="text-xs text-muted">Protein</div></div>
          <div class="rounded-xl bg-surface-2 p-2"><div class="font-bold text-carbs">{fmtNum(preview.carbs, 1)}</div><div class="text-xs text-muted">KH</div></div>
          <div class="rounded-xl bg-surface-2 p-2"><div class="font-bold text-fat">{fmtNum(preview.fat, 1)}</div><div class="text-xs text-muted">Fett</div></div>
        </div>
      {/if}
      <div class="flex gap-2">
        <button class="btn-soft" onclick={toggleFav} aria-label="Favorit"><Icon name="star" class={isFav ? 'fill-warn text-warn' : ''} /></button>
        <button class="btn-primary flex-1" onclick={log}>Zu „{slot}“ hinzufügen</button>
      </div>
    </div>
  {/if}
</Sheet>

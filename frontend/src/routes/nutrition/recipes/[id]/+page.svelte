<script>
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { page } from '$app/state';
  import { api } from '$lib/api.js';
  import { toast, toastError } from '$lib/toast.svelte.js';
  import { energy, energyUnit, fmtNum } from '$lib/units.js';
  import Header from '$components/Header.svelte';
  import Icon from '$components/Icon.svelte';
  import Sheet from '$components/Sheet.svelte';
  import ShareSheet from '$components/ShareSheet.svelte';
  import Skeleton from '$components/Skeleton.svelte';

  let r = $state(null);
  let edit = $state(page.url.searchParams.get('edit') === '1');
  let search = $state({ open: false, q: '', results: [] });
  let shareOpen = $state(false);
  onMount(async () => { r = await api.get(`/api/recipes/${page.params.id}`); });

  async function save() {
    try {
      r = await api.put(`/api/recipes/${r.id}`, { name: r.name, servings: Number(r.servings), instructions: r.instructions, tags: r.tags,
        ingredients: r.ingredients.map((i) => ({ food_id: i.food_id, grams: Number(i.grams) })) });
      edit = false; toast('Gespeichert', 'success');
    } catch (e) { toastError(e); }
  }
  let t;
  function find() {
    clearTimeout(t);
    t = setTimeout(async () => { if (search.q.length >= 2) search.results = (await api.get(`/api/foods/search?q=${encodeURIComponent(search.q)}`)).results; }, 350);
  }
  function add(f) { r.ingredients = [...r.ingredients, { food_id: f.id, name: f.name, brand: f.brand, grams: f.serving_g || 100 }]; search.open = false; }
  async function del() {
    if (!confirm('Rezept löschen?')) return;
    await api.del(`/api/recipes/${r.id}`); goto('/nutrition/recipes');
  }
</script>

<Header title={r?.name || 'Rezept'} back="/nutrition/recipes">
  {#snippet actions()}
    {#if r?.own}
      {#if edit}<button class="btn-primary btn-sm" onclick={save}>Speichern</button>
      {:else}<button class="p-2 text-muted" onclick={() => (shareOpen = true)} aria-label="Teilen"><Icon name="share" /></button>
        <button class="p-2 text-accent" onclick={() => (edit = true)} aria-label="Bearbeiten"><Icon name="edit" /></button>{/if}
    {/if}
  {/snippet}
</Header>
<div class="space-y-3 px-4">
  {#if !r}<Skeleton />{:else}
    {#if edit}
      <div class="card space-y-2">
        <input class="input font-semibold" bind:value={r.name} />
        <label><span class="label">Portionen</span><input class="input" type="number" step="0.5" bind:value={r.servings} /></label>
      </div>
    {/if}
    <div class="card grid grid-cols-4 gap-2 text-center">
      <div><div class="text-lg font-bold">{fmtNum(energy(r.per_serving.kcal), 0)}</div><div class="text-xs text-muted">{energyUnit()}/Port.</div></div>
      <div><div class="text-lg font-bold text-protein">{fmtNum(r.per_serving.protein, 0)}</div><div class="text-xs text-muted">Protein</div></div>
      <div><div class="text-lg font-bold text-carbs">{fmtNum(r.per_serving.carbs, 0)}</div><div class="text-xs text-muted">KH</div></div>
      <div><div class="text-lg font-bold text-fat">{fmtNum(r.per_serving.fat, 0)}</div><div class="text-xs text-muted">Fett</div></div>
      <div class="col-span-4 text-xs text-muted">Gesamt {fmtNum(r.total_grams, 0)} g · Portion {fmtNum(r.serving_grams, 0)} g</div>
    </div>
    <p class="section-title">Zutaten</p>
    <div class="card p-0">
      {#each r.ingredients as ing, i}
        <div class="list-row">
          <div class="min-w-0 flex-1 truncate text-sm">{ing.name}</div>
          {#if edit}
            <input class="input w-24 py-1.5 text-right" type="number" bind:value={ing.grams} /><span class="text-sm text-muted">g</span>
            <button class="text-danger" onclick={() => (r.ingredients = r.ingredients.filter((_, j) => j !== i))}><Icon name="x" size={18} /></button>
          {:else}<span class="text-sm text-muted">{fmtNum(ing.grams, 0)} g</span>{/if}
        </div>
      {/each}
      {#if edit}<button class="flex w-full items-center gap-2 px-4 py-3 text-sm font-medium text-accent" onclick={() => (search.open = true)}><Icon name="plus" size={18} /> Zutat</button>{/if}
    </div>
    <p class="section-title">Zubereitung</p>
    {#if edit}<textarea class="input" rows="6" bind:value={r.instructions}></textarea>
    {:else}<div class="card whitespace-pre-line text-sm">{r.instructions || '–'}</div>{/if}
    {#if edit}<button class="btn-ghost w-full text-danger" onclick={del}>Rezept löschen</button>{/if}
    <a class="btn-primary w-full" href="/nutrition/add?mode=recipes">Rezept loggen</a>
  {/if}
</div>

<Sheet bind:open={search.open} title="Zutat hinzufügen" full>
  <input class="input mb-3" placeholder="Suchen …" bind:value={search.q} oninput={find} />
  {#each search.results as f}
    <button class="list-row w-full text-left" onclick={() => add(f)}>
      <div class="flex-1"><div class="text-sm font-medium">{f.name}</div><div class="text-xs text-muted">{f.brand}</div></div>
      <span class="text-sm text-muted">{fmtNum(f.kcal, 0)} kcal</span>
    </button>
  {/each}
</Sheet>
{#if r?.own}<ShareSheet bind:open={shareOpen} type="recipe" id={r.id} />{/if}

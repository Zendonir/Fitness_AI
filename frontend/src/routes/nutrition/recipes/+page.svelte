<script>
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { api } from '$lib/api.js';
  import { toastError } from '$lib/toast.svelte.js';
  import { energy, fmtNum } from '$lib/units.js';
  import Header from '$components/Header.svelte';
  import Icon from '$components/Icon.svelte';
  import Empty from '$components/Empty.svelte';
  import Skeleton from '$components/Skeleton.svelte';

  let list = $state(null);
  onMount(async () => { list = await api.get('/api/recipes'); });
  async function create() {
    try { const r = await api.post('/api/recipes', { name: 'Neues Rezept', servings: 2, ingredients: [] }); goto(`/nutrition/recipes/${r.id}?edit=1`); } catch (e) { toastError(e); }
  }
</script>

<Header title="Rezepte" back="/nutrition">
  {#snippet actions()}<button class="btn-primary btn-sm" onclick={create}><Icon name="plus" size={16} /> Neu</button>{/snippet}
</Header>
<div class="px-4">
  {#if !list}<Skeleton />{:else if !list.length}
    <Empty icon="book" title="Noch keine Rezepte" text="Nährwerte werden automatisch aus den Zutaten berechnet." />
  {:else}
    <div class="card p-0">
      {#each list as r}
        <a href="/nutrition/recipes/{r.id}" class="list-row">
          <div class="flex-1"><div class="font-medium">{r.name} {#if !r.own}<span class="text-xs text-accent">geteilt</span>{/if}</div>
            <div class="text-xs text-muted">{r.servings} Portionen · pro Portion {fmtNum(energy(r.per_serving.kcal), 0)} kcal · {fmtNum(r.per_serving.protein, 0)} g Protein</div></div>
          <Icon name="right" size={18} class="text-muted" />
        </a>
      {/each}
    </div>
  {/if}
</div>

<script>
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { api } from '$lib/api.js';
  import { toastError } from '$lib/toast.svelte.js';
  import Header from '$components/Header.svelte';
  import Icon from '$components/Icon.svelte';
  import Skeleton from '$components/Skeleton.svelte';

  let plans = $state(null);
  onMount(async () => { plans = await api.get('/api/plans'); });
  const groups = $derived(plans ? [['own', 'Meine Pläne'], ['shared', 'Mit mir geteilt'], ['template', 'Vorlagen']].map(([k, l]) => [l, plans.filter((p) => p.kind === k)]) : []);
  async function create() {
    try {
      const p = await api.post('/api/plans', { name: 'Neuer Plan', weeks: 4, deload_weeks: [4], days: [{ name: 'Tag 1', exercises: [] }] });
      goto(`/training/plans/${p.id}?edit=1`);
    } catch (e) { toastError(e); }
  }
</script>

<Header title="Trainingspläne" back="/training">
  {#snippet actions()}<button class="btn-primary btn-sm" onclick={create}><Icon name="plus" size={16} /> Neu</button>{/snippet}
</Header>
<div class="px-4">
  {#if !plans}<Skeleton />{:else}
    {#each groups as [label, list]}
      {#if list.length}
        <p class="section-title">{label}</p>
        <div class="card p-0">
          {#each list as p}
            <a href="/training/plans/{p.id}" class="list-row">
              <div class="flex-1 min-w-0"><div class="font-medium">{p.name} {#if p.is_active}<span class="chip-active ml-1 py-0.5 text-xs">aktiv</span>{/if}</div>
                <div class="truncate text-sm text-muted">{p.days_count} Tage · {p.weeks} Wochen{p.deload_weeks?.length ? ` · Deload W${p.deload_weeks.join(', ')}` : ''}</div></div>
              <Icon name="right" size={18} class="text-muted" />
            </a>
          {/each}
        </div>
      {/if}
    {/each}
  {/if}
</div>

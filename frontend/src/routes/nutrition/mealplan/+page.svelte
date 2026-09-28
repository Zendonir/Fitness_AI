<script>
  import { onMount } from 'svelte';
  import { api } from '$lib/api.js';
  import { toast, toastError } from '$lib/toast.svelte.js';
  import { fmtDate, fmtNum } from '$lib/units.js';
  import Header from '$components/Header.svelte';
  import Icon from '$components/Icon.svelte';
  import Empty from '$components/Empty.svelte';

  let plans = $state([]);
  let current = $state(null);
  let busy = $state(false);
  let notes = $state('');
  let days = $state(7);
  let checked = $state({});

  onMount(async () => {
    plans = await api.get('/api/coach/meal-plans');
    current = plans[0] || null;
    try { checked = JSON.parse(localStorage.getItem('ff_shopping') || '{}'); } catch {}
  });
  async function generate(today_only = false) {
    busy = true;
    try {
      current = await api.post('/api/coach/meal-plan', { days, notes, today_only });
      plans = [current, ...plans];
      toast('Plan erstellt', 'success');
    } catch (e) { toastError(e); } finally { busy = false; }
  }
  function toggle(key) {
    checked[key] = !checked[key];
    try { localStorage.setItem('ff_shopping', JSON.stringify(checked)); } catch {}
  }
  const shopping = $derived.by(() => {
    const g = {};
    for (const it of current?.shopping_list || []) (g[it.category || 'Sonstiges'] ??= []).push(it);
    return Object.entries(g);
  });
</script>

<Header title="Mahlzeitenplan" back="/nutrition" />
<div class="space-y-3 px-4">
  <div class="card space-y-3">
    <p class="text-sm text-muted">Der Coach plant passend zu deinen Makrozielen, Vorlieben und vorhandenen Rezepten.</p>
    <input class="input" placeholder="Wünsche, z. B. schnell, günstig, vegetarisch" bind:value={notes} />
    <div class="flex gap-2">
      <select class="input w-28" bind:value={days}>{#each [3, 5, 7] as d}<option value={d}>{d} Tage</option>{/each}</select>
      <button class="btn-primary flex-1" disabled={busy} onclick={() => generate(false)}><Icon name="sparkles" size={18} /> {busy ? 'Plane …' : 'Wochenplan'}</button>
    </div>
    <button class="btn-soft w-full" disabled={busy} onclick={() => generate(true)}>Nur Rest von heute (Restmakros)</button>
  </div>

  {#if !current}
    <Empty icon="calendar" title="Noch kein Plan" />
  {:else}
    {#each current.plan.days || [] as d}
      <div class="card">
        <div class="mb-2 flex justify-between font-semibold"><span>{d.day}</span><span class="text-sm text-muted">{fmtNum(d.totals?.kcal, 0)} kcal · {fmtNum(d.totals?.protein, 0)} g P</span></div>
        {#each d.meals || [] as m}
          <div class="border-t border-line py-2 text-sm">
            <div class="flex justify-between"><span><span class="text-muted">{m.slot}:</span> {m.name}</span><span class="tabular-nums text-muted">{fmtNum(m.kcal, 0)}</span></div>
            {#if m.ingredients?.length}<div class="text-xs text-muted">{m.ingredients.map((i) => `${i.name} ${i.grams ?? ''}g`).join(', ')}</div>{/if}
          </div>
        {/each}
      </div>
    {/each}
    {#if shopping.length}
      <p class="section-title">Einkaufsliste</p>
      {#each shopping as [cat, items]}
        <div class="card p-0">
          <div class="px-4 pt-3 text-sm font-semibold">{cat}</div>
          {#each items as it}
            {@const key = `${current.id}:${it.name}`}
            <label class="list-row text-sm"><input type="checkbox" class="h-5 w-5 accent-[var(--accent)]" checked={checked[key]} onchange={() => toggle(key)} />
              <span class="flex-1 {checked[key] ? 'text-muted line-through' : ''}">{it.name}</span><span class="text-muted">{it.amount}</span></label>
          {/each}
        </div>
      {/each}
    {/if}
    {#each current.plan.tips || [] as t}<p class="text-sm text-muted">💡 {t}</p>{/each}
    <p class="text-center text-xs text-muted">Erstellt am {fmtDate(current.created_at, { day: '2-digit', month: '2-digit', year: 'numeric' })}</p>
  {/if}
</div>

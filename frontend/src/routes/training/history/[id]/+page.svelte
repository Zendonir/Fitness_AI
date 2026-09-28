<script>
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { page } from '$app/state';
  import { api } from '$lib/api.js';
  import { toastError } from '$lib/toast.svelte.js';
  import { fmtDate, fmtDuration, fmtWeight, fmtNum, toDisplayWeight, weightUnit } from '$lib/units.js';
  import Header from '$components/Header.svelte';
  import Icon from '$components/Icon.svelte';
  import Skeleton from '$components/Skeleton.svelte';

  let w = $state(null);
  onMount(async () => {
    try { w = await api.get(`/api/workouts/${page.params.id}`); } catch (e) { toastError(e); }
  });
  const groups = $derived.by(() => {
    const g = {};
    for (const s of w?.sets || []) (g[s.exercise_id] ??= { name: s.exercise_name, id: s.exercise_id, sets: [] }).sets.push(s);
    return Object.values(g);
  });
  const volume = $derived((w?.sets || []).filter((s) => s.completed && !s.is_warmup).reduce((a, s) => a + s.reps * s.weight_kg, 0));
  async function del() {
    if (!confirm('Training löschen?')) return;
    await api.del(`/api/workouts/${w.id}`);
    goto('/training', { replaceState: true });
  }
</script>

<Header title={w?.name || 'Training'} back="/training" subtitle={w ? fmtDate(w.started_at, { weekday: 'long', day: 'numeric', month: 'long' }) : ''}>
  {#snippet actions()}{#if w}<button class="p-2 text-danger" onclick={del} aria-label="Löschen"><Icon name="trash" /></button>{/if}{/snippet}
</Header>
<div class="space-y-3 px-4">
  {#if !w}<Skeleton />{:else}
    <div class="grid grid-cols-3 gap-2 text-center">
      <div class="card p-3"><div class="text-xs text-muted">Dauer</div><div class="font-bold">{w.finished_at ? fmtDuration((new Date(w.finished_at) - new Date(w.started_at)) / 1000) : 'läuft'}</div></div>
      <div class="card p-3"><div class="text-xs text-muted">Volumen</div><div class="font-bold">{fmtNum(toDisplayWeight(volume), 0)} {weightUnit()}</div></div>
      <div class="card p-3"><div class="text-xs text-muted">Gefühl</div><div class="font-bold">{['–', '😫', '😕', '🙂', '😃', '🔥'][w.rating || 0]}</div></div>
    </div>
    {#if !w.finished_at}<a class="btn-primary w-full" href="/training/live/{w.id}">Fortsetzen</a>{/if}
    {#each groups as g}
      <div class="card">
        <a href="/training/exercises/{g.id}" class="mb-2 flex items-center justify-between font-semibold">{g.name}<Icon name="right" size={18} class="text-muted" /></a>
        {#each g.sets as s, i}
          <div class="flex justify-between py-1 text-sm tabular-nums {s.completed ? '' : 'opacity-40'}">
            <span class="text-muted">{s.is_warmup ? 'W' : i + 1}</span><span>{s.reps} × {fmtWeight(s.weight_kg)}{s.rpe ? ` @${s.rpe}` : ''}</span>
          </div>
        {/each}
      </div>
    {/each}
    {#if w.notes}<div class="card text-sm"><div class="mb-1 text-muted">Notizen</div>{w.notes}</div>{/if}
  {/if}
</div>

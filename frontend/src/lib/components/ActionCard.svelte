<script>
  import { untrack } from 'svelte';
  // Bestätigungsdialog für schreibende Coach-Aktionen (mit Diff-Anzeige)
  import { api } from '$lib/api.js';
  import { toast, toastError } from '$lib/toast.svelte.js';
  import { GOALS } from '$lib/units.js';
  import Icon from './Icon.svelte';
  let { action, onresolved = () => {} } = $props();
  let busy = $state(false);
  let status = $state(untrack(() => action.status));

  async function resolve(ok) {
    busy = true;
    try {
      await api.post(`/api/coach/actions/${action.id}/${ok ? 'confirm' : 'reject'}`);
      status = ok ? 'confirmed' : 'rejected';
      toast(ok ? 'Übernommen ✓' : 'Verworfen', ok ? 'success' : 'info');
      onresolved(status);
    } catch (e) { toastError(e); } finally { busy = false; }
  }
  const diff = $derived(action.diff || {});
  function planChanges() {
    const out = [];
    (diff.after || []).forEach((day, i) => {
      const before = (diff.before || [])[i] || { exercises: [] };
      const b = before.exercises.map((e) => `${e.exercise} ${e.sets}×${e.rep_min}–${e.rep_max}`);
      const a = day.exercises.map((e) => `${e.exercise} ${e.sets}×${e.rep_min}–${e.rep_max}`);
      if (JSON.stringify(a) !== JSON.stringify(b)) out.push({ day: day.day, removed: b.filter((x) => !a.includes(x)), added: a.filter((x) => !b.includes(x)) });
    });
    return out;
  }
</script>

<div class="pop rounded-2xl border border-accent/40 bg-accent/5 p-3 text-sm">
  <div class="mb-2 flex items-center gap-2 font-semibold"><Icon name="shield" size={18} class="text-accent" /> {action.summary}</div>

  {#if action.tool === 'propose_log_meal'}
    <ul class="space-y-1">
      {#each diff.items || [] as it}
        <li class="flex justify-between"><span>{it.name}{it.grams ? ` · ${it.grams} g` : ''}</span>
          <span class="text-muted tabular-nums">{Math.round(it.kcal || 0)} kcal · {Math.round(it.protein || 0)} g P</span></li>
      {/each}
    </ul>
  {:else if action.tool === 'propose_nutrition_goal'}
    <div class="grid grid-cols-3 gap-1 text-center tabular-nums">
      <span></span><span class="text-muted">Vorher</span><span class="text-muted">Nachher</span>
      <span class="text-left">Ziel</span><span>{GOALS[diff.before?.goal]}</span><span class="font-semibold">{GOALS[diff.after?.goal]}</span>
      {#each ['training', 'rest'] as t}
        <span class="text-left">{t === 'training' ? 'Trainingstag' : 'Ruhetag'}</span>
        <span>{Math.round(diff.before?.[t]?.kcal)} kcal / {Math.round(diff.before?.[t]?.protein)} g</span>
        <span class="font-semibold">{Math.round(diff.after?.[t]?.kcal)} kcal / {Math.round(diff.after?.[t]?.protein)} g</span>
      {/each}
    </div>
    {#if diff.clamped}<p class="mt-2 text-warn">Auf die Untergrenzen ({diff.floors?.kcal} kcal, {diff.floors?.protein} g Protein) angehoben.</p>{/if}
  {:else if action.tool === 'propose_plan_changes'}
    {#each planChanges() as ch}
      <div class="mb-1.5"><div class="font-medium">{ch.day}</div>
        {#each ch.removed as r}<div class="text-danger">− {r}</div>{/each}
        {#each ch.added as a}<div class="text-accent">+ {a}</div>{/each}
      </div>
    {/each}
    {#each diff.warnings || [] as w}<p class="text-warn">{w}</p>{/each}
  {:else if action.tool === 'propose_workout'}
    <ul>{#each diff.exercises || [] as e}<li>{e.exercise}: {e.sets}×{e.reps}{e.weight_kg ? ` @ ${e.weight_kg} kg` : ''}</li>{/each}</ul>
  {:else if action.tool === 'propose_profile_update'}
    <p class="text-muted line-through">{diff.before || '–'}</p><p>{diff.after}</p>
  {/if}

  {#if status === 'pending'}
    <div class="mt-3 flex gap-2">
      <button class="btn-primary btn-sm flex-1" disabled={busy} onclick={() => resolve(true)}><Icon name="check" size={16} /> Übernehmen</button>
      <button class="btn-soft btn-sm flex-1" disabled={busy} onclick={() => resolve(false)}>Verwerfen</button>
    </div>
  {:else}
    <p class="mt-2 text-xs text-muted">{status === 'confirmed' ? '✓ Übernommen' : status === 'rejected' ? 'Verworfen' : status}</p>
  {/if}
</div>

<script>
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { api } from '$lib/api.js';
  import { toastError } from '$lib/toast.svelte.js';
  import { fmtDate, fmtNum, fmtWeight, weightUnit, toDisplayWeight } from '$lib/units.js';
  import { uuid } from '$lib/offline.js';
  import Header from '$components/Header.svelte';
  import Icon from '$components/Icon.svelte';
  import Skeleton from '$components/Skeleton.svelte';
  import Empty from '$components/Empty.svelte';

  let today = $state(null);
  let workouts = $state(null);
  let busy = $state(false);

  onMount(async () => {
    try {
      [today, workouts] = await Promise.all([api.get('/api/training/today'), api.get('/api/workouts?limit=15')]);
    } catch (e) { toastError(e); }
  });

  async function start(plan_day_id = null) {
    busy = true;
    try {
      const w = await api.post('/api/workouts/start', { plan_day_id, client_id: uuid() });
      goto(`/training/live/${w.id}`);
    } catch (e) { toastError(e); } finally { busy = false; }
  }
  const open = $derived(workouts?.find((w) => !w.finished_at));
</script>

<Header title="Training">
  {#snippet actions()}<a href="/training/exercises" class="rounded-full p-2 text-muted" aria-label="Übungen"><Icon name="book" /></a>{/snippet}
</Header>

<div class="space-y-4 px-4">
  {#if open}
    <a href="/training/live/{open.id}" class="card flex items-center gap-3 border-accent bg-accent/10">
      <Icon name="play" class="text-accent" /><div class="flex-1"><div class="font-semibold">Laufendes Training fortsetzen</div>
      <div class="text-sm text-muted">{open.name} · seit {new Date(open.started_at).toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' })}</div></div>
      <Icon name="right" />
    </a>
  {/if}

  {#if !today}
    <Skeleton lines={2} h="h-40" />
  {:else if today.active_plan}
    <div class="card">
      <div class="flex items-start justify-between">
        <div>
          <p class="text-xs font-semibold uppercase tracking-wide text-accent">{today.rest_day ? 'Heute Ruhetag · als Nächstes' : 'Heute'}{today.deload ? ' · Deload-Woche' : ''}</p>
          <h2 class="text-xl font-bold">{today.day.name}</h2>
          <p class="text-sm text-muted">{today.plan_name} · Woche {today.week}/{today.weeks}</p>
        </div>
        <a href="/training/plans/{today.plan_id}" class="text-sm text-accent">Plan</a>
      </div>
      <ul class="my-3 divide-y divide-line">
        {#each today.exercises as e}
          <li class="flex items-center justify-between py-2 text-sm">
            <span class="font-medium">{e.superset_group ? `${e.superset_group.toUpperCase()} · ` : ''}{e.exercise.name}</span>
            <span class="text-muted tabular-nums">{e.suggestion.sets}× {e.suggestion.reps}{e.suggestion.weight_kg ? ` · ${fmtWeight(e.suggestion.weight_kg)}` : ''}
              {#if e.suggestion.action === 'increase'}<span class="text-accent">↑</span>{/if}</span>
          </li>
        {/each}
      </ul>
      <button class="btn-primary w-full" disabled={busy} onclick={() => start(today.day.id)}><Icon name="play" size={18} /> Training starten</button>
    </div>
  {:else}
    <div class="card">
      <Empty icon="dumbbell" title="Kein aktiver Plan" text="Wähle eine Vorlage oder erstelle deinen eigenen Plan.">
        <a href="/training/plans" class="btn-soft">Pläne ansehen</a>
      </Empty>
    </div>
  {/if}

  <div class="grid grid-cols-3 gap-2">
    <button class="card flex flex-col items-center gap-1 py-4 text-sm font-medium" onclick={() => start(null)}><Icon name="bolt" class="text-accent" />Frei</button>
    <a href="/training/plans" class="card flex flex-col items-center gap-1 py-4 text-sm font-medium"><Icon name="list" class="text-accent" />Pläne</a>
    <a href="/training/cardio" class="card flex flex-col items-center gap-1 py-4 text-sm font-medium"><Icon name="run" class="text-accent" />Ausdauer</a>
  </div>

  <p class="section-title">Verlauf</p>
  {#if workouts === null}
    <Skeleton lines={3} />
  {:else if !workouts.length}
    <Empty icon="calendar" title="Noch keine Trainings" text="Dein erstes Workout erscheint hier." />
  {:else}
    <div class="card p-0">
      {#each workouts as w}
        <a href="/training/history/{w.id}" class="list-row">
          <div class="flex-1"><div class="font-medium">{w.name}</div>
            <div class="text-sm text-muted">{fmtDate(w.started_at, { weekday: 'short', day: '2-digit', month: 'short' })} · {w.exercises_count} Übungen · {w.sets_count} Sätze</div></div>
          <div class="text-right text-sm tabular-nums"><div class="font-semibold">{fmtNum(toDisplayWeight(w.volume_kg), 0)} {weightUnit()}</div><div class="text-muted">Volumen</div></div>
        </a>
      {/each}
    </div>
  {/if}
</div>

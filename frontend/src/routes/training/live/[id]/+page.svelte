<script>
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { page } from '$app/state';
  import { api } from '$lib/api.js';
  import { session } from '$lib/session.svelte.js';
  import { toast, toastError } from '$lib/toast.svelte.js';
  import { fmtDuration, fmtWeight, fromDisplayWeight, toDisplayWeight, weightUnit, MUSCLES } from '$lib/units.js';
  import { success, tap } from '$lib/haptics.js';
  import { uuid } from '$lib/offline.js';
  import Icon from '$components/Icon.svelte';
  import RestTimer from '$components/RestTimer.svelte';
  import Sheet from '$components/Sheet.svelte';
  import Stepper from '$components/Stepper.svelte';
  import ExerciseMedia from '$components/ExerciseMedia.svelte';
  import { mediaEnabled } from '$lib/media.js';

  const id = page.params.id;
  let w = $state(null);
  let idx = $state(0);
  let elapsed = $state(0);
  let timer = $state();
  let timerRunning = $state(false);
  let pickerOpen = $state(false);
  let finishOpen = $state(false);
  let allExercises = $state([]);
  let search = $state('');
  let reps = $state(8), weight = $state(0), rpe = $state(null), warmup = $state(false);
  let custom = $state({});
  let prs = $state([]);
  let showMedia = $state(true);
  try { showMedia = localStorage.getItem('ff_live_media') !== '0'; } catch {}
  function toggleMedia() { showMedia = !showMedia; try { localStorage.setItem('ff_live_media', showMedia ? '1' : '0'); } catch {} }

  onMount(() => {
    load();
    const iv = setInterval(() => w && (elapsed = Math.floor((Date.now() - new Date(w.started_at)) / 1000)), 1000);
    // Bildschirm im Live-Modus wach halten (wo unterstützt)
    let lock;
    navigator.wakeLock?.request('screen').then((l) => (lock = l)).catch(() => {});
    return () => { clearInterval(iv); lock?.release?.(); };
  });

  async function load() {
    try {
      w = await api.get(`/api/workouts/${id}/live`);
      if (w.finished_at) goto(`/training/history/${id}`, { replaceState: true });
      prefill();
    } catch (e) { toastError(e); }
  }
  const ex = $derived(w?.exercises?.[idx]);
  const setsFor = (eid) => (w?.sets || []).filter((s) => s.exercise_id === eid);
  const doneSets = $derived(ex ? setsFor(ex.exercise_id).filter((s) => s.completed && !s.is_warmup) : []);
  const plannedOpen = $derived(ex ? setsFor(ex.exercise_id).filter((s) => !s.completed) : []);

  function prefill() {
    if (!ex) return;
    const last = setsFor(ex.exercise_id).filter((s) => s.completed).at(-1);
    const planned = setsFor(ex.exercise_id).find((s) => !s.completed);
    const sug = ex.suggestion || {};
    const src = planned || last;
    reps = src?.reps || sug.reps || ex.rep_min || 8;
    weight = toDisplayWeight(src?.weight_kg ?? sug.weight_kg ?? 0) || 0;
    rpe = null;
    warmup = false;
    custom = {};
  }
  $effect(() => { idx; prefill(); });

  async function logSet() {
    tap(15);
    const body = { exercise_id: ex.exercise_id, reps: Number(reps), weight_kg: fromDisplayWeight(weight) || 0, rpe, is_warmup: warmup,
      superset_group: ex.superset_group, custom, client_id: uuid() };
    try {
      const planned = plannedOpen[0];
      let s;
      if (planned) s = await api.patch(`/api/sets/${planned.id}`, { ...body, completed: true });
      else s = await api.post(`/api/workouts/${id}/sets`, body);
      if (planned) w.sets = w.sets.map((x) => (x.id === planned.id ? s : x));
      else w.sets = [...w.sets, { ...s, completed: true }];
      success();
      if (!warmup) {
        // Supersatz: direkt zur nächsten Übung der Gruppe, Pause erst nach der Runde
        const group = ex.superset_group;
        const members = group ? w.exercises.map((e, i) => [e, i]).filter(([e]) => e.superset_group === group) : [];
        const pos = members.findIndex(([, i]) => i === idx);
        if (group && pos < members.length - 1) { idx = members[pos + 1][1]; return; }
        if (group && pos === members.length - 1) idx = members[0][1];
        timer?.start(ex.rest_seconds || session.settings?.rest_timer_default || 120);
      }
    } catch (e) { toastError(e); }
  }
  async function deleteSet(s) {
    if (!confirm('Satz löschen?')) return;
    await api.del(`/api/sets/${s.id}`);
    w.sets = w.sets.filter((x) => x.id !== s.id);
  }
  async function openPicker() {
    pickerOpen = true;
    if (!allExercises.length) allExercises = await api.get('/api/exercises');
  }
  function addExercise(e) {
    w.exercises = [...w.exercises, { exercise_id: e.id, exercise: e, sets: 3, rep_min: e.progression?.rep_min || 8, rep_max: e.progression?.rep_max || 12,
      rest_seconds: session.settings?.rest_timer_default || 120, superset_group: null, suggestion: {} }];
    idx = w.exercises.length - 1;
    pickerOpen = false;
    api.get(`/api/exercises/${e.id}/suggestion`).then((s) => { w.exercises[idx].suggestion = s; prefill(); }).catch(() => {});
  }
  async function finish() {
    try {
      const r = await api.post(`/api/workouts/${id}/finish`, { rating: w.rating, notes: w.notes });
      timer?.stop();
      prs = r.prs || [];
      if (prs.length) { success(); toast('Neuer Rekord! 🏆', 'success'); }
      goto(`/training/history/${id}`, { replaceState: true });
    } catch (e) { toastError(e); }
  }
  const filtered = $derived(allExercises.filter((e) => e.name.toLowerCase().includes(search.toLowerCase())));
</script>

{#if w}
  <div class="safe-top flex min-h-dvh flex-col px-4 pb-40">
    <div class="flex items-center gap-2 py-2">
      <button class="-ml-2 p-2 text-accent" onclick={() => goto('/training')} aria-label="Zurück"><Icon name="back" size={26} /></button>
      <div class="flex-1"><div class="font-bold">{w.name}{w.is_deload ? ' · Deload' : ''}</div><div class="text-sm tabular-nums text-muted">{fmtDuration(elapsed)}</div></div>
      <button class="btn-primary btn-sm" onclick={() => (finishOpen = true)}>Beenden</button>
    </div>

    <div class="no-scrollbar -mx-4 mb-3 flex gap-1.5 overflow-x-auto px-4">
      {#each w.exercises as e, i}
        {@const n = setsFor(e.exercise_id).filter((s) => s.completed && !s.is_warmup).length}
        <button class="{i === idx ? 'chip-active' : 'chip'} {n >= e.sets ? 'ring-2 ring-accent/50' : ''}" onclick={() => (idx = i)}>
          {e.superset_group ? e.superset_group.toUpperCase() + ' ' : ''}{e.exercise.name} <span class="opacity-70">{n}/{e.sets}</span>
        </button>
      {/each}
      <button class="chip" onclick={openPicker}><Icon name="plus" size={14} /> Übung</button>
    </div>

    {#if ex}
      <div class="card mb-3">
        <div class="flex items-start justify-between gap-2">
          <div>
            <h2 class="text-xl font-bold">{ex.exercise.name}</h2>
            <p class="text-sm text-muted">{(ex.exercise.primary_muscles || []).map((m) => MUSCLES[m]).join(', ')} · Ziel {ex.sets}× {ex.rep_min}–{ex.rep_max}{ex.target_rpe ? ` @RPE ${ex.target_rpe}` : ''}</p>
          </div>
          <a href="/coach?formcheck={ex.exercise_id}" class="chip text-xs">Formcheck</a>
        </div>
        {#if ex.exercise.media_id && mediaEnabled()}
          {#if showMedia}
            <div class="relative mt-3 overflow-hidden rounded-2xl">
              <ExerciseMedia id={ex.exercise.media_id} name={ex.exercise.name} size="full" class="mx-auto aspect-square max-h-56 w-full" />
              <button class="absolute right-2 top-2 rounded-full bg-black/50 px-2 py-1 text-xs text-white" onclick={toggleMedia}>Ausblenden</button>
            </div>
          {:else}
            <button class="mt-2 text-xs text-accent" onclick={toggleMedia}>▶ Animation anzeigen</button>
          {/if}
        {/if}
        {#if ex.suggestion?.reason}
          <p class="mt-2 rounded-xl bg-accent/10 p-2 text-sm"><Icon name="sparkles" size={14} class="inline text-accent" /> {ex.suggestion.reason}</p>
        {/if}
        {#if ex.suggestion?.last?.length}
          <p class="mt-2 text-xs text-muted">Letztes Mal: {ex.suggestion.last.map((s) => `${s.reps}×${toDisplayWeight(s.weight_kg)}`).join(' · ')} {weightUnit()}</p>
        {/if}
      </div>

      <div class="card mb-3 p-0">
        {#each setsFor(ex.exercise_id) as s, i}
          <div class="list-row {s.completed ? '' : 'opacity-50'}">
            <span class="w-8 text-center text-sm font-bold {s.is_warmup ? 'text-warn' : 'text-muted'}">{s.is_warmup ? 'W' : i + 1}</span>
            <span class="flex-1 font-semibold tabular-nums">{s.reps} × {fmtWeight(s.weight_kg)}{s.rpe ? ` · RPE ${s.rpe}` : ''}</span>
            {#if s.completed}<Icon name="check" size={18} class="text-accent" />{:else}<span class="text-xs text-muted">geplant</span>{/if}
            {#if s.id}<button class="p-1 text-muted" onclick={() => deleteSet(s)} aria-label="Löschen"><Icon name="trash" size={16} /></button>{/if}
          </div>
        {:else}
          <p class="p-4 text-center text-sm text-muted">Noch keine Sätze</p>
        {/each}
      </div>

      <div class="card space-y-4">
        <div class="flex justify-around">
          <Stepper bind:value={reps} step={1} label="Wiederholungen" decimals={0} />
          <Stepper bind:value={weight} step={weightUnit() === 'kg' ? (ex.exercise.progression?.increment_kg || 2.5) : 5} label="Gewicht" unit={weightUnit()} decimals={2} />
        </div>
        <div>
          <span class="label">RPE (optional)</span>
          <div class="no-scrollbar flex gap-1 overflow-x-auto">
            {#each [6, 7, 7.5, 8, 8.5, 9, 9.5, 10] as r}
              <button class="{rpe === r ? 'chip-active' : 'chip'} min-w-11 justify-center" onclick={() => (rpe = rpe === r ? null : r)}>{r}</button>
            {/each}
          </div>
        </div>
        {#each ex.exercise.custom_fields || [] as f}
          <label class="block"><span class="label">{f.label}</span><input class="input" bind:value={custom[f.key]} /></label>
        {/each}
        <label class="flex items-center gap-2 text-sm"><input type="checkbox" class="h-5 w-5 accent-[var(--accent)]" bind:checked={warmup} /> Aufwärmsatz</label>
      </div>
    {:else}
      <button class="btn-soft w-full" onclick={openPicker}><Icon name="plus" /> Übung hinzufügen</button>
    {/if}
  </div>

  {#if ex}
    <div class="fixed inset-x-0 bottom-0 z-30 border-t border-line bg-surface/95 p-3 backdrop-blur-xl" style="padding-bottom: calc(env(safe-area-inset-bottom) + 12px)">
      <div class="mx-auto flex max-w-2xl gap-2">
        <button class="btn-soft" disabled={idx === 0} onclick={() => idx--} aria-label="Vorherige"><Icon name="back" /></button>
        <button class="btn-primary flex-1 text-lg" onclick={logSet}><Icon name="check" /> Satz {doneSets.length + 1} erledigt</button>
        <button class="btn-soft" disabled={idx >= w.exercises.length - 1} onclick={() => idx++} aria-label="Nächste"><Icon name="right" /></button>
      </div>
    </div>
  {/if}
  <RestTimer bind:this={timer} bind:running={timerRunning} exercise={ex?.exercise?.name} />
{/if}

<Sheet bind:open={pickerOpen} title="Übung hinzufügen" full>
  <input class="input mb-3" placeholder="Suchen …" bind:value={search} />
  {#each filtered as e}
    <button class="list-row w-full text-left" onclick={() => addExercise(e)}>
      <ExerciseMedia id={e.media_id} name={e.name} class="h-10 w-10 rounded-lg" zoom={false} />
      <div class="flex-1"><div class="font-medium">{e.name}</div><div class="text-xs text-muted">{e.primary_muscles.map((m) => MUSCLES[m]).join(', ')}</div></div>
      <Icon name="plus" size={18} class="text-accent" />
    </button>
  {/each}
</Sheet>

<Sheet bind:open={finishOpen} title="Training beenden">
  {#if w}
    <p class="mb-2 text-sm text-muted">Wie hat es sich angefühlt?</p>
    <div class="mb-4 flex justify-between">
      {#each ['😫', '😕', '🙂', '😃', '🔥'] as emo, i}
        <button class="rounded-2xl p-3 text-3xl {w.rating === i + 1 ? 'bg-accent/20' : 'bg-surface-2'}" onclick={() => (w.rating = i + 1)}>{emo}</button>
      {/each}
    </div>
    <textarea class="input mb-4" rows="3" placeholder="Notizen (optional)" bind:value={w.notes}></textarea>
    <button class="btn-primary w-full" onclick={finish}>Speichern & beenden</button>
  {/if}
</Sheet>

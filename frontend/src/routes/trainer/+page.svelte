<script>
  import { onMount } from 'svelte';
  import { api } from '$lib/api.js';
  import { toast, toastError } from '$lib/toast.svelte.js';
  import { energy, fmtDate, fmtNum, fmtWeight, toDisplayWeight, weightUnit } from '$lib/units.js';
  import { accent, cv } from '$lib/colors.js';
  import Chart from '$components/Chart.svelte';
  import Header from '$components/Header.svelte';
  import Icon from '$components/Icon.svelte';
  import MuscleMap from '$components/MuscleMap.svelte';
  import Empty from '$components/Empty.svelte';

  let athletes = $state([]);
  let sel = $state(null);
  let d = $state(null);
  let comment = $state('');

  onMount(async () => { athletes = await api.get('/api/trainer/athletes'); if (athletes.length) pick(athletes[0]); });
  async function pick(a) {
    sel = a; d = null;
    const q = `athlete=${a.id}`;
    const [workouts, muscles, nutrition, weight, week] = await Promise.all([
      api.get(`/api/workouts?${q}&limit=10`), api.get(`/api/stats/muscles?${q}&days=14`), api.get(`/api/stats/nutrition?${q}&days=14`),
      api.get(`/api/stats/weight?${q}&days=60`), api.get(`/api/reports/week?${q}`)]).catch((e) => { toastError(e); return []; });
    d = { workouts, muscles, nutrition, weight, week };
  }
  async function send() {
    if (!comment.trim()) return;
    try { await api.post('/api/trainer/comments', { athlete_id: sel.id, text: comment }); comment = ''; toast('Kommentar gesendet', 'success'); } catch (e) { toastError(e); }
  }
</script>

<Header title="Meine Athleten" back="/profile" />
<div class="space-y-3 px-4">
  {#if !athletes.length}<Empty icon="user" title="Noch keine Freigaben" text="Athleten können dich unter Einstellungen → Trainer & Teilen freigeben." />{:else}
    <div class="no-scrollbar flex gap-1.5 overflow-x-auto">{#each athletes as a}<button class={sel?.id === a.id ? 'chip-active' : 'chip'} onclick={() => pick(a)}>{a.display_name}</button>{/each}</div>
    {#if d?.week}
      <div class="grid grid-cols-3 gap-2 text-center">
        <div class="card p-3"><div class="text-xs text-muted">Trainings (Vorwoche)</div><div class="font-bold">{d.week.data.training.workouts}</div></div>
        <div class="card p-3"><div class="text-xs text-muted">Ø kcal (14 T)</div><div class="font-bold">{fmtNum(energy(d.nutrition.average.kcal), 0)}</div></div>
        <div class="card p-3"><div class="text-xs text-muted">Ø Protein</div><div class="font-bold">{fmtNum(d.nutrition.average.protein, 0)} g</div></div>
      </div>
      <div class="card"><div class="mb-2 text-sm font-semibold">Muskelbelastung (14 Tage)</div><MuscleMap values={d.muscles.weekly_sets} size={100} /></div>
      {#if d.weight.length > 1}
        <div class="card"><div class="mb-2 text-sm font-semibold">Gewicht</div>
          <Chart height={180} option={{ xAxis: { type: 'category', data: d.weight.map((p) => fmtDate(p.day, { day: '2-digit', month: '2-digit' })) }, yAxis: { type: 'value', scale: true },
            series: [{ type: 'line', smooth: true, color: accent(), data: d.weight.map((p) => toDisplayWeight(p.avg)) }] }} /></div>
      {/if}
      <div class="card p-0"><div class="px-4 pt-3 text-sm font-semibold">Letzte Trainings</div>
        {#each d.workouts as w}<div class="list-row text-sm"><span class="flex-1">{w.name}</span><span class="text-muted">{fmtDate(w.started_at)} · {w.sets_count} Sätze · {fmtNum(toDisplayWeight(w.volume_kg), 0)} {weightUnit()}</span></div>{/each}
      </div>
      <div class="card space-y-2"><div class="font-semibold">Kommentar an {sel.display_name}</div>
        <textarea class="input" rows="3" placeholder="Feedback, Hinweise …" bind:value={comment}></textarea>
        <button class="btn-primary w-full" onclick={send}><Icon name="send" size={18} /> Senden</button></div>
    {/if}
  {/if}
</div>

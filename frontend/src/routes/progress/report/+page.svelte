<script>
  import { page } from '$app/state';
  import { goto } from '$app/navigation';
  import { api, qs } from '$lib/api.js';
  import { toast, toastError } from '$lib/toast.svelte.js';
  import { MUSCLES, addDays, energy, fmtDate, fmtNum, fmtWeight, toDisplayWeight, weightUnit } from '$lib/units.js';
  import { accent, cv } from '$lib/colors.js';
  import Chart from '$components/Chart.svelte';
  import Header from '$components/Header.svelte';
  import Icon from '$components/Icon.svelte';
  import MuscleMap from '$components/MuscleMap.svelte';
  import Skeleton from '$components/Skeleton.svelte';

  let periodType = $state(page.url.searchParams.get('period') || 'week');
  let start = $state(page.url.searchParams.get('start') || null);
  let r = $state(null);
  let generating = $state(false);

  function load(p, s) {
    const url = p === 'week' ? '/api/reports/week' + qs({ start: s }) : '/api/reports/month' + qs({ month: s ? s.slice(0, 7) : null });
    return api.get(url).then((x) => { r = x; }).catch(toastError);
  }
  $effect(() => { const p = periodType, s = start; r = null; load(p, s); });
  function shift(n) {
    if (periodType === 'week') start = addDays(r.start, 7 * n);
    else { const d = new Date(r.start + 'T12:00:00'); d.setMonth(d.getMonth() + n); start = d.toISOString().slice(0, 10); }
  }
  async function generate() {
    generating = true;
    try { await api.post(`/api/coach/reports/${periodType}?start=${r.start}`); toast('Bewertung erstellt', 'success'); await load(periodType, r.start); }
    catch (e) { toastError(e); } finally { generating = false; }
  }
  const rep = $derived(r?.coach?.data?.report);
  const t = $derived(r?.data?.training);
  const n = $derived(r?.data?.nutrition);
  const delta = (a, b) => (a == null || b == null ? '' : `${a - b >= 0 ? '+' : ''}${fmtNum(a - b, 0)}`);
</script>

<Header title={periodType === 'week' ? 'Wochenrückblick' : 'Monatsrückblick'} back="/progress" />
<div class="space-y-3 px-4">
  <div class="flex items-center gap-2">
    <div class="flex gap-1.5">{#each [['week', 'Woche'], ['month', 'Monat']] as [k, l]}<button class={periodType === k ? 'chip-active' : 'chip'} onclick={() => { periodType = k; start = null; }}>{l}</button>{/each}</div>
    <div class="flex flex-1 items-center justify-end gap-1">
      <button class="rounded-xl bg-surface-2 p-2" onclick={() => shift(-1)} disabled={!r} aria-label="Zurück"><Icon name="back" size={18} /></button>
      <span class="text-sm font-medium">{r ? `${fmtDate(r.start, { day: '2-digit', month: '2-digit' })} – ${fmtDate(r.end, { day: '2-digit', month: '2-digit' })}` : ''}</span>
      <button class="rounded-xl bg-surface-2 p-2" onclick={() => shift(1)} disabled={!r} aria-label="Weiter"><Icon name="right" size={18} /></button>
    </div>
  </div>

  {#if !r}<Skeleton lines={4} h="h-40" />{:else}
    <div class="card overflow-hidden bg-gradient-to-br from-accent/20 to-transparent">
      {#if rep}
        <div class="flex items-start gap-4">
          <div class="flex h-20 w-20 shrink-0 flex-col items-center justify-center rounded-3xl bg-accent text-white shadow-lg">
            <span class="text-3xl font-black">{rep.score}</span><span class="text-[10px] opacity-80">von 10</span></div>
          <div><h2 class="text-xl font-bold">{rep.headline}</h2><p class="mt-1 text-sm">{rep.summary}</p></div>
        </div>
        {#if rep.training_score}<div class="mt-3 flex gap-2 text-xs"><span class="chip">Training {rep.training_score}/10</span><span class="chip">Ernährung {rep.nutrition_score}/10</span></div>{/if}
      {:else}
        <p class="font-semibold">Noch keine Coach-Bewertung für diesen Zeitraum</p>
        <p class="text-sm text-muted">Wird automatisch erstellt (montags / am Monatsersten) – oder jetzt:</p>
      {/if}
      <button class="btn-soft btn-sm mt-3" disabled={generating} onclick={generate}><Icon name="sparkles" size={16} /> {generating ? 'Erstelle …' : rep ? 'Neu bewerten' : 'Bewertung erstellen'}</button>
    </div>

    <div class="grid grid-cols-2 gap-2 sm:grid-cols-4">
      <div class="card p-3"><div class="text-xs text-muted">Trainings</div><div class="text-2xl font-bold">{t.workouts}</div><div class="text-xs text-muted">{delta(t.workouts, r.previous?.training?.workouts)} ggü. Vorperiode</div></div>
      <div class="card p-3"><div class="text-xs text-muted">Volumen</div><div class="text-2xl font-bold">{fmtNum(toDisplayWeight(t.tonnage_kg) / 1000, 1)} t</div><div class="text-xs text-muted">{t.sets} Sätze{t.avg_rpe ? ` · Ø RPE ${t.avg_rpe}` : ''}</div></div>
      <div class="card p-3"><div class="text-xs text-muted">Ø kcal / Protein</div><div class="text-xl font-bold">{fmtNum(energy(n.average.kcal), 0)} / {fmtNum(n.average.protein, 0)} g</div><div class="text-xs text-muted">Ziel {n.target_kcal_avg} / {n.target_protein_avg} g</div></div>
      <div class="card p-3"><div class="text-xs text-muted">Gewicht</div><div class="text-xl font-bold">{r.data.body.weight_change != null ? (r.data.body.weight_change > 0 ? '+' : '') + fmtWeight(r.data.body.weight_change, 2) : '–'}</div><div class="text-xs text-muted">{r.data.body.weight_end ? `Ø ${fmtWeight(r.data.body.weight_end)}` : ''}</div></div>
    </div>

    {#if rep?.highlights?.length || t.prs.length}
      <div class="card"><div class="mb-2 font-semibold"><Icon name="trophy" size={18} class="inline text-warn" /> Highlights</div>
        <ul class="space-y-1 text-sm">{#each rep?.highlights || [] as h}<li>✓ {h}</li>{/each}
          {#each t.prs.slice(0, 6) as p}<li>🏆 {p.exercise}: {p.type === 'e1rm' ? `1RM ${fmtWeight(p.value)}` : `${fmtWeight(p.value)} Top-Gewicht`}</li>{/each}</ul></div>
    {/if}
    {#if rep?.recommendations?.length}
      <div class="card border-accent/40"><div class="mb-2 font-semibold"><Icon name="sparkles" size={18} class="inline text-accent" /> Empfehlungen für {periodType === 'week' ? 'nächste Woche' : 'nächsten Monat'}</div>
        <ol class="ml-4 list-decimal space-y-1 text-sm">{#each rep.recommendations as rec}<li>{rec}</li>{/each}</ol>
        {#if rep.improvements?.length}<p class="mt-3 text-sm font-medium">Verbesserungspotenzial</p><ul class="ml-4 list-disc text-sm text-muted">{#each rep.improvements as i}<li>{i}</li>{/each}</ul>{/if}
        {#if rep.recovery_note}<p class="mt-2 text-sm text-muted">😴 {rep.recovery_note}</p>{/if}
      </div>
    {/if}

    <div class="card"><div class="mb-2 text-sm font-semibold">Trainierte Muskeln</div><MuscleMap values={t.muscle_sets} size={110} /></div>
    {#if r.nutrition_days || r.nutrition}
      {@const days = r.nutrition_days || r.nutrition.days}
      <div class="card"><div class="mb-2 text-sm font-semibold">Ernährung</div>
        <Chart name="bericht-ernaehrung" height={220} option={{
          legend: {}, xAxis: { type: 'category', data: days.map((x) => fmtDate(x.day, { weekday: periodType === 'week' ? 'short' : undefined, day: '2-digit' })) },
          yAxis: [{ type: 'value' }, { type: 'value', splitLine: { show: false } }],
          series: [{ name: 'kcal', type: 'bar', data: days.map((x) => energy(x.kcal || 0)), itemStyle: { borderRadius: 4, color: cv('--carbs') } },
            { name: 'Ziel', type: 'line', step: 'middle', showSymbol: false, data: days.map((x) => energy(x.target_kcal)), lineStyle: { type: 'dashed' }, color: cv('--muted') },
            { name: 'Protein', type: 'line', yAxisIndex: 1, smooth: true, data: days.map((x) => x.protein || 0), color: cv('--protein') }]
        }} />
      </div>
    {/if}
    {#if r.weight?.length > 1}
      <div class="card"><div class="mb-2 text-sm font-semibold">Gewicht</div>
        <Chart name="bericht-gewicht" height={180} option={{ xAxis: { type: 'category', data: r.weight.map((p) => fmtDate(p.day, { day: '2-digit', month: '2-digit' })) }, yAxis: { type: 'value', scale: true },
          series: [{ name: '7-Tage-Mittel', type: 'line', smooth: true, color: accent(), data: r.weight.map((p) => toDisplayWeight(p.avg)), areaStyle: { opacity: 0.1 } }] }} />
      </div>
    {/if}
    <div class="card p-0"><div class="px-4 pt-3 text-sm font-semibold">Übungen</div>
      {#each Object.entries(t.exercises).sort((a, b) => b[1].sets - a[1].sets) as [name, e]}
        <div class="list-row text-sm"><span class="flex-1">{name}</span><span class="text-muted">{e.sets} Sätze · 1RM {fmtWeight(e.best_e1rm)}</span></div>
      {:else}<p class="p-4 text-sm text-muted">Keine Trainings</p>{/each}
    </div>
    <button class="btn-soft w-full" onclick={() => window.print()}><Icon name="download" size={18} /> Drucken / PDF</button>
  {/if}
</div>

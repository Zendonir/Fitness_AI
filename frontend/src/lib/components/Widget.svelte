<script>
  import { api, qs } from '$lib/api.js';
  import { session } from '$lib/session.svelte.js';
  import { fmtWeight, energy, energyUnit, fmtNum, fmtDate, toDisplayWeight, weightUnit, today, addDays } from '$lib/units.js';
  import { tap, success } from '$lib/haptics.js';
  import { toastError } from '$lib/toast.svelte.js';
  import Ring from './Ring.svelte';
  import Chart from './Chart.svelte';
  import MuscleMap from './MuscleMap.svelte';
  import Icon from './Icon.svelte';
  import { accent, cv } from '$lib/colors.js';

  let { widget, data, reload = () => {} } = $props();
  let extra = $state(null);
  const cfg = $derived(widget.config || {});

  $effect(() => {
    const t = widget.type;
    const days = cfg.days || 7;
    extra = null;
    if (t === 'muscle_heatmap') api.get(`/api/stats/muscles?days=${days}`).then((r) => (extra = r)).catch(() => {});
    if (t === 'calendar') api.get('/api/stats/calendar?days=120').then((r) => (extra = r)).catch(() => {});
    if (t === 'weekly_volume') api.get('/api/stats/weekly-volume?weeks=8').then((r) => (extra = r)).catch(() => {});
    if (t === 'kcal_trend') api.get('/api/stats/nutrition?days=14').then((r) => (extra = r)).catch(() => {});
    if (t === 'exercise_1rm' && cfg.exercise_id) api.get(`/api/stats/exercise/${cfg.exercise_id}?days=180`).then((r) => (extra = r)).catch(() => {});
    if (t === 'metric' && cfg.metric_id) api.get(`/api/metrics/${cfg.metric_id}/entries?days=30`).then((r) => (extra = r)).catch(() => {});
    if (t === 'body_stats') api.get('/api/body?days=30').then((r) => (extra = r)).catch(() => {});
  });

  const n = $derived(data?.nutrition);
  async function addWater(ml) {
    tap();
    try { await api.post('/api/water', { ml }); success(); reload(); } catch (e) { toastError(e); }
  }
  const visible = (k) => (session.settings?.visible_nutrients || ['kcal', 'protein', 'carbs', 'fat']).includes(k);
</script>

<div class="card h-full {widget.w >= 2 ? '' : 'p-3'}">
  {#if widget.type === 'macros' && n}
    <div class="mb-3 flex items-center justify-between">
      <span class="text-sm font-semibold">Makros {n.day_type === 'training' ? '· Trainingstag' : '· Ruhetag'}</span>
      <a href="/nutrition" class="text-sm text-accent">Loggen</a>
    </div>
    <div class="flex items-center justify-around">
      <Ring value={energy(n.totals.kcal)} max={energy(n.targets.kcal)} size={112} stroke={11} big sub={`/ ${energy(n.targets.kcal)} ${energyUnit()}`} />
      <div class="grid grid-cols-2 gap-x-3 gap-y-2">
        {#each [['protein', 'Protein'], ['carbs', 'Kohlenh.'], ['fat', 'Fett'], ['fiber', 'Ballast.']] as [k, l]}
          {#if visible(k)}
            <Ring value={n.totals[k]} max={n.targets[k]} size={58} stroke={6} color="var(--{k})" label={l} sub={`/${Math.round(n.targets[k])}g`} />
          {/if}
        {/each}
      </div>
    </div>
    <p class="mt-2 text-center text-xs text-muted">Noch {fmtNum(Math.max(0, energy(n.targets.kcal - n.totals.kcal)), 0)} {energyUnit()} · {fmtNum(Math.max(0, n.targets.protein - n.totals.protein), 0)} g Protein offen</p>

  {:else if widget.type === 'workout_today'}
    {@const t = data?.training}
    <div class="flex items-center gap-3">
      <div class="rounded-2xl bg-accent/15 p-3 text-accent"><Icon name="dumbbell" /></div>
      <div class="min-w-0 flex-1">
        {#if !t?.active_plan}
          <div class="font-semibold">Kein aktiver Plan</div><div class="text-sm text-muted">Freies Training starten</div>
        {:else if t.rest_day}
          <div class="font-semibold">Ruhetag 😴</div><div class="text-sm text-muted">Nächstes: {t.day.name}</div>
        {:else}
          <div class="truncate font-semibold">{t.day.name}{t.deload ? ' · Deload' : ''}</div>
          <div class="truncate text-sm text-muted">{t.exercises.length} Übungen · Woche {t.week}/{t.weeks}{t.done_today ? ' · erledigt ✓' : ''}</div>
        {/if}
      </div>
      <a href="/training" class="btn-primary btn-sm"><Icon name="play" size={16} /></a>
    </div>

  {:else if widget.type === 'coach_hint'}
    {#if data?.hint}
      <a href="/coach" class="flex gap-3">
        <div class="h-fit rounded-2xl bg-accent/15 p-2.5 text-accent"><Icon name="sparkles" /></div>
        <div><div class="font-semibold">{data.hint.title}</div><p class="line-clamp-3 text-sm text-muted">{data.hint.body}</p></div>
      </a>
    {:else}
      <a href="/coach" class="flex items-center gap-3 text-muted"><Icon name="sparkles" /> Frag deinen Coach …</a>
    {/if}

  {:else if widget.type === 'water' && n}
    {@const goal = data.water_goal_ml || 2500}
    <div class="flex items-center gap-2 text-sm font-semibold"><Icon name="water" size={18} class="text-protein" /> Wasser</div>
    <div class="my-2 text-2xl font-bold tabular-nums">{fmtNum(n.water_ml / 1000, 2)} <span class="text-sm text-muted">/ {goal / 1000} l</span></div>
    <div class="mb-2 h-2 overflow-hidden rounded-full bg-surface-2"><div class="h-full bg-protein transition-all duration-700" style="width:{Math.min(100, (n.water_ml / goal) * 100)}%"></div></div>
    <div class="flex gap-1.5"><button class="btn-soft btn-sm flex-1" onclick={() => addWater(250)}>+250</button><button class="btn-soft btn-sm flex-1" onclick={() => addWater(500)}>+500</button></div>

  {:else if widget.type === 'streak'}
    {@const s = data?.streaks || {}}
    <div class="flex items-center gap-2 text-sm font-semibold"><Icon name="fire" size={18} class="text-warn" /> Streak</div>
    <div class="my-1 text-3xl font-bold tabular-nums">{s.days ?? 0} <span class="text-sm font-medium text-muted">Tage</span></div>
    <div class="text-xs text-muted">{s.training_weeks ?? 0} Trainingswochen in Folge · {s.workouts_30d ?? 0} Trainingstage/30 T</div>

  {:else if widget.type === 'weight_trend'}
    {@const w = data?.weight || []}
    <div class="flex items-center justify-between"><span class="text-sm font-semibold">Gewichtstrend</span>
      <span class="text-sm font-bold">{w.length ? fmtWeight(w.at(-1).avg) : '–'}</span></div>
    {#if w.length > 1}
      <Chart height={140} toolbar={false} option={{
        grid: { left: 4, right: 4, top: 10, bottom: 4, containLabel: true },
        xAxis: { type: 'category', data: w.map((p) => fmtDate(p.day, { day: '2-digit', month: '2-digit' })), axisLabel: { show: false } },
        yAxis: { type: 'value', scale: true, splitNumber: 3 },
        series: [
          { name: 'Gewicht', type: 'scatter', symbolSize: 5, data: w.map((p) => toDisplayWeight(p.value)), itemStyle: { color: cv('--muted'), opacity: 0.5 } },
          { name: '7-Tage-Mittel', type: 'line', smooth: true, showSymbol: false, data: w.map((p) => toDisplayWeight(p.avg)), lineStyle: { width: 3 }, color: accent() }
        ]
      }} />
    {:else}<a href="/progress/body" class="mt-3 block text-sm text-accent">Gewicht eintragen →</a>{/if}

  {:else if widget.type === 'muscle_heatmap'}
    <div class="mb-1 flex justify-between text-sm font-semibold"><span>Muskelbelastung</span><span class="text-muted">{cfg.days || 7} Tage</span></div>
    {#if extra}<MuscleMap values={extra.weekly_sets} size={widget.w >= 2 ? 110 : 60} />{:else}<div class="skeleton h-40"></div>{/if}

  {:else if widget.type === 'calendar'}
    <div class="mb-1 text-sm font-semibold">Trainingskalender</div>
    {#if extra}
      <Chart height={150} toolbar={false} option={{
        tooltip: { trigger: 'item', formatter: (p) => `${p.data[0]}: ${p.data[1]} Einheit(en)` },
        visualMap: { show: false, min: 0, max: 2, inRange: { color: ['#88888822', accent()] } },
        calendar: { range: [addDays(today(), -119), today()], cellSize: ['auto', 13], dayLabel: { show: false }, monthLabel: { nameMap: 'DE', fontSize: 10 }, yearLabel: { show: false }, itemStyle: { borderWidth: 2, borderColor: 'transparent' }, splitLine: { show: false }, top: 20, left: 10, right: 10 },
        series: [{ type: 'heatmap', coordinateSystem: 'calendar', data: extra.map((d) => [d.day, d.workouts + d.cardio]) }]
      }} />
    {/if}

  {:else if widget.type === 'weekly_volume'}
    <div class="mb-1 text-sm font-semibold">Wochenvolumen (Sätze)</div>
    {#if extra}
      <Chart height={180} toolbar={false} option={{
        xAxis: { type: 'category', data: extra.weeks.map((w) => fmtDate(w, { day: '2-digit', month: '2-digit' })) },
        yAxis: { type: 'value' },
        series: [{ type: 'bar', data: extra.weeks.map((_, i) => Object.values(extra.sets_by_muscle).reduce((a, s) => a + s[i], 0)), itemStyle: { borderRadius: 6, color: accent() } }]
      }} />
    {/if}

  {:else if widget.type === 'kcal_trend'}
    <div class="mb-1 text-sm font-semibold">Kalorien vs. Ziel</div>
    {#if extra}
      <Chart height={160} toolbar={false} option={{
        xAxis: { type: 'category', data: extra.days.map((d) => fmtDate(d.day, { day: '2-digit' })) },
        yAxis: { type: 'value' },
        series: [
          { name: 'Gegessen', type: 'bar', data: extra.days.map((d) => energy(d.kcal || 0)), itemStyle: { borderRadius: 4, color: '#f59e0b' } },
          { name: 'Ziel', type: 'line', step: 'middle', showSymbol: false, data: extra.days.map((d) => energy(d.target_kcal)), lineStyle: { type: 'dashed' } }
        ]
      }} />
    {/if}

  {:else if widget.type === 'exercise_1rm'}
    <div class="mb-1 text-sm font-semibold">{extra?.exercise?.name || 'Übung wählen'} · 1RM</div>
    {#if extra?.sessions?.length}
      <Chart height={150} toolbar={false} option={{
        xAxis: { type: 'category', data: extra.sessions.map((s) => fmtDate(s.day, { day: '2-digit', month: '2-digit' })) },
        yAxis: { type: 'value', scale: true },
        series: [{ type: 'line', smooth: true, data: extra.sessions.map((s) => toDisplayWeight(s.e1rm)), areaStyle: { opacity: 0.15 } }]
      }} />
    {:else}<p class="text-sm text-muted">Übung im Bearbeiten-Modus festlegen.</p>{/if}

  {:else if widget.type === 'metric'}
    <div class="mb-1 text-sm font-semibold">{cfg.title || 'Metrik'}</div>
    {#if extra?.length}
      <Chart height={140} toolbar={false} option={{
        xAxis: { type: 'category', data: extra.map((e) => fmtDate(e.day, { day: '2-digit', month: '2-digit' })) },
        yAxis: { type: 'value', scale: true },
        series: [{ type: 'line', smooth: true, data: extra.map((e) => e.value_num) }]
      }} />
    {:else}<a href="/progress/metrics" class="text-sm text-accent">Werte erfassen →</a>{/if}

  {:else if widget.type === 'body_stats'}
    <div class="mb-2 text-sm font-semibold">Körper</div>
    {#if extra}
      <div class="grid grid-cols-2 gap-2 text-sm">
        <div><span class="text-muted">Gewicht</span><div class="font-bold">{fmtWeight(extra.latest.weight_kg)}</div></div>
        <div><span class="text-muted">7-T-Änderung</span><div class="font-bold">{extra.weekly_change_kg != null ? (extra.weekly_change_kg > 0 ? '+' : '') + fmtNum(toDisplayWeight(extra.weekly_change_kg), 2) + ' ' + weightUnit() : '–'}</div></div>
        <div><span class="text-muted">KFA</span><div class="font-bold">{extra.latest.body_fat_pct ?? '–'} %</div></div>
        <div><span class="text-muted">Taille</span><div class="font-bold">{extra.latest.waist_cm ?? '–'} cm</div></div>
      </div>
    {/if}

  {:else if widget.type === 'quick_add'}
    <div class="grid grid-cols-4 gap-2 text-center text-xs">
      <a href="/nutrition/add" class="flex flex-col items-center gap-1"><span class="rounded-2xl bg-surface-2 p-3"><Icon name="plus" /></span>Essen</a>
      <a href="/nutrition/add?mode=barcode" class="flex flex-col items-center gap-1"><span class="rounded-2xl bg-surface-2 p-3"><Icon name="barcode" /></span>Scan</a>
      <a href="/progress/body?add=1" class="flex flex-col items-center gap-1"><span class="rounded-2xl bg-surface-2 p-3"><Icon name="body" /></span>Gewicht</a>
      <a href="/training" class="flex flex-col items-center gap-1"><span class="rounded-2xl bg-surface-2 p-3"><Icon name="dumbbell" /></span>Training</a>
    </div>
  {:else}
    <div class="skeleton h-20"></div>
  {/if}
</div>

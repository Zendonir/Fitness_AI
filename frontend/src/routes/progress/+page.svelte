<script>
  import { onMount } from 'svelte';
  import { api, qs } from '$lib/api.js';
  import { session } from '$lib/session.svelte.js';
  import { MUSCLES, addDays, energy, energyUnit, fmtDate, fmtNum, toDisplayWeight, today, weightUnit } from '$lib/units.js';
  import { accent, cv, PALETTE } from '$lib/colors.js';
  import Chart from '$components/Chart.svelte';
  import Header from '$components/Header.svelte';
  import Icon from '$components/Icon.svelte';
  import MuscleMap from '$components/MuscleMap.svelte';
  import PeriodPicker from '$components/PeriodPicker.svelte';
  import Skeleton from '$components/Skeleton.svelte';

  let tab = $state('training');
  let period = $state({ start: addDays(today(), -29), end: today(), days: 30, compare: false, cstart: addDays(today(), -59), cend: addDays(today(), -30) });
  let d = $state({});
  let cmp = $state({});
  let exercises = $state([]);
  let exId = $state(null);
  let muscleSel = $state(null);

  onMount(async () => {
    const recent = await api.get('/api/training/recent-exercises').catch(() => []);
    exercises = recent.length ? recent : (await api.get('/api/exercises')).slice(0, 30);
    exId = exercises[0]?.id ?? null;
  });

  $effect(() => {
    const p = { start: period.start, end: period.end };
    const c = { start: period.cstart, end: period.cend };
    const t = tab, compare = period.compare, e = exId;
    const get = (url, params) => api.get(url + qs(params)).catch(() => null);
    d = {}; cmp = {};
    if (t === 'training') {
      get('/api/stats/muscles', p).then((r) => (d.muscles = r));
      get('/api/stats/calendar', p).then((r) => (d.calendar = r));
      const weeks = Math.max(4, Math.ceil(((new Date(period.end) - new Date(period.start)) / 86400000 + 1) / 7));
      get('/api/stats/weekly-volume', { weeks, end: period.end }).then((r) => (d.weekly = r));
      if (e) get(`/api/stats/exercise/${e}`, p).then((r) => (d.exercise = r));
      if (compare) {
        get('/api/stats/muscles', c).then((r) => (cmp.muscles = r));
        if (e) get(`/api/stats/exercise/${e}`, c).then((r) => (cmp.exercise = r));
      }
    } else if (t === 'nutrition') {
      get('/api/stats/nutrition', p).then((r) => (d.nutrition = r));
      if (compare) get('/api/stats/nutrition', c).then((r) => (cmp.nutrition = r));
    } else if (t === 'body') {
      get('/api/stats/weight', p).then((r) => (d.weight = r));
      get('/api/body', { days: (new Date(period.end) - new Date(period.start)) / 86400000 + 1 }).then((r) => (d.body = r));
      if (compare) get('/api/stats/weight', c).then((r) => (cmp.weight = r));
    } else if (t === 'corr') {
      get('/api/stats/correlations', p).then((r) => (d.corr = r));
    } else if (t === 'metrics') {
      api.get('/api/metrics').then(async (defs) => {
        d.metrics = await Promise.all(defs.filter((m) => !m.archived && m.kind !== 'text').map(async (m) => ({ ...m, entries: await api.get(`/api/metrics/${m.id}/entries?days=${Math.max(7, (new Date(period.end) - new Date(period.start)) / 86400000 + 1)}`) })));
      });
    }
  });

  const dd = (x) => fmtDate(x, { day: '2-digit', month: '2-digit' });
  const zoom = [{ type: 'inside', filterMode: 'none' }];
  const mc = () => session.settings?.theme?.muscle_colors || {};

  function sum(o) { return Object.values(o || {}).reduce((a, b) => a + b, 0); }
</script>

<Header title="Fortschritt">
  {#snippet actions()}<a href="/progress/report" class="btn-soft btn-sm"><Icon name="calendar" size={16} /> Berichte</a>{/snippet}
</Header>

<div class="space-y-3 px-4">
  <div class="no-scrollbar flex gap-1.5 overflow-x-auto">
    {#each [['training', 'Training'], ['nutrition', 'Ernährung'], ['body', 'Körper'], ['metrics', 'Metriken'], ['corr', 'Korrelationen']] as [k, l]}
      <button class={tab === k ? 'chip-active' : 'chip'} onclick={() => (tab = k)}>{l}</button>
    {/each}
  </div>
  <PeriodPicker bind:value={period} />

  {#if tab === 'training'}
    <div class="card">
      <div class="mb-2 flex justify-between text-sm font-semibold"><span>Muskel-Heatmap (Sätze/Woche)</span>
        {#if muscleSel}<span class="text-accent">{MUSCLES[muscleSel]}: {d.muscles?.weekly_sets?.[muscleSel] ?? 0}{period.compare ? ` (vorher ${cmp.muscles?.weekly_sets?.[muscleSel] ?? 0})` : ''}</span>{/if}</div>
      {#if d.muscles}<MuscleMap values={d.muscles.weekly_sets} size={130} onselect={(m) => (muscleSel = m)} selected={muscleSel} />
        <div class="mt-2 flex justify-center gap-3 text-[10px] text-muted">
          <span>◼︎ &lt;4 wenig</span><span>4–10 moderat</span><span class="text-accent">10–20 optimal</span><span class="text-warn">&gt;20 hoch</span></div>
      {:else}<Skeleton lines={1} h="h-72" />{/if}
    </div>
    {#if d.muscles && Object.keys(d.muscles.sets).length}
      <div class="card">
        <div class="mb-2 text-sm font-semibold">Sätze pro Muskelgruppe{period.compare ? ' (Vergleich)' : ''}</div>
        <Chart name="muskelgruppen" height={Math.max(220, Object.keys(MUSCLES).length * 18)} option={{
          legend: period.compare ? {} : undefined,
          grid: { left: 4, right: 12, top: period.compare ? 28 : 8, bottom: 4, containLabel: true },
          yAxis: { type: 'category', data: Object.keys(MUSCLES).map((m) => MUSCLES[m]), inverse: true },
          xAxis: { type: 'value' },
          series: [
            { name: 'Zeitraum', type: 'bar', data: Object.keys(MUSCLES).map((m) => ({ value: d.muscles.sets[m] || 0, itemStyle: { color: mc()[m] || accent() } })), itemStyle: { borderRadius: 4 } },
            ...(period.compare && cmp.muscles ? [{ name: 'Vergleich', type: 'bar', data: Object.keys(MUSCLES).map((m) => cmp.muscles.sets[m] || 0), itemStyle: { color: cv('--muted'), borderRadius: 4 } }] : [])
          ]
        }} />
      </div>
    {/if}
    {#if d.weekly}
      <div class="card">
        <div class="mb-2 text-sm font-semibold">Wochenvolumen nach Muskelgruppe</div>
        <Chart name="wochenvolumen" height={280} option={{
          legend: { type: 'scroll' }, dataZoom: zoom,
          xAxis: { type: 'category', data: d.weekly.weeks.map(dd) },
          yAxis: [{ type: 'value', name: 'Sätze' }, { type: 'value', name: weightUnit(), splitLine: { show: false } }],
          series: [
            ...Object.entries(d.weekly.sets_by_muscle).map(([m, v], i) => ({ name: MUSCLES[m], type: 'bar', stack: 'sets', data: v, color: mc()[m] || PALETTE[i % PALETTE.length] })),
            { name: 'Tonnage', type: 'line', yAxisIndex: 1, smooth: true, data: d.weekly.tonnage_kg.map((x) => Math.round(toDisplayWeight(x))), color: cv('--muted') }
          ]
        }} />
      </div>
    {/if}
    {#if d.calendar}
      <div class="card">
        <div class="mb-2 text-sm font-semibold">Trainingskalender</div>
        <Chart name="kalender" height={180} option={{
          tooltip: { trigger: 'item', formatter: (p) => `${fmtDate(p.data[0])}: ${p.data[1]} Einheit(en), ${fmtNum(toDisplayWeight(p.data[2]), 0)} ${weightUnit()}` },
          visualMap: { show: false, min: 0, max: 2, inRange: { color: [cv('--surface-2'), accent()] } },
          calendar: { range: [period.start, period.end], cellSize: ['auto', 16], left: 30, right: 10, top: 24, dayLabel: { firstDay: 1, nameMap: ['S', 'M', 'D', 'M', 'D', 'F', 'S'], fontSize: 9 },
            monthLabel: { nameMap: ['Jan', 'Feb', 'Mär', 'Apr', 'Mai', 'Jun', 'Jul', 'Aug', 'Sep', 'Okt', 'Nov', 'Dez'] }, yearLabel: { show: false }, splitLine: { show: false }, itemStyle: { borderWidth: 3, borderColor: cv('--surface') } },
          series: [{ type: 'heatmap', coordinateSystem: 'calendar', data: d.calendar.map((x) => [x.day, x.workouts + x.cardio, x.volume_kg]) }]
        }} csv={d.calendar} />
      </div>
    {/if}
    <div class="card">
      <div class="mb-2 flex items-center justify-between gap-2"><span class="text-sm font-semibold">Übung</span>
        <select class="input w-auto py-1.5 text-sm" bind:value={exId}>{#each exercises as e}<option value={e.id}>{e.name}</option>{/each}</select></div>
      {#if d.exercise?.sessions?.length}
        {@const base = d.exercise.sessions}
        <Chart name="1rm" height={260} option={{
          legend: {}, dataZoom: zoom,
          xAxis: { type: 'category', data: base.map((s) => dd(s.day)) },
          yAxis: [{ type: 'value', scale: true, name: weightUnit() }, { type: 'value', splitLine: { show: false } }],
          series: [
            { name: '1RM (Epley)', type: 'line', smooth: true, color: accent(), data: base.map((s) => ({ value: toDisplayWeight(s.e1rm), symbolSize: s.pr ? 12 : 5, itemStyle: s.pr ? { color: '#f59e0b' } : undefined })) },
            { name: 'Volumen', type: 'bar', yAxisIndex: 1, color: cv('--muted'), itemStyle: { opacity: 0.3, borderRadius: 3 }, data: base.map((s) => Math.round(toDisplayWeight(s.volume_kg))) },
            ...(period.compare && cmp.exercise?.sessions?.length ? [{ name: 'Vergleich 1RM', type: 'line', smooth: true, lineStyle: { type: 'dashed' }, color: '#3b82f6', data: cmp.exercise.sessions.map((s) => toDisplayWeight(s.e1rm)) }] : [])
          ]
        }} />
        <p class="mt-1 text-xs text-muted">Orange Punkte = neue Bestleistung (PR). Pinch/Scroll zum Zoomen.</p>
      {:else}<p class="text-sm text-muted">Keine Daten im Zeitraum.</p>{/if}
    </div>

  {:else if tab === 'nutrition'}
    {#if !d.nutrition}<Skeleton lines={3} h="h-48" />{:else}
      {@const n = d.nutrition}
      <div class="grid grid-cols-3 gap-2 text-center">
        <div class="card p-3"><div class="text-xs text-muted">Ø {energyUnit()}</div><div class="font-bold">{fmtNum(energy(n.average.kcal), 0)}</div>
          {#if cmp.nutrition}<div class="text-xs text-muted">vorher {fmtNum(energy(cmp.nutrition.average.kcal), 0)}</div>{/if}</div>
        <div class="card p-3"><div class="text-xs text-muted">Ø Protein</div><div class="font-bold">{fmtNum(n.average.protein, 0)} g</div>
          {#if cmp.nutrition}<div class="text-xs text-muted">vorher {fmtNum(cmp.nutrition.average.protein, 0)} g</div>{/if}</div>
        <div class="card p-3"><div class="text-xs text-muted">Ziel erreicht</div><div class="font-bold">{n.adherence_pct} %</div><div class="text-xs text-muted">{n.logged_days} Tage geloggt</div></div>
      </div>
      <div class="card">
        <div class="mb-2 text-sm font-semibold">Kalorien vs. Ziel</div>
        <Chart name="kalorien" height={260} csv={n.days} option={{
          legend: {}, dataZoom: zoom,
          xAxis: { type: 'category', data: n.days.map((x) => dd(x.day)) },
          yAxis: { type: 'value' },
          series: [
            { name: 'Gegessen', type: 'bar', data: n.days.map((x) => energy(x.kcal || 0)), itemStyle: { borderRadius: 4, color: '#f59e0b' } },
            { name: 'Ziel', type: 'line', step: 'middle', showSymbol: false, data: n.days.map((x) => energy(x.target_kcal)), lineStyle: { type: 'dashed' }, color: cv('--muted') },
            { name: 'Wochenmittel', type: 'line', smooth: true, showSymbol: false, color: accent(), data: n.days.map((x) => { const w = n.weekly.find((wk) => new Date(x.day) >= new Date(wk.week) && new Date(x.day) < new Date(addDays(wk.week, 7))); return w ? energy(w.kcal) : null; }) }
          ]
        }} />
      </div>
      <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <div class="card">
          <div class="mb-2 text-sm font-semibold">Makro-Verteilung (Ø)</div>
          <Chart name="makros" height={220} option={{
            tooltip: { trigger: 'item', formatter: '{b}: {d} %' },
            series: [{ type: 'pie', radius: ['50%', '78%'], itemStyle: { borderRadius: 8, borderColor: cv('--surface'), borderWidth: 3 }, label: { formatter: '{b}\n{d} %', color: cv('--text') },
              data: [{ name: 'Protein', value: n.average.protein * 4, itemStyle: { color: cv('--protein') } }, { name: 'Kohlenhydrate', value: n.average.carbs * 4, itemStyle: { color: cv('--carbs') } }, { name: 'Fett', value: n.average.fat * 9, itemStyle: { color: cv('--fat') } }] }]
          }} csv={[n.distribution_pct]} />
        </div>
        <div class="card">
          <div class="mb-2 text-sm font-semibold">Protein pro Tag</div>
          <Chart name="protein" height={220} option={{
            xAxis: { type: 'category', data: n.days.map((x) => dd(x.day)) }, yAxis: { type: 'value' }, dataZoom: zoom,
            series: [{ name: 'Protein', type: 'bar', data: n.days.map((x) => ({ value: x.protein || 0, itemStyle: { color: (x.protein || 0) >= x.target_protein * 0.95 ? cv('--protein') : cv('--muted') } })), itemStyle: { borderRadius: 4 } },
              { name: 'Ziel', type: 'line', step: 'middle', showSymbol: false, data: n.days.map((x) => x.target_protein), lineStyle: { type: 'dashed' } }]
          }} />
        </div>
      </div>
      {#if Object.keys(n.micros_avg).length}
        <div class="card">
          <div class="mb-2 text-sm font-semibold">Mikronährstoffe (Ø pro Tag, soweit erfasst)</div>
          <div class="grid grid-cols-2 gap-2 text-sm">
            {#each Object.entries(n.micros_avg) as [k, v]}<div class="flex justify-between rounded-xl bg-surface-2 px-3 py-2"><span>{k.replace(/_(mg|ug)$/, '').replace(/_/g, ' ')}</span><span class="tabular-nums">{fmtNum(v, 1)} {k.endsWith('_ug') ? 'µg' : 'mg'}</span></div>{/each}
          </div>
        </div>
      {/if}
      <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
        {#each [['top_protein', 'Top Proteinquellen', 'protein', 'g'], ['top_kcal', 'Top Kalorienquellen', 'kcal', 'kcal']] as [key, title, f, unit]}
          <div class="card p-0"><div class="px-4 pt-3 text-sm font-semibold">{title}</div>
            {#each n[key].slice(0, 8) as item}<div class="list-row text-sm"><span class="flex-1 truncate">{item.name}</span><span class="tabular-nums text-muted">{fmtNum(item[f], 0)} {unit}</span></div>{/each}
          </div>
        {/each}
      </div>
    {/if}

  {:else if tab === 'body'}
    <div class="card">
      <div class="mb-2 flex justify-between text-sm font-semibold"><span>Gewicht & 7-Tage-Mittel</span><a href="/progress/body" class="text-accent">Details</a></div>
      {#if d.weight?.length}
        <Chart name="gewicht" height={260} csv={d.weight} option={{
          legend: {}, dataZoom: zoom,
          xAxis: { type: 'category', data: d.weight.map((p) => dd(p.day)) },
          yAxis: { type: 'value', scale: true, name: weightUnit() },
          series: [
            { name: 'Messung', type: 'scatter', symbolSize: 6, color: cv('--muted'), data: d.weight.map((p) => toDisplayWeight(p.value)) },
            { name: '7-Tage-Mittel', type: 'line', smooth: true, showSymbol: false, lineStyle: { width: 3 }, color: accent(), data: d.weight.map((p) => toDisplayWeight(p.avg)) },
            ...(period.compare && cmp.weight?.length ? [{ name: 'Vergleich (Mittel)', type: 'line', smooth: true, showSymbol: false, lineStyle: { type: 'dashed' }, color: '#3b82f6', data: cmp.weight.map((p) => toDisplayWeight(p.avg)) }] : [])
          ]
        }} />
      {:else}<p class="text-sm text-muted">Keine Gewichtsdaten im Zeitraum. <a class="text-accent" href="/progress/body?add=1">Jetzt eintragen</a></p>{/if}
    </div>
    {#if d.body?.entries?.some((e) => e.waist_cm || e.chest_cm || e.arm_cm)}
      {@const es = [...d.body.entries].reverse()}
      <div class="card"><div class="mb-2 text-sm font-semibold">Umfänge</div>
        <Chart name="umfaenge" height={240} option={{
          legend: {}, xAxis: { type: 'category', data: es.map((e) => dd(e.day)) }, yAxis: { type: 'value', scale: true, name: 'cm' },
          series: [['waist_cm', 'Taille'], ['chest_cm', 'Brust'], ['hips_cm', 'Hüfte'], ['arm_cm', 'Arm'], ['thigh_cm', 'Oberschenkel']].map(([k, l], i) => ({ name: l, type: 'line', connectNulls: true, smooth: true, color: PALETTE[i], data: es.map((e) => e[k]) }))
        }} />
      </div>
    {/if}
    <a href="/progress/body" class="btn-soft w-full"><Icon name="image" size={18} /> Messungen & Fotos</a>

  {:else if tab === 'metrics'}
    {#if !d.metrics}<Skeleton />{:else if !d.metrics.length}
      <div class="card text-center text-sm text-muted">Noch keine eigenen Metriken. <a href="/progress/metrics" class="text-accent">Metrik anlegen</a></div>
    {:else}
      {#each d.metrics as m, i}
        <div class="card"><div class="mb-2 flex justify-between text-sm font-semibold"><span>{m.name}{m.unit ? ` (${m.unit})` : ''}</span>
          {#if m.target}<span class="text-muted">Ziel {m.target}</span>{/if}</div>
          <Chart name={m.name} height={200} csv={m.entries.map((e) => ({ day: e.day, value: e.value_num }))} option={{
            xAxis: { type: 'category', data: m.entries.map((e) => dd(e.day)) }, yAxis: { type: 'value', scale: m.kind !== 'bool', max: m.kind === 'bool' ? 1 : undefined },
            series: [{ name: m.name, type: m.chart === 'bar' || m.kind === 'bool' ? 'bar' : 'line', smooth: true, color: m.color || PALETTE[i % PALETTE.length], data: m.entries.map((e) => e.value_num), itemStyle: { borderRadius: 4 },
              markLine: m.target ? { symbol: 'none', data: [{ yAxis: m.target }], lineStyle: { type: 'dashed' } } : undefined }]
          }} />
        </div>
      {/each}
    {/if}
    <a href="/progress/metrics" class="btn-soft w-full"><Icon name="settings" size={18} /> Metriken verwalten & erfassen</a>

  {:else if tab === 'corr'}
    {#if !d.corr}<Skeleton lines={2} h="h-64" />{:else}
      {@const w = d.corr.weekly}
      <div class="card">
        <div class="mb-1 text-sm font-semibold">Gewichtstrend vs. Kalorienbilanz</div>
        <p class="mb-2 text-xs text-muted">Bilanz = Ø Aufnahme − geschätzter Bedarf ({d.corr.tdee} kcal). {d.corr.r_balance_weight != null ? `Korrelation r = ${d.corr.r_balance_weight}` : 'Für eine Korrelation werden mind. 3 Wochen mit Daten benötigt.'}</p>
        <Chart name="korrelation-gewicht" height={250} csv={w} option={{
          legend: {}, xAxis: { type: 'category', data: w.map((x) => dd(x.week)) },
          yAxis: [{ type: 'value', name: 'kcal/Tag' }, { type: 'value', name: `Δ ${weightUnit()}`, splitLine: { show: false } }],
          series: [
            { name: 'Kalorienbilanz', type: 'bar', data: w.map((x) => x.kcal_balance), itemStyle: { borderRadius: 4, color: cv('--carbs') } },
            { name: 'Gewichtsänderung', type: 'line', yAxisIndex: 1, smooth: true, connectNulls: true, color: accent(), data: w.map((x) => (x.weight_change == null ? null : toDisplayWeight(x.weight_change))) }
          ]
        }} />
      </div>
      <div class="card">
        <div class="mb-1 text-sm font-semibold">Kraftentwicklung vs. Protein</div>
        <p class="mb-2 text-xs text-muted">Kraftindex = Ø der besten 1RM-Werte relativ zur ersten Woche (=100). {d.corr.r_protein_strength != null ? `r = ${d.corr.r_protein_strength}` : ''}</p>
        <Chart name="korrelation-kraft" height={250} option={{
          legend: {}, xAxis: { type: 'category', data: w.map((x) => dd(x.week)) },
          yAxis: [{ type: 'value', name: 'Protein g', scale: true }, { type: 'value', name: 'Index', scale: true, splitLine: { show: false } }],
          series: [
            { name: 'Ø Protein', type: 'bar', data: w.map((x) => x.protein_avg), itemStyle: { borderRadius: 4, color: cv('--protein') } },
            { name: 'Kraftindex', type: 'line', yAxisIndex: 1, smooth: true, connectNulls: true, color: accent(), data: w.map((x) => x.strength_index) }
          ]
        }} />
      </div>
    {/if}
  {/if}
</div>

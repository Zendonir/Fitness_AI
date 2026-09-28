<script>
  import { onMount } from 'svelte';
  import { page } from '$app/state';
  import { goto } from '$app/navigation';
  import { api } from '$lib/api.js';
  import { toast, toastError } from '$lib/toast.svelte.js';
  import { EQUIPMENT, MUSCLES, fmtDate, fmtWeight, toDisplayWeight, weightUnit, fmtNum } from '$lib/units.js';
  import { accent, cv } from '$lib/colors.js';
  import Chart from '$components/Chart.svelte';
  import Header from '$components/Header.svelte';
  import Icon from '$components/Icon.svelte';
  import MuscleMap from '$components/MuscleMap.svelte';
  import Sheet from '$components/Sheet.svelte';
  import ShareSheet from '$components/ShareSheet.svelte';
  import Skeleton from '$components/Skeleton.svelte';
  import ExerciseMedia from '$components/ExerciseMedia.svelte';
  import MediaLibrary from '$components/MediaLibrary.svelte';
  import { mediaEnabled } from '$lib/media.js';

  let ex = $state(null), stats = $state(null), days = $state(365);
  let editOpen = $state(false), shareOpen = $state(false), libOpen = $state(false);
  let newField = $state({ label: '', type: 'text' });

  onMount(async () => {
    ex = await api.get(`/api/exercises/${page.params.id}`);
  });
  $effect(() => { const d = days; api.get(`/api/stats/exercise/${page.params.id}?days=${d}`).then((s) => (stats = s)).catch(() => {}); });

  const muscleValues = $derived(ex ? Object.fromEntries([...ex.primary_muscles.map((m) => [m, 12]), ...ex.secondary_muscles.map((m) => [m, 5])]) : {});
  const chartOpt = $derived(stats?.sessions?.length ? {
    legend: {},
    dataZoom: [{ type: 'inside' }],
    xAxis: { type: 'category', data: stats.sessions.map((s) => fmtDate(s.day, { day: '2-digit', month: '2-digit', year: '2-digit' })) },
    yAxis: [{ type: 'value', scale: true, name: weightUnit() }, { type: 'value', name: 'Volumen', splitLine: { show: false } }],
    series: [
      { name: 'Geschätztes 1RM', type: 'line', smooth: true, color: accent(), data: stats.sessions.map((s) => ({ value: toDisplayWeight(s.e1rm), symbolSize: s.pr ? 12 : 5,
        itemStyle: s.pr ? { color: '#f59e0b' } : undefined })),
        markPoint: { symbol: 'pin', symbolSize: 36, data: stats.sessions.map((s, i) => s.pr ? { coord: [i, toDisplayWeight(s.e1rm)], value: 'PR' } : null).filter(Boolean) } },
      { name: 'Top-Gewicht', type: 'line', smooth: true, color: '#3b82f6', data: stats.sessions.map((s) => toDisplayWeight(s.top_weight)) },
      { name: 'Volumen', type: 'bar', yAxisIndex: 1, color: cv('--muted'), itemStyle: { opacity: 0.35, borderRadius: 4 }, data: stats.sessions.map((s) => Math.round(toDisplayWeight(s.volume_kg))) }
    ]
  } : null);

  async function saveEdit() {
    try {
      ex = await api.patch(`/api/exercises/${ex.id}`, ex);
      ex.own = true;
      editOpen = false;
      toast('Gespeichert', 'success');
    } catch (e) { toastError(e); }
  }
  function addField() {
    if (!newField.label) return;
    ex.custom_fields = [...(ex.custom_fields || []), { key: newField.label.toLowerCase().replace(/\W+/g, '_'), label: newField.label, type: newField.type }];
    newField = { label: '', type: 'text' };
  }
  async function del() {
    if (!confirm('Übung löschen?')) return;
    try { await api.del(`/api/exercises/${ex.id}`); goto('/training/exercises'); } catch (e) { toastError(e); }
  }
</script>

<Header title={ex?.name || 'Übung'} back="/training/exercises">
  {#snippet actions()}
    {#if ex?.own}
      <button class="p-2 text-muted" onclick={() => (shareOpen = true)} aria-label="Teilen"><Icon name="share" /></button>
    {/if}
    {#if ex}<button class="p-2 text-accent" onclick={() => (editOpen = true)} aria-label="Einstellungen"><Icon name="settings" /></button>{/if}
  {/snippet}
</Header>

<div class="space-y-3 px-4">
  {#if !ex}<Skeleton lines={3} h="h-40" />{:else}
    {#if ex.media_id && mediaEnabled()}
      <div class="card overflow-hidden p-0">
        <ExerciseMedia id={ex.media_id} name={ex.name} size="full" class="aspect-square max-h-80 w-full" />
      </div>
    {/if}
    <div class="card flex items-center gap-4">
      <MuscleMap values={muscleValues} size={48} />
      <div class="text-sm">
        <div><span class="text-muted">Haupt:</span> {ex.primary_muscles.map((m) => MUSCLES[m]).join(', ')}</div>
        {#if ex.secondary_muscles.length}<div><span class="text-muted">Hilfs:</span> {ex.secondary_muscles.map((m) => MUSCLES[m]).join(', ')}</div>{/if}
        <div><span class="text-muted">Equipment:</span> {EQUIPMENT[ex.equipment]}</div>
        <div><span class="text-muted">Progression:</span> {ex.progression?.rep_min}–{ex.progression?.rep_max} Wdh., +{ex.progression?.increment_kg} kg</div>
      </div>
    </div>
    {#if ex.instructions}<div class="card text-sm"><Icon name="info" size={16} class="mr-1 inline text-accent" />{ex.instructions}</div>{/if}

    <div class="no-scrollbar flex gap-1.5 overflow-x-auto">
      {#each [[90, '3 M'], [180, '6 M'], [365, '1 J'], [1825, 'Alles']] as [d, l]}<button class={days === d ? 'chip-active' : 'chip'} onclick={() => (days = d)}>{l}</button>{/each}
    </div>
    {#if stats}
      <div class="grid grid-cols-3 gap-2 text-center">
        <div class="card p-3"><div class="text-xs text-muted">Bestes 1RM</div><div class="font-bold">{stats.best_e1rm ? fmtWeight(stats.best_e1rm) : '–'}</div></div>
        <div class="card p-3"><div class="text-xs text-muted">Einheiten</div><div class="font-bold">{stats.total_sessions}</div></div>
        <div class="card p-3"><div class="text-xs text-muted">Zuletzt</div><div class="font-bold">{stats.sessions.at(-1) ? fmtDate(stats.sessions.at(-1).day, { day: '2-digit', month: '2-digit' }) : '–'}</div></div>
      </div>
      {#if chartOpt}
        <div class="card"><div class="mb-2 text-sm font-semibold">1RM-Verlauf (Epley) & Volumen</div><Chart option={chartOpt} height={280} name="1rm-{ex.name}" /></div>
      {/if}
      {#if stats.rep_records.length}
        <div class="card"><div class="mb-2 text-sm font-semibold"><Icon name="trophy" size={16} class="inline text-warn" /> Beste Sätze</div>
          <div class="grid grid-cols-4 gap-2 text-center text-sm">
            {#each stats.rep_records as r}<div class="rounded-xl bg-surface-2 p-2"><div class="text-xs text-muted">{r.reps} Wdh.</div><div class="font-bold">{fmtNum(toDisplayWeight(r.weight_kg))}</div></div>{/each}
          </div>
        </div>
      {/if}
      <div class="card p-0">
        {#each [...stats.sessions].reverse().slice(0, 20) as s}
          <a href="/training/history/{s.workout_id}" class="list-row text-sm">
            <span class="w-20 text-muted">{fmtDate(s.day)}</span>
            <span class="flex-1">{s.sets} Sätze · best {s.best_set?.reps}×{fmtWeight(s.best_set?.weight_kg)}</span>
            {#if s.pr}<span class="chip-active py-0.5 text-xs">PR</span>{/if}
          </a>
        {/each}
      </div>
    {/if}
  {/if}
</div>

<Sheet bind:open={editOpen} title="Übung anpassen" full>
  {#if ex}
    <div class="space-y-3">
      {#if ex.own}
        <input class="input" bind:value={ex.name} />
        <textarea class="input" rows="2" bind:value={ex.instructions}></textarea>
        {#if mediaEnabled()}
          <div class="flex items-center gap-3">
            <ExerciseMedia id={ex.media_id} name={ex.name} class="h-16 w-16 rounded-xl" />
            <button class="btn-soft btn-sm" onclick={() => (libOpen = true)}><Icon name="image" size={16} /> {ex.media_id ? 'Animation ändern' : 'Animation wählen'}</button>
            {#if ex.media_id}<button class="btn-ghost btn-sm text-danger" onclick={() => (ex.media_id = null)}>Entfernen</button>{/if}
          </div>
        {/if}
      {:else}
        <p class="text-sm text-muted">Globale Übung – Progressionsregel und eigene Felder gelten nur für Kopien. Erstelle bei Bedarf eine eigene Übung.</p>
      {/if}
      <p class="section-title">Progression (Double Progression)</p>
      <div class="grid grid-cols-3 gap-2">
        <label><span class="label">Wdh. min</span><input class="input" type="number" bind:value={ex.progression.rep_min} /></label>
        <label><span class="label">Wdh. max</span><input class="input" type="number" bind:value={ex.progression.rep_max} /></label>
        <label><span class="label">+ kg</span><input class="input" type="number" step="0.25" bind:value={ex.progression.increment_kg} /></label>
      </div>
      <label class="flex items-center gap-2 text-sm"><input type="checkbox" class="h-5 w-5 accent-[var(--accent)]" bind:checked={ex.progression.all_sets} /> Alle Sätze müssen das Maximum erreichen</label>
      <p class="section-title">Eigene Satzfelder</p>
      {#each ex.custom_fields || [] as f, i}
        <div class="flex items-center justify-between rounded-xl bg-surface-2 px-3 py-2 text-sm">{f.label}
          <button class="text-danger" onclick={() => (ex.custom_fields = ex.custom_fields.filter((_, j) => j !== i))}><Icon name="x" size={16} /></button></div>
      {/each}
      <div class="flex gap-2"><input class="input" placeholder="z. B. Tempo, Griffart, Band" bind:value={newField.label} /><button class="btn-soft" onclick={addField}><Icon name="plus" /></button></div>
      {#if ex.own}
        <button class="btn-primary w-full" onclick={saveEdit}>Speichern</button>
        <button class="btn-ghost w-full text-danger" onclick={del}>Übung löschen</button>
      {:else}
        <button class="btn-primary w-full" onclick={async () => { const c = await api.post('/api/exercises', { ...ex, name: ex.name + ' (eigene)' }); goto(`/training/exercises/${c.id}`).then(() => location.reload()); }}>Als eigene Übung speichern</button>
      {/if}
    </div>
  {/if}
</Sheet>
{#if ex?.own}<ShareSheet bind:open={shareOpen} type="exercise" id={ex.id} />{/if}
<MediaLibrary bind:open={libOpen} title="Animation wählen" onpick={(e) => (ex.media_id = e.id)} />

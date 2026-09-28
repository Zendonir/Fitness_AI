<script>
  import { onMount } from 'svelte';
  import Sortable from 'sortablejs';
  import { api } from '$lib/api.js';
  import { session } from '$lib/session.svelte.js';
  import { toast, toastError } from '$lib/toast.svelte.js';
  import { fmtDate, today } from '$lib/units.js';
  import Header from '$components/Header.svelte';
  import Icon from '$components/Icon.svelte';
  import Sheet from '$components/Sheet.svelte';
  import Skeleton from '$components/Skeleton.svelte';
  import Widget from '$components/Widget.svelte';

  const TYPES = {
    macros: 'Makro-Ringe', workout_today: 'Heutiges Training', coach_hint: 'Coach-Hinweis', water: 'Wasser', streak: 'Streak',
    weight_trend: 'Gewichtstrend', muscle_heatmap: 'Muskel-Heatmap', calendar: 'Trainingskalender', weekly_volume: 'Wochenvolumen',
    kcal_trend: 'Kalorien vs. Ziel', exercise_1rm: '1RM einer Übung', metric: 'Eigene Metrik', body_stats: 'Körperwerte', quick_add: 'Schnellzugriff'
  };

  let dashboards = $state([]);
  let active = $state(0);
  let data = $state(null);
  let editing = $state(false);
  let addOpen = $state(false);
  let configW = $state(null);
  let grid = $state();
  let exercises = $state([]);
  let metrics = $state([]);
  let sortable;

  const dash = $derived(dashboards[active]);

  async function load() {
    try { data = await api.get('/api/stats/today'); } catch (e) { toastError(e); }
  }
  onMount(async () => {
    dashboards = await api.get('/api/dashboards');
    try { active = Math.min(Number(localStorage.getItem('ff_dash') || 0), dashboards.length - 1); } catch {}
    load();
  });

  $effect(() => {
    if (editing && grid) {
      sortable = Sortable.create(grid, {
        animation: 180, handle: '.drag', delay: 80, delayOnTouchOnly: true,
        onEnd: (e) => {
          if (e.oldIndex === e.newIndex) return;
          e.item.remove();
          e.from.insertBefore(e.item, e.from.children[e.oldIndex] ?? null);
          const w = [...dash.widgets];
          const [m] = w.splice(e.oldIndex, 1);
          w.splice(e.newIndex, 0, m);
          dashboards[active].widgets = w;
        }
      });
      return () => sortable?.destroy();
    }
  });

  async function save() {
    try {
      dashboards[active] = await api.put(`/api/dashboards/${dash.id}`, dash);
      editing = false;
      toast('Dashboard gespeichert', 'success');
    } catch (e) { toastError(e); }
  }
  function addWidget(type) {
    dashboards[active].widgets = [...dash.widgets, { id: type + Date.now(), type, w: 2, h: 1, visible: true, config: {} }];
    addOpen = false;
  }
  async function newDashboard() {
    const name = prompt('Name des neuen Dashboards', 'Kraft');
    if (!name) return;
    const d = await api.post('/api/dashboards', { name, position: dashboards.length, widgets: [{ id: 'q', type: 'quick_add', w: 2, h: 1, visible: true, config: {} }] });
    dashboards = [...dashboards, d];
    active = dashboards.length - 1;
    editing = true;
  }
  async function deleteDashboard() {
    if (dashboards.length < 2 || !confirm(`Dashboard „${dash.name}“ löschen?`)) return;
    await api.del(`/api/dashboards/${dash.id}`);
    dashboards = dashboards.filter((d) => d.id !== dash.id);
    active = 0;
    editing = false;
  }
  function selectDash(i) {
    active = i;
    try { localStorage.setItem('ff_dash', String(i)); } catch {}
  }
  async function openConfig(w) {
    configW = w;
    if (w.type === 'exercise_1rm' && !exercises.length) exercises = await api.get('/api/exercises');
    if (w.type === 'metric' && !metrics.length) metrics = await api.get('/api/metrics');
  }
  const greeting = () => {
    const h = new Date().getHours();
    return h < 11 ? 'Guten Morgen' : h < 18 ? 'Hallo' : 'Guten Abend';
  };
</script>

<Header title={`${greeting()}, ${session.user?.display_name?.split(' ')[0] || ''}`} subtitle={fmtDate(today(), { weekday: 'long', day: 'numeric', month: 'long' })}>
  {#snippet actions()}
    {#if editing}
      <button class="btn-primary btn-sm" onclick={save}>Fertig</button>
    {:else}
      <button class="rounded-full p-2 text-muted" onclick={() => (editing = true)} aria-label="Dashboard bearbeiten"><Icon name="grid" /></button>
      <a class="rounded-full p-2 text-muted" href="/profile" aria-label="Profil"><Icon name="user" /></a>
    {/if}
  {/snippet}
</Header>

<div class="px-4">
  {#if dashboards.length > 1 || editing}
    <div class="no-scrollbar mb-3 flex gap-1.5 overflow-x-auto">
      {#each dashboards as d, i}
        <button class={i === active ? 'chip-active' : 'chip'} onclick={() => selectDash(i)}>{d.name}</button>
      {/each}
      {#if editing}<button class="chip" onclick={newDashboard}><Icon name="plus" size={14} /> Neu</button>{/if}
    </div>
  {/if}

  {#if !data || !dash}
    <Skeleton lines={4} h="h-32" />
  {:else}
    <div bind:this={grid} class="grid grid-cols-2 gap-3">
      {#each dash.widgets as w (w.id)}
        {#if w.visible || editing}
          <div class="relative {w.w >= 2 ? 'col-span-2' : ''} {!w.visible ? 'opacity-40' : ''}">
            {#if editing}
              <div class="absolute -top-2 right-1 z-10 flex gap-1">
                <span class="drag cursor-grab rounded-full bg-fg p-1.5 text-bg"><Icon name="drag" size={14} /></span>
                <button class="rounded-full bg-fg p-1.5 text-bg" onclick={() => (w.w = w.w >= 2 ? 1 : 2)} aria-label="Größe"><Icon name="grid" size={14} /></button>
                <button class="rounded-full bg-fg p-1.5 text-bg" onclick={() => (w.visible = !w.visible)} aria-label="Sichtbarkeit"><Icon name="eye" size={14} /></button>
                {#if ['muscle_heatmap', 'exercise_1rm', 'metric'].includes(w.type)}
                  <button class="rounded-full bg-fg p-1.5 text-bg" onclick={() => openConfig(w)} aria-label="Einstellungen"><Icon name="settings" size={14} /></button>
                {/if}
                <button class="rounded-full bg-danger p-1.5 text-white" onclick={() => (dashboards[active].widgets = dash.widgets.filter((x) => x.id !== w.id))} aria-label="Entfernen"><Icon name="x" size={14} /></button>
              </div>
            {/if}
            <Widget widget={w} {data} reload={load} />
          </div>
        {/if}
      {/each}
    </div>
    {#if editing}
      <div class="mt-4 flex gap-2">
        <button class="btn-soft flex-1" onclick={() => (addOpen = true)}><Icon name="plus" /> Widget</button>
        {#if dashboards.length > 1}<button class="btn-soft text-danger" onclick={deleteDashboard}><Icon name="trash" /></button>{/if}
      </div>
    {/if}
  {/if}
</div>

<Sheet bind:open={addOpen} title="Widget hinzufügen">
  <div class="grid grid-cols-2 gap-2">
    {#each Object.entries(TYPES) as [t, l]}
      <button class="btn-soft h-auto py-3 text-sm" onclick={() => addWidget(t)}>{l}</button>
    {/each}
  </div>
</Sheet>

<Sheet open={!!configW} title="Widget einstellen" onclose={() => (configW = null)}>
  {#if configW}
    {#if configW.type === 'muscle_heatmap'}
      <div class="flex gap-2">
        {#each [7, 14, 30] as d}<button class={configW.config.days === d ? 'chip-active' : 'chip'} onclick={() => (configW.config = { ...configW.config, days: d })}>{d} Tage</button>{/each}
      </div>
    {:else if configW.type === 'exercise_1rm'}
      <select class="input" value={configW.config.exercise_id} onchange={(e) => (configW.config = { ...configW.config, exercise_id: Number(e.currentTarget.value) })}>
        <option value="">Übung wählen</option>
        {#each exercises as e}<option value={e.id}>{e.name}</option>{/each}
      </select>
    {:else if configW.type === 'metric'}
      <select class="input" value={configW.config.metric_id} onchange={(e) => { const m = metrics.find((x) => x.id == e.currentTarget.value); configW.config = { ...configW.config, metric_id: m?.id, title: m?.name }; }}>
        <option value="">Metrik wählen</option>
        {#each metrics as m}<option value={m.id}>{m.name}</option>{/each}
      </select>
    {/if}
    <button class="btn-primary mt-4 w-full" onclick={() => (configW = null)}>Übernehmen</button>
  {/if}
</Sheet>

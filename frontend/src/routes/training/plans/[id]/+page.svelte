<script>
  import { onMount, tick } from 'svelte';
  import { goto } from '$app/navigation';
  import { page } from '$app/state';
  import Sortable from 'sortablejs';
  import { api } from '$lib/api.js';
  import { isAdmin, session } from '$lib/session.svelte.js';
  import { toast, toastError } from '$lib/toast.svelte.js';
  import { MUSCLES } from '$lib/units.js';
  import Header from '$components/Header.svelte';
  import Icon from '$components/Icon.svelte';
  import Sheet from '$components/Sheet.svelte';
  import Skeleton from '$components/Skeleton.svelte';
  import ShareSheet from '$components/ShareSheet.svelte';
  import ActionCard from '$components/ActionCard.svelte';
  import { md } from '$lib/markdown.js';

  let plan = $state(null);
  let edit = $state(page.url.searchParams.get('edit') === '1');
  let picker = $state({ open: false, day: 0 });
  let exercises = $state([]);
  let q = $state('');
  let shareOpen = $state(false);
  const WD = ['Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So'];

  let proposals = $state([]);
  let coach = $state({ open: false, request: '', busy: false, text: '', actions: [] });
  const IDEAS = ['Ich habe nur noch 3 Tage pro Woche', 'Max. 45 Minuten pro Einheit', 'Mehr Fokus auf Arme und Schultern',
    'Mein Knie schonen', 'Nur Kurzhanteln zu Hause', 'Deload-Woche einplanen', 'Analysiere meinen Fortschritt und optimiere'];

  async function load() {
    plan = await api.get(`/api/plans/${page.params.id}`);
    if (plan.own) proposals = await api.get(`/api/coach/actions?plan_id=${plan.id}`).catch(() => []);
  }
  onMount(load);

  async function askCoach() {
    coach.busy = true; coach.text = ''; coach.actions = [];
    try {
      const r = await api.post('/api/coach/plan-review', { plan_id: plan.id, request: coach.request });
      coach.text = r.text; coach.actions = r.actions;
      if (!r.actions.length) toast('Der Coach hat keine Änderung vorgeschlagen');
    } catch (e) { toastError(e); } finally { coach.busy = false; }
  }
  async function resolved(status) {
    if (status === 'confirmed') { coach.open = false; await load(); }
    else proposals = await api.get(`/api/coach/actions?plan_id=${plan.id}`).catch(() => []);
  }

  function bindSortable(node, { list, onmove }) {
    const s = Sortable.create(node, { animation: 180, handle: '.drag', delay: 60, delayOnTouchOnly: true,
      onEnd: (e) => {
        if (e.oldIndex === e.newIndex) return;
        // DOM-Änderung von Sortable rückgängig machen – Svelte rendert anhand des States neu
        e.item.remove();
        e.from.insertBefore(e.item, e.from.children[e.oldIndex] ?? null);
        onmove(e.oldIndex, e.newIndex);
      } });
    return { destroy: () => s.destroy() };
  }
  function move(arr, from, to) { const a = [...arr]; const [m] = a.splice(from, 1); a.splice(to, 0, m); return a; }

  async function save() {
    try {
      const body = { name: plan.name, description: plan.description, weeks: Number(plan.weeks), deload_weeks: plan.deload_weeks, deload_factor: Number(plan.deload_factor),
        days: plan.days.map((d) => ({ name: d.name, weekday: d.weekday === '' || d.weekday === null ? null : Number(d.weekday), notes: d.notes || '',
          exercises: d.exercises.map((e) => ({ exercise_id: e.exercise_id, sets: Number(e.sets), rep_min: Number(e.rep_min), rep_max: Number(e.rep_max),
            target_rpe: e.target_rpe === '' ? null : e.target_rpe, rest_seconds: Number(e.rest_seconds), superset_group: e.superset_group || null, notes: e.notes || '' })) })) };
      plan = await api.put(`/api/plans/${plan.id}`, body);
      edit = false;
      toast('Plan gespeichert', 'success');
    } catch (e) { toastError(e); }
  }
  async function activate() {
    try {
      const p = await api.post(`/api/plans/${plan.id}/activate`);
      toast(p.id !== plan.id ? 'Kopie erstellt und aktiviert' : 'Plan aktiviert', 'success');
      goto(`/training/plans/${p.id}`, { replaceState: true }).then(async () => (plan = await api.get(`/api/plans/${p.id}`)));
    } catch (e) { toastError(e); }
  }
  async function copy() {
    const p = await api.post(`/api/plans/${plan.id}/copy`);
    goto(`/training/plans/${p.id}?edit=1`).then(async () => { plan = await api.get(`/api/plans/${p.id}`); edit = true; });
  }
  async function del() {
    if (!confirm('Plan löschen?')) return;
    await api.del(`/api/plans/${plan.id}`);
    goto('/training/plans', { replaceState: true });
  }
  async function makeGlobal() {
    await api.post(`/api/admin/templates/plan/${plan.id}`);
    toast('Als globale Vorlage gespeichert', 'success');
  }
  async function openPicker(day) {
    picker = { open: true, day };
    if (!exercises.length) exercises = await api.get('/api/exercises');
  }
  function addEx(e) {
    plan.days[picker.day].exercises = [...plan.days[picker.day].exercises, { exercise_id: e.id, exercise: e, sets: 3,
      rep_min: e.progression?.rep_min || 8, rep_max: e.progression?.rep_max || 12, target_rpe: 8, rest_seconds: 120, superset_group: null }];
    picker.open = false;
  }
  const filtered = $derived(exercises.filter((e) => e.name.toLowerCase().includes(q.toLowerCase())));
  function toggleDeload(w) {
    plan.deload_weeks = plan.deload_weeks.includes(w) ? plan.deload_weeks.filter((x) => x !== w) : [...plan.deload_weeks, w].sort((a, b) => a - b);
  }
</script>

<Header title={plan?.name || 'Plan'} back="/training/plans">
  {#snippet actions()}
    {#if plan?.own}
      {#if edit}<button class="btn-primary btn-sm" onclick={save}>Speichern</button>
      {:else}
        <button class="p-2 text-muted" onclick={() => (shareOpen = true)} aria-label="Teilen"><Icon name="share" /></button>
        <button class="p-2 text-accent" onclick={() => (edit = true)} aria-label="Bearbeiten"><Icon name="edit" /></button>
      {/if}
    {/if}
  {/snippet}
</Header>

<div class="space-y-3 px-4">
  {#if !plan}<Skeleton lines={4} />{:else}
    {#if edit}
      <div class="card space-y-3">
        <input class="input text-lg font-semibold" bind:value={plan.name} />
        <textarea class="input" rows="2" placeholder="Beschreibung" bind:value={plan.description}></textarea>
        <div class="grid grid-cols-2 gap-2">
          <label><span class="label">Wochen pro Block</span><input class="input" type="number" min="1" max="52" bind:value={plan.weeks} /></label>
          <label><span class="label">Deload-Volumen</span><select class="input" bind:value={plan.deload_factor}>
            {#each [0.4, 0.5, 0.6, 0.7] as f}<option value={f}>{Math.round(f * 100)} %</option>{/each}</select></label>
        </div>
        <div><span class="label">Deload-Wochen</span>
          <div class="flex flex-wrap gap-1">{#each Array(Number(plan.weeks) || 1) as _, i}
            <button class={plan.deload_weeks.includes(i + 1) ? 'chip-active' : 'chip'} onclick={() => toggleDeload(i + 1)}>W{i + 1}</button>{/each}</div>
        </div>
      </div>
    {:else}
      {#if plan.description}<p class="text-sm text-muted">{plan.description}</p>{/if}
      <div class="flex gap-2">
        {#if !plan.is_active}<button class="btn-primary flex-1" onclick={activate}><Icon name="play" size={18} /> Aktivieren</button>
        {:else}<span class="btn-soft flex-1 text-accent"><Icon name="check" size={18} /> Aktiver Plan</span>{/if}
        <button class="btn-soft" onclick={copy} aria-label="Kopieren"><Icon name="copy" /></button>
        {#if plan.own}<button class="btn-soft text-danger" onclick={del} aria-label="Löschen"><Icon name="trash" /></button>{/if}
      </div>
      {#if plan.own}
        <button class="btn-soft w-full border border-accent/40 text-accent" onclick={() => (coach = { ...coach, open: true })}><Icon name="sparkles" size={18} /> Mit Coach bearbeiten</button>
      {:else}
        <p class="text-xs text-muted">Zum Bearbeiten (auch mit dem Coach) zuerst aktivieren oder kopieren – so entsteht deine eigene Version.</p>
      {/if}
      {#each proposals as a (a.id)}
        <div><p class="section-title mt-2">Vorschlag vom Coach</p><ActionCard action={a} onresolved={resolved} /></div>
      {/each}
      {#if isAdmin() && plan.own}<button class="btn-ghost btn-sm text-muted" onclick={makeGlobal}>Als globale Vorlage bereitstellen</button>{/if}
    {/if}

    <div class="space-y-3" use:bindSortable={{ list: plan.days, onmove: (a, b) => (plan.days = move(plan.days, a, b)) }}>
      {#each plan.days as day, di (day.id ?? di)}
        <div class="card">
          <div class="mb-2 flex items-center gap-2">
            {#if edit}
              <span class="drag cursor-grab text-muted"><Icon name="drag" /></span>
              <input class="input flex-1 py-2 font-semibold" bind:value={day.name} />
              <select class="input w-20 py-2" bind:value={day.weekday}>
                <option value={null}>–</option>{#each WD as d, i}<option value={i}>{d}</option>{/each}
              </select>
              <button class="p-1 text-danger" onclick={() => (plan.days = plan.days.filter((_, i) => i !== di))} aria-label="Tag löschen"><Icon name="trash" size={18} /></button>
            {:else}
              <h3 class="flex-1 font-semibold">{day.name}</h3>{#if day.weekday !== null}<span class="chip text-xs">{WD[day.weekday]}</span>{/if}
            {/if}
          </div>
          <div use:bindSortable={{ list: day.exercises, onmove: (a, b) => (day.exercises = move(day.exercises, a, b)) }}>
            {#each day.exercises as e, ei (e.id ?? `${e.exercise_id}-${ei}`)}
              <div class="border-t border-line py-2">
                {#if edit}
                  <div class="flex items-center gap-2">
                    <span class="drag cursor-grab text-muted"><Icon name="drag" size={18} /></span>
                    <span class="flex-1 truncate text-sm font-medium">{e.exercise?.name}</span>
                    <button class="p-1 text-danger" onclick={() => (day.exercises = day.exercises.filter((_, i) => i !== ei))} aria-label="Entfernen"><Icon name="x" size={16} /></button>
                  </div>
                  <div class="mt-1 grid grid-cols-5 gap-1 text-xs">
                    <label>Sätze<input class="input px-1 py-1.5 text-center" type="number" bind:value={e.sets} /></label>
                    <label>Wdh. min<input class="input px-1 py-1.5 text-center" type="number" bind:value={e.rep_min} /></label>
                    <label>Wdh. max<input class="input px-1 py-1.5 text-center" type="number" bind:value={e.rep_max} /></label>
                    <label>Pause s<input class="input px-1 py-1.5 text-center" type="number" step="15" bind:value={e.rest_seconds} /></label>
                    <label>Supers.<input class="input px-1 py-1.5 text-center" maxlength="2" placeholder="–" bind:value={e.superset_group} /></label>
                  </div>
                {:else}
                  <a href="/training/exercises/{e.exercise_id}" class="flex justify-between text-sm">
                    <span>{e.superset_group ? `${e.superset_group.toUpperCase()} · ` : ''}{e.exercise?.name}</span>
                    <span class="text-muted tabular-nums">{e.sets}× {e.rep_min}–{e.rep_max} · {e.rest_seconds}s</span>
                  </a>
                {/if}
              </div>
            {/each}
          </div>
          {#if edit}<button class="btn-soft btn-sm mt-2 w-full" onclick={() => openPicker(di)}><Icon name="plus" size={16} /> Übung</button>{/if}
        </div>
      {/each}
    </div>
    {#if edit}
      <button class="btn-soft w-full" onclick={() => (plan.days = [...plan.days, { name: `Tag ${plan.days.length + 1}`, weekday: null, exercises: [] }])}><Icon name="plus" /> Trainingstag</button>
    {/if}
  {/if}
</div>

<Sheet bind:open={picker.open} title="Übung wählen" full>
  <input class="input mb-3" placeholder="Suchen …" bind:value={q} />
  {#each filtered as e}
    <button class="list-row w-full text-left" onclick={() => addEx(e)}>
      <div class="flex-1"><div class="font-medium">{e.name}</div><div class="text-xs text-muted">{e.primary_muscles.map((m) => MUSCLES[m]).join(', ')}</div></div>
      <Icon name="plus" size={18} class="text-accent" />
    </button>
  {/each}
</Sheet>
{#if plan}<ShareSheet bind:open={shareOpen} type="plan" id={plan.id} />{/if}

<Sheet bind:open={coach.open} title="Plan mit Coach bearbeiten" full>
  <div class="space-y-3">
    <p class="text-sm text-muted">Beschreibe, was sich ändern soll – der Coach kennt deinen Plan und deine letzten Trainings.
      Du siehst danach ein Vorher/Nachher und entscheidest selbst.</p>
    <div class="flex flex-wrap gap-1.5">{#each IDEAS as i}<button class="chip text-xs" onclick={() => (coach.request = i)}>{i}</button>{/each}</div>
    <textarea class="input" rows="3" placeholder="z. B. Ersetze Kniebeugen durch etwas Knieschonendes und mache Freitag zum Armtag" bind:value={coach.request}></textarea>
    <button class="btn-primary w-full" disabled={coach.busy} onclick={askCoach}><Icon name="sparkles" size={18} /> {coach.busy ? 'Coach überarbeitet den Plan …' : 'Vorschlag erstellen'}</button>
    {#if coach.text}<div class="rounded-2xl bg-surface-2 p-3 text-sm leading-relaxed">{@html md(coach.text)}</div>{/if}
    {#each coach.actions as a (a.id)}<ActionCard action={a} onresolved={resolved} />{/each}
  </div>
</Sheet>

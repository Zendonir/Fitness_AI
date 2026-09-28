<script>
  // Vorher/Nachher eines Trainingsplans (Coach-Vorschlag) – Tage und Übungen mit Änderungen markiert
  let { before = null, after } = $props();
  const WD = ['Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So'];
  const fmt = (e) => `${e.sets}× ${e.rep_min}–${e.rep_max}${e.target_rpe ? ` @${e.target_rpe}` : ''} · ${e.rest_seconds}s${e.superset_group ? ` · SS ${e.superset_group.toUpperCase()}` : ''}`;

  const rows = $derived.by(() => {
    const bDays = before?.days || [];
    const byId = Object.fromEntries(bDays.filter((d) => d.id).map((d) => [d.id, d]));
    const out = [];
    for (const d of after.days || []) {
      const old = d.id ? byId[d.id] : null;
      const status = !old ? 'new' : 'kept';
      // Zuordnung: gleiche Position+Übung → sonst gleiche Übung woanders → sonst an gleicher Position ersetzt
      const oldList = old?.exercises || [];
      const used = new Set();
      const match = new Array(d.exercises.length).fill(-1);
      d.exercises.forEach((e, i) => { if (oldList[i] && oldList[i].exercise_id === e.exercise_id) { match[i] = i; used.add(i); } });
      d.exercises.forEach((e, i) => {
        if (match[i] >= 0) return;
        const j = oldList.findIndex((o, k) => !used.has(k) && o.exercise_id === e.exercise_id);
        if (j >= 0) { match[i] = j; used.add(j); }
      });
      const exRows = d.exercises.map((e, i) => {
        if (!old) return { e, kind: 'new' };
        if (match[i] >= 0) {
          const o = oldList[match[i]];
          return { e, o, kind: fmt(o) !== fmt(e) ? 'changed' : match[i] !== i ? 'moved' : 'same' };
        }
        if (oldList[i] && !used.has(i) && !d.exercises.some((x) => x.exercise_id === oldList[i].exercise_id)) {
          used.add(i);
          return { e, o: oldList[i], kind: 'replaced' };
        }
        return { e, kind: 'added' };
      });
      oldList.forEach((o, k) => { if (!used.has(k)) exRows.push({ e: o, kind: 'removed' }); });
      out.push({ d, old, status, renamed: old && old.day !== d.day, weekdayChanged: old && old.weekday !== d.weekday, exRows });
    }
    const keptIds = new Set((after.days || []).map((d) => d.id).filter(Boolean));
    for (const d of bDays) if (!keptIds.has(d.id)) out.push({ d, status: 'removed', exRows: [] });
    return out;
  });
  const settings = $derived.by(() => {
    if (!before) return [`${after.weeks} Wochen`, after.deload_weeks?.length ? `Deload W${after.deload_weeks.join(', ')}` : 'ohne Deload'];
    const s = [];
    if (before.name !== after.name) s.push(`Name: ${before.name} → ${after.name}`);
    if (before.weeks !== after.weeks) s.push(`Wochen: ${before.weeks} → ${after.weeks}`);
    if (JSON.stringify(before.deload_weeks) !== JSON.stringify(after.deload_weeks)) s.push(`Deload: ${before.deload_weeks.join(', ') || '–'} → ${after.deload_weeks.join(', ') || '–'}`);
    return s;
  });
  const onlyChanged = (r) => r.status !== 'kept' || r.renamed || r.weekdayChanged || r.exRows.some((x) => x.kind !== 'same');
  let showAll = $state(false);
</script>

{#if settings.length}<div class="mb-2 flex flex-wrap gap-1">{#each settings as s}<span class="chip text-xs">{s}</span>{/each}</div>{/if}
{#each rows.filter((r) => showAll || !before || onlyChanged(r)) as r}
  <div class="mb-2 rounded-xl border p-2 {r.status === 'new' ? 'border-accent/50 bg-accent/5' : r.status === 'removed' ? 'border-danger/40 bg-danger/5 opacity-70' : 'border-line'}">
    <div class="mb-1 flex items-center gap-1.5 font-semibold">
      {#if r.status === 'new'}<span class="text-accent">+</span>{:else if r.status === 'removed'}<span class="text-danger">−</span>{/if}
      <span class={r.status === 'removed' ? 'line-through' : ''}>{r.d.day}</span>
      {#if r.renamed}<span class="text-xs font-normal text-muted">(vorher {r.old.day})</span>{/if}
      {#if r.weekdayChanged}<span class="chip bg-accent/20 py-0 text-[10px]">{r.old.weekday != null ? WD[r.old.weekday] : 'ohne'} → {r.d.weekday != null ? WD[r.d.weekday] : 'ohne Tag'}</span>
      {:else if r.d.weekday !== null && r.d.weekday !== undefined}<span class="chip py-0 text-[10px]">{WD[r.d.weekday]}</span>{/if}
    </div>
    {#each r.exRows as x}
      {#if showAll || x.kind !== 'same' || !before}
        <div class="flex justify-between gap-2 text-xs {x.kind === 'removed' ? 'text-danger line-through' : x.kind === 'added' || x.kind === 'new' ? 'text-accent' : ''}">
          <span>{x.kind === 'added' ? '+ ' : x.kind === 'removed' ? '− ' : x.kind === 'moved' ? '↕ ' : x.kind === 'changed' ? '✎ ' : x.kind === 'replaced' ? '⇄ ' : ''}{#if x.kind === 'replaced'}<span class="text-muted line-through">{x.o.exercise}</span> → <span class="text-accent">{x.e.exercise}</span>{:else}{x.e.exercise}{/if}</span>
          <span class="text-right tabular-nums">{#if x.kind === 'changed'}<span class="text-muted line-through">{fmt(x.o)}</span><br />{/if}{fmt(x.e)}</span>
        </div>
      {/if}
    {/each}
    {#if before && !r.exRows.some((x) => x.kind !== 'same') && r.status === 'kept'}<p class="text-xs text-muted">Übungen unverändert</p>{/if}
  </div>
{/each}
{#if before}<button class="text-xs text-accent" onclick={() => (showAll = !showAll)}>{showAll ? 'Nur Änderungen' : 'Ganzen Plan anzeigen'}</button>{/if}

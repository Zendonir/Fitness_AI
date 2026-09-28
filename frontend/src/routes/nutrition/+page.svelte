<script>
  import { page } from '$app/state';
  import { api } from '$lib/api.js';
  import { session } from '$lib/session.svelte.js';
  import { toast, toastError } from '$lib/toast.svelte.js';
  import { addDays, energy, energyUnit, fmtNum, today } from '$lib/units.js';
  import { success, tap } from '$lib/haptics.js';
  import DateNav from '$components/DateNav.svelte';
  import Header from '$components/Header.svelte';
  import Icon from '$components/Icon.svelte';
  import Ring from '$components/Ring.svelte';
  import Sheet from '$components/Sheet.svelte';
  import Skeleton from '$components/Skeleton.svelte';

  let day = $state(page.url.searchParams.get('day') || today());
  let data = $state(null);
  let edit = $state(null);
  let menuOpen = $state(false);
  let templates = $state([]);

  async function load() {
    try { data = await api.get(`/api/meals?day=${day}`); } catch (e) { toastError(e); }
  }
  $effect(() => { day; load(); });

  async function water(ml) { tap(); await api.post('/api/water', { day, ml }); success(); load(); }
  async function copyYesterday() {
    const r = await api.post('/api/meals/copy', { from_day: addDays(day, -1), to_day: day });
    toast(r.copied ? `${r.copied} Einträge kopiert` : 'Gestern war nichts geloggt', r.copied ? 'success' : 'info');
    menuOpen = false; load();
  }
  async function saveTemplate() {
    const name = prompt('Name der Vorlage', 'Standardtag');
    if (!name) return;
    try { await api.post('/api/day-templates', { name, from_day: day }); toast('Vorlage gespeichert', 'success'); } catch (e) { toastError(e); }
  }
  async function openMenu() { menuOpen = true; templates = await api.get('/api/day-templates'); }
  async function applyTemplate(t) {
    await api.post(`/api/day-templates/${t.id}/apply?day=${day}`);
    menuOpen = false; toast('Vorlage angewendet', 'success'); load();
  }
  async function saveEdit() {
    try {
      await api.patch(`/api/meals/${edit.id}`, edit.servings ? { servings: Number(edit.servings), slot: edit.slot } : { grams: Number(edit.grams), slot: edit.slot });
      edit = null; load();
    } catch (e) { toastError(e); }
  }
  async function del() { await api.del(`/api/meals/${edit.id}`); edit = null; load(); }
  const show = (k) => (session.settings?.visible_nutrients || []).includes(k);
</script>

<Header title="Ernährung">
  {#snippet actions()}
    <a href="/nutrition/recipes" class="p-2 text-muted" aria-label="Rezepte"><Icon name="book" /></a>
    <button class="p-2 text-muted" onclick={openMenu} aria-label="Mehr"><Icon name="more" /></button>
  {/snippet}
</Header>

<div class="space-y-3 px-4">
  <DateNav bind:value={day} />
  {#if !data}<Skeleton lines={4} />{:else}
    <div class="card">
      <div class="flex items-center justify-around">
        <Ring value={energy(data.totals.kcal)} max={energy(data.targets.kcal)} size={104} stroke={10} big sub={`/ ${energy(data.targets.kcal)} ${energyUnit()}`} />
        <div class="flex-1 space-y-2 pl-4">
          {#each [['protein', 'Protein'], ['carbs', 'Kohlenhydrate'], ['fat', 'Fett'], ['fiber', 'Ballaststoffe']] as [k, l]}
            {#if show(k)}
              <div>
                <div class="flex justify-between text-xs"><span>{l}</span><span class="tabular-nums text-muted">{fmtNum(data.totals[k], 0)} / {fmtNum(data.targets[k], 0)} g</span></div>
                <div class="h-2 overflow-hidden rounded-full bg-surface-2"><div class="h-full rounded-full transition-all duration-700" style="width:{Math.min(100, (data.totals[k] / (data.targets[k] || 1)) * 100)}%; background: var(--{k})"></div></div>
              </div>
            {/if}
          {/each}
        </div>
      </div>
      <p class="mt-2 text-center text-xs text-muted">{data.day_type === 'training' ? 'Trainingstag' : 'Ruhetag'} · Untergrenze {data.floors.kcal} kcal / {data.floors.protein} g Protein</p>
    </div>

    {#if show('water')}
      <div class="card flex items-center gap-3 py-3">
        <Icon name="water" class="text-protein" />
        <div class="flex-1"><div class="font-semibold tabular-nums">{fmtNum(data.water_ml / 1000, 2)} l <span class="text-sm font-normal text-muted">/ {(session.settings?.water_goal_ml || 2500) / 1000} l</span></div></div>
        <button class="btn-soft btn-sm" onclick={() => water(250)}>+250</button>
        <button class="btn-soft btn-sm" onclick={() => water(500)}>+500</button>
      </div>
    {/if}

    {#each data.slots as slot}
      <div class="card p-0">
        <div class="flex items-center justify-between px-4 pt-3 pb-1">
          <span class="font-semibold">{slot.name}</span>
          <span class="text-sm tabular-nums text-muted">{fmtNum(energy(slot.kcal), 0)} {energyUnit()}</span>
        </div>
        {#each slot.entries as e}
          <button class="list-row w-full text-left" onclick={() => (edit = { ...e })}>
            <div class="min-w-0 flex-1"><div class="truncate text-sm font-medium">{e.name}</div>
              <div class="text-xs text-muted">{e.servings ? `${e.servings} Port.` : `${fmtNum(e.grams, 0)} g`} · {fmtNum(e.protein, 0)} P · {fmtNum(e.carbs, 0)} K · {fmtNum(e.fat, 0)} F</div></div>
            <span class="text-sm tabular-nums">{fmtNum(energy(e.kcal), 0)}</span>
          </button>
        {/each}
        <a href="/nutrition/add?slot={encodeURIComponent(slot.name)}&day={day}" class="flex items-center gap-2 px-4 py-3 text-sm font-medium text-accent"><Icon name="plus" size={18} /> Hinzufügen</a>
      </div>
    {/each}
  {/if}
</div>

<a href="/nutrition/add?day={day}" class="fixed right-4 z-30 rounded-full bg-accent p-4 text-white shadow-xl active:scale-95"
  style="bottom: calc(env(safe-area-inset-bottom) + var(--tabbar-h) + 16px)" aria-label="Essen hinzufügen"><Icon name="plus" size={26} /></a>

<Sheet open={!!edit} title={edit?.name || ''} onclose={() => (edit = null)}>
  {#if edit}
    <div class="space-y-3">
      {#if edit.servings}
        <label class="block"><span class="label">Portionen</span><input class="input" inputmode="decimal" type="number" step="0.25" bind:value={edit.servings} /></label>
      {:else}
        <label class="block"><span class="label">Menge (g)</span><input class="input" inputmode="decimal" type="number" bind:value={edit.grams} /></label>
      {/if}
      <label class="block"><span class="label">Mahlzeit</span><select class="input" bind:value={edit.slot}>{#each session.settings?.meal_slots || [] as s}<option>{s}</option>{/each}</select></label>
      <div class="flex gap-2"><button class="btn-primary flex-1" onclick={saveEdit}>Speichern</button><button class="btn-soft text-danger" onclick={del}><Icon name="trash" /></button></div>
    </div>
  {/if}
</Sheet>

<Sheet bind:open={menuOpen} title="Aktionen">
  <div class="space-y-2">
    <button class="btn-soft w-full justify-start" onclick={copyYesterday}><Icon name="copy" /> Vortag kopieren</button>
    <button class="btn-soft w-full justify-start" onclick={saveTemplate}><Icon name="star" /> Tag als Vorlage speichern</button>
    <a class="btn-soft w-full justify-start" href="/nutrition/foods"><Icon name="apple" /> Eigene Lebensmittel</a>
    <a class="btn-soft w-full justify-start" href="/nutrition/recipes"><Icon name="book" /> Rezepte</a>
    <a class="btn-soft w-full justify-start" href="/nutrition/mealplan"><Icon name="calendar" /> Mahlzeitenplan & Einkaufsliste</a>
    {#if templates.length}<p class="section-title">Vorlage anwenden</p>
      {#each templates as t}<button class="btn-soft w-full justify-between" onclick={() => applyTemplate(t)}>{t.name}<span class="text-sm text-muted">{t.kcal} kcal</span></button>{/each}
    {/if}
  </div>
</Sheet>

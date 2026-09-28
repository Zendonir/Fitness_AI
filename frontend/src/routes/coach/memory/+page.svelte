<script>
  import { onMount } from 'svelte';
  import { api } from '$lib/api.js';
  import { toast, toastError } from '$lib/toast.svelte.js';
  import { fmtDate } from '$lib/units.js';
  import Header from '$components/Header.svelte';
  import Icon from '$components/Icon.svelte';

  let tab = $state('profile');
  let profile = $state(null), notes = $state([]), summaries = $state([]);
  let newNote = $state({ content: '', category: 'general', importance: 2 });
  const CAT = { general: 'Allgemein', training: 'Training', nutrition: 'Ernährung', health: 'Gesundheit', preference: 'Vorliebe', goal: 'Ziel' };
  const FIELDS = [['goals', 'Ziele'], ['preferences', 'Vorlieben'], ['dislikes', 'Abneigungen'], ['limitations', 'Einschränkungen / Verletzungen'], ['equipment', 'Equipment'], ['schedule', 'Trainingszeiten']];

  onMount(async () => {
    [profile, notes, summaries] = await Promise.all([api.get('/api/coach/profile'), api.get('/api/coach/notes'), api.get('/api/coach/summaries')]);
  });
  async function saveProfile() {
    try { profile = await api.put('/api/coach/profile', profile); toast('Gespeichert', 'success'); } catch (e) { toastError(e); }
  }
  async function addNote() {
    if (!newNote.content) return;
    notes = [await api.post('/api/coach/notes', newNote), ...notes];
    newNote = { content: '', category: 'general', importance: 2 };
  }
  async function delNote(n) { await api.del(`/api/coach/notes/${n.id}`); notes = notes.filter((x) => x.id !== n.id); }
  async function delSummary(s) { await api.del(`/api/coach/summaries/${s.id}`); summaries = summaries.filter((x) => x.id !== s.id); }
  async function wipe() {
    if (!confirm('Gesamtes Gedächtnis (Notizen und Zusammenfassungen) löschen?')) return;
    await api.del('/api/coach/memory'); notes = []; summaries = []; toast('Gedächtnis gelöscht');
  }
</script>

<Header title="Was der Coach weiß" back="/coach" />
<div class="px-4">
  <div class="mb-3 flex gap-1.5">
    {#each [['profile', 'Profil'], ['notes', `Notizen (${notes.length})`], ['summaries', 'Verlauf']] as [k, l]}<button class={tab === k ? 'chip-active' : 'chip'} onclick={() => (tab = k)}>{l}</button>{/each}
  </div>

  {#if tab === 'profile' && profile}
    <div class="space-y-3">
      <label class="block"><span class="label">Erfahrung</span>
        <select class="input" bind:value={profile.experience}><option value="beginner">Einsteiger</option><option value="intermediate">Fortgeschritten</option><option value="advanced">Profi</option></select></label>
      {#each FIELDS as [k, l]}<label class="block"><span class="label">{l}</span><textarea class="input" rows="2" bind:value={profile[k]}></textarea></label>{/each}
      <button class="btn-primary w-full" onclick={saveProfile}>Speichern</button>
    </div>
  {:else if tab === 'notes'}
    <p class="mb-3 text-sm text-muted">Der Coach merkt sich wichtige Erkenntnisse aus Gesprächen. Du kannst alles einsehen, ergänzen und löschen.</p>
    <div class="card mb-3 space-y-2">
      <textarea class="input" rows="2" placeholder="Neue Notiz, z. B. „Trainiert lieber morgens“" bind:value={newNote.content}></textarea>
      <div class="flex gap-2"><select class="input py-2" bind:value={newNote.category}>{#each Object.entries(CAT) as [k, l]}<option value={k}>{l}</option>{/each}</select>
        <button class="btn-primary" onclick={addNote}><Icon name="plus" /></button></div>
    </div>
    <div class="card p-0">
      {#each notes as n}
        <div class="list-row">
          <div class="flex-1"><div class="text-sm">{n.content}</div><div class="text-xs text-muted">{CAT[n.category] || n.category} · {n.source === 'coach' ? 'vom Coach' : 'von dir'} · {fmtDate(n.created_at, { day: '2-digit', month: '2-digit', year: '2-digit' })}</div></div>
          <button class="text-muted" onclick={() => delNote(n)} aria-label="Löschen"><Icon name="trash" size={16} /></button>
        </div>
      {:else}<p class="p-4 text-sm text-muted">Noch keine Notizen</p>{/each}
    </div>
  {:else if tab === 'summaries'}
    <div class="space-y-2">
      {#each summaries as s}
        <div class="card text-sm">
          <div class="mb-1 flex justify-between text-xs text-muted"><span>{({ day: 'Tag', week: 'Woche', month: 'Monat' })[s.period]} ab {fmtDate(s.period_start, { day: '2-digit', month: '2-digit', year: 'numeric' })}</span>
            <button onclick={() => delSummary(s)} aria-label="Löschen"><Icon name="trash" size={14} /></button></div>
          {s.content}
        </div>
      {:else}<p class="text-sm text-muted">Zusammenfassungen entstehen automatisch jede Nacht (Tag), montags (Woche) und am Monatsersten.</p>{/each}
    </div>
  {/if}
  <button class="btn-ghost mt-6 w-full text-danger" onclick={wipe}>Gedächtnis komplett löschen</button>
</div>

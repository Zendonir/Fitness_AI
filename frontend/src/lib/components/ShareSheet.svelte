<script>
  import { api } from '$lib/api.js';
  import { toast, toastError } from '$lib/toast.svelte.js';
  import Sheet from './Sheet.svelte';
  let { open = $bindable(false), type, id } = $props();
  let share = $state({ visibility: 'private', user_ids: [] });
  let users = $state([]);
  $effect(() => {
    if (open) {
      api.get(`/api/share/${type}/${id}`).then((s) => (share = s)).catch(toastError);
      api.get('/api/users/directory').then((u) => (users = u)).catch(() => {});
    }
  });
  function toggle(uid) {
    share.user_ids = share.user_ids.includes(uid) ? share.user_ids.filter((x) => x !== uid) : [...share.user_ids, uid];
  }
  async function save() {
    try {
      await api.put(`/api/share/${type}/${id}`, share);
      toast('Freigabe gespeichert', 'success');
      open = false;
    } catch (e) { toastError(e); }
  }
</script>

<Sheet bind:open title="Teilen">
  <div class="space-y-2">
    {#each [['private', 'Privat', 'Nur du'], ['shared', 'Bestimmte Benutzer', 'Ausgewählte Personen'], ['public', 'Alle', 'Alle Benutzer dieser Instanz']] as [v, l, d]}
      <button class="w-full rounded-2xl border p-3 text-left {share.visibility === v ? 'border-accent bg-accent/10' : 'border-line'}" onclick={() => (share.visibility = v)}>
        <div class="font-medium">{l}</div><div class="text-xs text-muted">{d}</div>
      </button>
    {/each}
    {#if share.visibility === 'shared'}
      <div class="card p-0">
        {#each users as u}
          <label class="list-row"><input type="checkbox" class="h-5 w-5 accent-[var(--accent)]" checked={share.user_ids.includes(u.id)} onchange={() => toggle(u.id)} />{u.display_name}</label>
        {:else}<p class="p-3 text-sm text-muted">Keine weiteren Benutzer</p>{/each}
      </div>
    {/if}
    <button class="btn-primary w-full" onclick={save}>Speichern</button>
  </div>
</Sheet>

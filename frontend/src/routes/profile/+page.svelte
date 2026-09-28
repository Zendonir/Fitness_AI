<script>
  import { onMount } from 'svelte';
  import { api } from '$lib/api.js';
  import { isAdmin, isTrainer, session } from '$lib/session.svelte.js';
  import { fmtDate } from '$lib/units.js';
  import Header from '$components/Header.svelte';
  import Icon from '$components/Icon.svelte';

  let comments = $state([]);
  onMount(async () => { comments = (await api.get('/api/me/comments').catch(() => [])).filter((c) => c.athlete_id === session.user.id); });
  async function logout() {
    await api.post('/api/auth/logout');
    location.href = '/login';
  }
  const items = [
    ['/settings?tab=profile', 'user', 'Profil & Ziele'],
    ['/settings?tab=appearance', 'sun', 'Darstellung & Einheiten'],
    ['/settings?tab=nutrition', 'apple', 'Ernährungseinstellungen'],
    ['/settings?tab=ai', 'sparkles', 'KI-Coach & Datenfreigaben'],
    ['/settings?tab=notifications', 'bell', 'Benachrichtigungen'],
    ['/settings?tab=security', 'lock', 'Sicherheit & Passkeys'],
    ['/settings?tab=sharing', 'share', 'Trainer & Teilen'],
    ['/settings?tab=integrations', 'link', 'Integrationen & API'],
    ['/settings?tab=data', 'download', 'Export, Import & Konto']
  ];
</script>

<Header title="Profil" back="/" />
<div class="space-y-4 px-4">
  <div class="card flex items-center gap-4">
    <div class="flex h-14 w-14 items-center justify-center rounded-full bg-accent text-xl font-bold text-white">{(session.user?.display_name || '?')[0].toUpperCase()}</div>
    <div><div class="text-lg font-semibold">{session.user?.display_name}</div><div class="text-sm text-muted">{session.user?.email} · {({ admin: 'Administrator', user: 'Benutzer', trainer: 'Trainer' })[session.user?.role]}</div></div>
  </div>
  {#if comments.length}
    <div class="card"><div class="mb-2 font-semibold">Trainer-Kommentare</div>
      {#each comments.slice(0, 5) as c}<div class="border-t border-line py-2 text-sm"><span class="font-medium">{c.trainer_name}:</span> {c.text}<div class="text-xs text-muted">{fmtDate(c.created_at)}</div></div>{/each}
    </div>
  {/if}
  <div class="card p-0">
    {#each items as [href, icon, label]}
      <a {href} class="list-row"><Icon name={icon} size={20} class="text-accent" /><span class="flex-1">{label}</span><Icon name="right" size={18} class="text-muted" /></a>
    {/each}
  </div>
  <div class="card p-0">
    <a href="/progress/metrics" class="list-row"><Icon name="chart" size={20} class="text-accent" /><span class="flex-1">Eigene Metriken</span><Icon name="right" size={18} class="text-muted" /></a>
    <a href="/coach/memory" class="list-row"><Icon name="book" size={20} class="text-accent" /><span class="flex-1">Coach-Gedächtnis</span><Icon name="right" size={18} class="text-muted" /></a>
    {#if isTrainer()}<a href="/trainer" class="list-row"><Icon name="user" size={20} class="text-accent" /><span class="flex-1">Meine Athleten</span><Icon name="right" size={18} class="text-muted" /></a>{/if}
    {#if isAdmin()}<a href="/admin" class="list-row"><Icon name="shield" size={20} class="text-accent" /><span class="flex-1">Administration</span><Icon name="right" size={18} class="text-muted" /></a>{/if}
  </div>
  <button class="btn-soft w-full text-danger" onclick={logout}><Icon name="logout" size={18} /> Abmelden</button>
  <p class="text-center text-xs text-muted">FitForge 1.0 · <a href="/api/docs" class="underline" data-sveltekit-reload>API-Doku</a></p>
</div>

<script>
  import { goto } from '$app/navigation';
  import { page } from '$app/state';
  import { onMount } from 'svelte';
  import { api } from '$lib/api.js';
  import { loadSession, session } from '$lib/session.svelte.js';
  import { toastError } from '$lib/toast.svelte.js';

  const invite = page.url.searchParams.get('invite');
  let email = $state(''), password = $state(''), name = $state(''), busy = $state(false);
  let inviteInfo = $state(null), inviteError = $state('');

  onMount(async () => {
    if (invite) {
      try {
        inviteInfo = await api.get(`/api/auth/invite/${invite}`);
        if (inviteInfo.email) email = inviteInfo.email;
      } catch (e) { inviteError = e.message; }
    }
  });
  const allowed = $derived(session.config?.needs_setup || session.config?.open_registration || (invite && inviteInfo));

  async function submit(e) {
    e.preventDefault();
    busy = true;
    try {
      await api.post('/api/auth/register', { email, password, display_name: name, invite });
      await loadSession();
      goto('/onboarding', { replaceState: true });
    } catch (e) { toastError(e); } finally { busy = false; }
  }
</script>

<div class="safe-top flex min-h-dvh flex-col justify-center px-6">
  <div class="mx-auto w-full max-w-sm">
    <img src="/icons/icon.svg" alt="" class="mx-auto mb-4 h-16 w-16 rounded-3xl" />
    <h1 class="mb-2 text-center text-2xl font-bold">
      {session.config?.needs_setup ? 'Ersten Admin anlegen' : 'Konto erstellen'}</h1>
    {#if session.config?.needs_setup}
      <p class="mb-6 text-center text-sm text-muted">Willkommen! Das erste Konto wird automatisch Administrator.</p>
    {/if}
    {#if inviteError}<p class="mb-4 rounded-xl bg-danger/10 p-3 text-sm text-danger">{inviteError}</p>{/if}
    {#if allowed}
      <form class="space-y-3" onsubmit={submit}>
        <input class="input" placeholder="Name" bind:value={name} autocomplete="name" />
        <input class="input" type="email" placeholder="E-Mail" bind:value={email} required autocomplete="email" readonly={!!inviteInfo?.email} />
        <input class="input" type="password" placeholder="Passwort (min. 10 Zeichen)" bind:value={password} minlength="10" required autocomplete="new-password" />
        <button class="btn-primary w-full" disabled={busy}>Registrieren</button>
      </form>
    {:else if !invite}
      <p class="text-center text-muted">Die Registrierung ist nur mit Einladungslink möglich. Bitte wende dich an den Administrator.</p>
    {/if}
    <p class="mt-6 text-center text-sm"><a class="text-accent" href="/login">Zur Anmeldung</a></p>
  </div>
</div>

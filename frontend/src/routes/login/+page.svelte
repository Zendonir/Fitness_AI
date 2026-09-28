<script>
  import { goto } from '$app/navigation';
  import { page } from '$app/state';
  import { api } from '$lib/api.js';
  import { loadSession, session } from '$lib/session.svelte.js';
  import { getPasskey, passkeysSupported } from '$lib/webauthn.js';
  import { toastError } from '$lib/toast.svelte.js';
  import Icon from '$components/Icon.svelte';

  let email = $state(''), password = $state(''), totp = $state('');
  let needTotp = $state(false), busy = $state(false);
  const next = page.url.searchParams.get('next') || '/';
  const err = page.url.searchParams.get('error');

  $effect(() => { if (session.config?.needs_setup) goto('/register', { replaceState: true }); });

  async function done() {
    await loadSession();
    goto(session.user?.onboarding_done ? next : '/onboarding', { replaceState: true });
  }
  async function login(e) {
    e.preventDefault();
    busy = true;
    try {
      const r = await api.post('/api/auth/login', { email, password, totp: totp || null }, { allow401: true });
      if (r.totp_required) { needTotp = true; return; }
      await done();
    } catch (e) { toastError(e); } finally { busy = false; }
  }
  async function passkey() {
    try {
      const opts = await api.post('/api/auth/passkey/login/options');
      const credential = await getPasskey(opts);
      await api.post('/api/auth/passkey/login/verify', { credential }, { allow401: true });
      await done();
    } catch (e) { if (e.name !== 'NotAllowedError') toastError(e); }
  }
</script>

<div class="safe-top flex min-h-dvh flex-col justify-center px-6">
  <div class="mx-auto w-full max-w-sm">
    <img src="/icons/icon.svg" alt="" class="mx-auto mb-4 h-20 w-20 rounded-3xl shadow-lg" />
    <h1 class="mb-1 text-center text-3xl font-bold">FitForge</h1>
    <p class="mb-8 text-center text-muted">Training · Ernährung · KI-Coach</p>
    {#if err}<p class="mb-4 rounded-xl bg-danger/10 p-3 text-sm text-danger">
      {err === 'oidc_no_account' ? 'Kein Konto für diese SSO-Anmeldung. Bitte vom Admin einladen lassen.' : 'Anmeldung nicht möglich.'}</p>{/if}
    <form class="space-y-3" onsubmit={login}>
      {#if !needTotp}
        <input class="input" type="email" autocomplete="username webauthn" placeholder="E-Mail" bind:value={email} required />
        <input class="input" type="password" autocomplete="current-password" placeholder="Passwort" bind:value={password} required />
      {:else}
        <p class="text-sm text-muted">Code aus deiner Authenticator-App:</p>
        <!-- svelte-ignore a11y_autofocus -->
        <input class="input text-center text-2xl tracking-[0.4em]" inputmode="numeric" autocomplete="one-time-code" maxlength="6" bind:value={totp} autofocus />
      {/if}
      <button class="btn-primary w-full" disabled={busy}>{needTotp ? 'Bestätigen' : 'Anmelden'}</button>
    </form>
    {#if passkeysSupported() && !needTotp}
      <button class="btn-soft mt-3 w-full" onclick={passkey}><Icon name="lock" size={18} /> Mit Passkey anmelden</button>
    {/if}
    {#if session.config?.oidc_enabled}
      <a class="btn-soft mt-3 w-full" href="/api/auth/oidc/login" data-sveltekit-reload><Icon name="shield" size={18} /> Mit {session.config.oidc_name} anmelden</a>
    {/if}
    {#if session.config?.open_registration}
      <p class="mt-6 text-center text-sm text-muted">Noch kein Konto? <a class="text-accent font-semibold" href="/register">Registrieren</a></p>
    {/if}
  </div>
</div>

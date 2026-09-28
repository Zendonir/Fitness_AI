<script>
  import { goto } from '$app/navigation';
  import { page } from '$app/state';
  import { api } from '$lib/api.js';
  import { toast, toastError } from '$lib/toast.svelte.js';
  const token = page.url.searchParams.get('token');
  let password = $state(''), password2 = $state(''), busy = $state(false);
  async function submit(e) {
    e.preventDefault();
    if (password !== password2) return toastError('Passwörter stimmen nicht überein');
    busy = true;
    try {
      await api.post('/api/auth/password/reset', { token, password });
      toast('Passwort gesetzt – bitte anmelden', 'success');
      goto('/login');
    } catch (e) { toastError(e); } finally { busy = false; }
  }
</script>
<div class="safe-top flex min-h-dvh flex-col justify-center px-6">
  <form class="mx-auto w-full max-w-sm space-y-3" onsubmit={submit}>
    <h1 class="mb-4 text-center text-2xl font-bold">Neues Passwort</h1>
    <input class="input" type="password" placeholder="Neues Passwort" bind:value={password} minlength="10" required autocomplete="new-password" />
    <input class="input" type="password" placeholder="Wiederholen" bind:value={password2} required autocomplete="new-password" />
    <button class="btn-primary w-full" disabled={busy || !token}>Speichern</button>
  </form>
</div>
